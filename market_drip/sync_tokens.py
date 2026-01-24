"""Token sync logic using Gamma market detail endpoint."""

from __future__ import annotations

import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from .clients.gamma import GammaClient, GammaHttpError
from .clients.http import HttpError
from .db.db import connect
from .sync import _is_short_cycle, _upsert_token
from .utils.progress import format_duration

SECONDS_PER_DAY = 24 * 60 * 60
DEFAULT_LIMIT = 1000
DEFAULT_ROLLING_DAYS = 90
DEFAULT_STATUSES = ["active", "open"]
DEFAULT_CONCURRENCY = 10
DEFAULT_MAX_ATTEMPTS = 5
PROGRESS_EVERY = 50
DEBUG_SAMPLE_MARKETS = 3


@dataclass
class TokenSyncCounters:
    markets_selected: int = 0
    markets_processed: int = 0
    markets_skipped: int = 0
    tokens_inserted: int = 0
    tokens_updated: int = 0
    failed_http: int = 0
    failed_parse: int = 0
    missing_tokens: int = 0


_thread_local = threading.local()


def _get_gamma_client() -> GammaClient:
    client = getattr(_thread_local, "gamma_client", None)
    if client is None:
        client = GammaClient()
        _thread_local.gamma_client = client
    return client


def _compute_backoff_seconds(attempt: int) -> float:
    base = min(60.0, 0.5 * (2 ** max(0, attempt - 1)))
    jitter = random.uniform(0.8, 1.2)
    return base * jitter


def _debug_enabled() -> bool:
    return os.getenv("MARKET_DRIP_DEBUG") == "1"


def _get_top_level_keys(data: Any) -> list[str]:
    if isinstance(data, dict):
        return list(data.keys())
    return []


def _get_nested_dict(data: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = data.get(key)
    if isinstance(value, dict):
        return value
    return None


def _coalesce_list(data: dict[str, Any], key: str) -> list[Any] | None:
    value = data.get(key)
    if isinstance(value, list):
        return value
    return None


def _extract_token_ids(data: dict[str, Any]) -> list[str]:
    candidates = [
        "clobTokenIds",
        "clob_token_ids",
        "tokenIds",
        "token_ids",
        "outcomeTokens",
        "outcome_tokens",
    ]
    token_ids: list[str] = []
    for key in candidates:
        items = _coalesce_list(data, key)
        if items is None:
            nested = _get_nested_dict(data, "market") or _get_nested_dict(data, "result")
            if nested is not None:
                items = _coalesce_list(nested, key)
        if items:
            for item in items:
                if item is None:
                    continue
                token_ids.append(str(item))
            if token_ids:
                return token_ids
    return token_ids


def _extract_outcome_pairs(data: dict[str, Any]) -> list[tuple[str, str]]:
    outcomes = _coalesce_list(data, "outcomes")
    if outcomes is None:
        nested = _get_nested_dict(data, "market") or _get_nested_dict(data, "result")
        if nested is not None:
            outcomes = _coalesce_list(nested, "outcomes")

    pairs: list[tuple[str, str]] = []
    if outcomes:
        if all(isinstance(item, dict) for item in outcomes):
            for item in outcomes:
                if not isinstance(item, dict):
                    continue
                name = item.get("name") or item.get("outcome") or item.get("label") or ""
                token_id = (
                    item.get("clobTokenId")
                    or item.get("clob_token_id")
                    or item.get("token_id")
                    or item.get("tokenId")
                    or item.get("id")
                )
                if token_id is None:
                    continue
                pairs.append((str(name), str(token_id)))
            if pairs:
                return pairs

        if all(isinstance(item, str) for item in outcomes):
            token_ids = _extract_token_ids(data)
            if token_ids and len(token_ids) == len(outcomes):
                return [(str(name), str(token_id)) for name, token_id in zip(outcomes, token_ids)]

    return pairs


def _select_markets(
    conn,
    now_ts: int,
    limit: int,
    offset: int,
    rolling_days: int,
    statuses: list[str],
) -> list[tuple[int, str | None, int | None]]:
    if not statuses:
        return []
    placeholders = ",".join("?" for _ in statuses)
    cutoff_ts = now_ts - (rolling_days * SECONDS_PER_DAY)
    query = f"""
        SELECT m.market_pk, m.gamma_market_id, m.end_ts
        FROM markets m
        LEFT JOIN tokens t ON t.market_pk = m.market_pk
        WHERE t.market_pk IS NULL
          AND m.status IN ({placeholders})
          AND (m.end_ts IS NULL OR m.end_ts >= ?)
        ORDER BY m.updated_ts DESC
        LIMIT ? OFFSET ?
    """
    params: list[Any] = [*statuses, cutoff_ts, limit, offset]
    rows = conn.execute(query, params).fetchall()
    results: list[tuple[int, str | None, int | None]] = []
    for row in rows:
        market_id = None if row[1] is None else str(row[1])
        results.append((int(row[0]), market_id, row[2]))
    return results


def _token_exists(conn, token_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM tokens WHERE clob_token_id=? LIMIT 1", (token_id,)).fetchone()
    return row is not None


def _fetch_market_detail_with_retry(
    market_id: str,
    max_attempts: int,
    debug_state: dict[str, int],
    debug_lock: threading.Lock,
) -> tuple[str, Any]:
    attempt = 0
    last_error: Exception | None = None
    while attempt < max_attempts:
        attempt += 1
        try:
            gamma = _get_gamma_client()
            data = gamma.get_market_detail(market_id)
            if _debug_enabled():
                with debug_lock:
                    if debug_state["remaining"] > 0:
                        debug_state["remaining"] -= 1
                        url = f"{gamma.base_url}/markets/{market_id}"
                        keys = _get_top_level_keys(data)
                        print(f"[sync-tokens][debug] url={url} status=200 keys={keys}")
            return ("ok", data)
        except GammaHttpError as exc:
            last_error = exc
            if exc.status_code == 429 or (500 <= exc.status_code <= 599):
                if attempt < max_attempts:
                    sleep_seconds = float(exc.retry_after_seconds or _compute_backoff_seconds(attempt))
                    time.sleep(sleep_seconds)
                    continue
            return ("http_error", exc)
        except HttpError as exc:
            last_error = exc
            if exc.message == "invalid json":
                return ("parse_error", exc)
            if exc.retriable and attempt < max_attempts:
                sleep_seconds = float(exc.retry_after_seconds or _compute_backoff_seconds(attempt))
                time.sleep(sleep_seconds)
                continue
            return ("http_error", exc)
        except Exception as exc:  # pragma: no cover - defensive catch
            last_error = exc
            return ("parse_error", exc)

    return ("http_error", last_error)


def sync_tokens(
    db_path: str,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    rolling_days: int = DEFAULT_ROLLING_DAYS,
    statuses: list[str] | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> dict[str, int]:
    if statuses is None:
        statuses = list(DEFAULT_STATUSES)
    now_ts = int(time.time())
    counters = TokenSyncCounters()
    start_time = time.time()

    print(
        "[sync-tokens] start limit={limit} offset={offset} rolling_days={days} statuses={statuses} concurrency={conc} max_attempts={attempts}".format(
            limit=limit,
            offset=offset,
            days=rolling_days,
            statuses=",".join(statuses),
            conc=concurrency,
            attempts=max_attempts,
        )
    )

    conn = connect(db_path)
    try:
        markets = _select_markets(conn, now_ts, limit, offset, rolling_days, statuses)
        counters.markets_selected = len(markets)
        if not markets:
            print("[sync-tokens] no markets selected")
            return counters.__dict__

        debug_state = {"remaining": DEBUG_SAMPLE_MARKETS}
        debug_lock = threading.Lock()
        batch_size = 100
        pending_writes = 0
        in_txn = False

        def _begin_txn() -> None:
            nonlocal in_txn
            if not in_txn:
                conn.execute("BEGIN")
                in_txn = True

        def _commit_txn() -> None:
            nonlocal in_txn, pending_writes
            if in_txn:
                conn.commit()
                in_txn = False
                pending_writes = 0

        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
            futures = {}
            for market_pk, market_id, end_ts in markets:
                if not market_id:
                    counters.markets_skipped += 1
                    continue
                future = executor.submit(
                    _fetch_market_detail_with_retry,
                    market_id,
                    max_attempts,
                    debug_state,
                    debug_lock,
                )
                futures[future] = (market_pk, market_id, end_ts)

            for idx, future in enumerate(as_completed(futures), start=1):
                market_pk, market_id, end_ts = futures[future]
                counters.markets_processed += 1
                status, payload = future.result()

                if status != "ok":
                    if isinstance(payload, (GammaHttpError, HttpError)):
                        code = getattr(payload, "status_code", 0)
                        reason = getattr(payload, "message", "error")
                        counters.failed_http += 1
                        print(f"[sync-tokens] error market_id={market_id} status={code} reason={reason}")
                    else:
                        counters.failed_parse += 1
                        print(f"[sync-tokens] error market_id={market_id} status=0 reason=parse_error")
                else:
                    data = payload
                    if not isinstance(data, dict):
                        counters.failed_parse += 1
                        print(f"[sync-tokens] error market_id={market_id} status=0 reason=parse_error")
                    else:
                        pairs = _extract_outcome_pairs(data)
                        if not pairs:
                            counters.missing_tokens += 1
                            print(f"[sync-tokens] warn market_id={market_id} status=0 reason=missing_tokens")
                        else:
                            short_cycle = _is_short_cycle(end_ts, now_ts) if end_ts is not None else 0
                            seen: set[str] = set()
                            _begin_txn()
                            for outcome_name, token_id in pairs:
                                if not token_id or token_id in seen:
                                    continue
                                seen.add(token_id)
                                existed = _token_exists(conn, token_id)
                                _upsert_token(conn, market_pk, outcome_name, token_id, short_cycle, now_ts)
                                if existed:
                                    counters.tokens_updated += 1
                                else:
                                    counters.tokens_inserted += 1
                                pending_writes += 1
                            if pending_writes >= batch_size:
                                _commit_txn()

                if idx % PROGRESS_EVERY == 0:
                    elapsed = format_duration(time.time() - start_time)
                    print(
                        "[sync-tokens] progress processed={processed} selected={selected} skipped={skipped} inserted={ins} updated={upd} failed_http={fh} failed_parse={fp} missing_tokens={mt} elapsed={elapsed}".format(
                            processed=counters.markets_processed,
                            selected=counters.markets_selected,
                            skipped=counters.markets_skipped,
                            ins=counters.tokens_inserted,
                            upd=counters.tokens_updated,
                            fh=counters.failed_http,
                            fp=counters.failed_parse,
                            mt=counters.missing_tokens,
                            elapsed=elapsed,
                        )
                    )

        if pending_writes > 0:
            _commit_txn()
    finally:
        conn.close()

    elapsed = format_duration(time.time() - start_time)
    print(
        "[sync-tokens] done selected={selected} processed={processed} skipped={skipped} inserted={ins} updated={upd} failed_http={fh} failed_parse={fp} missing_tokens={mt} elapsed={elapsed}".format(
            selected=counters.markets_selected,
            processed=counters.markets_processed,
            skipped=counters.markets_skipped,
            ins=counters.tokens_inserted,
            upd=counters.tokens_updated,
            fh=counters.failed_http,
            fp=counters.failed_parse,
            mt=counters.missing_tokens,
            elapsed=elapsed,
        )
    )

    return counters.__dict__
