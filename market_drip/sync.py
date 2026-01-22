"""Market sync logic."""

from __future__ import annotations

import time
from typing import Any

from .clients.gamma import DEFAULT_GAMMA_BASE_URL, GammaClient, GammaMarket
from .db.db import connect
from .utils.progress import SlidingWindow, format_duration

SECONDS_14_DAYS = 14 * 24 * 60 * 60
SECONDS_30_DAYS = 30 * 24 * 60 * 60


def _is_short_cycle(end_ts: int | None, now_ts: int) -> int:
    if end_ts is None:
        return 0
    if end_ts - now_ts > SECONDS_14_DAYS:
        return 0
    if end_ts < now_ts - SECONDS_30_DAYS:
        return 0
    return 1


def _upsert_market(conn, market: GammaMarket, now_ts: int) -> int:
    row = conn.execute(
        """
        INSERT INTO markets (
            gamma_market_id, slug, question, status, end_ts, updated_ts
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(gamma_market_id) DO UPDATE SET
            slug=excluded.slug,
            question=excluded.question,
            status=excluded.status,
            end_ts=excluded.end_ts,
            updated_ts=excluded.updated_ts
        RETURNING market_pk
        """,
        (
            market.gamma_market_id,
            market.slug,
            market.question,
            market.status,
            market.end_ts,
            now_ts,
        ),
    ).fetchone()
    return int(row[0])


def _upsert_token(
    conn,
    market_pk: int,
    outcome_name: str,
    token_id: str,
    is_short_cycle: int,
    now_ts: int,
) -> None:
    conn.execute(
        """
        INSERT INTO tokens (
            clob_token_id, market_pk, outcome_name, is_short_cycle, updated_ts
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(clob_token_id) DO UPDATE SET
            market_pk=excluded.market_pk,
            outcome_name=excluded.outcome_name,
            is_short_cycle=excluded.is_short_cycle,
            updated_ts=excluded.updated_ts
        """,
        (token_id, market_pk, outcome_name, is_short_cycle, now_ts),
    )


def sync_markets(
    db_path: str,
    now_ts: int | None = None,
    limit: int = 100,
    max_pages: int | None = None,
    base_url: str | None = None,
    gamma_filters: dict[str, Any] | None = None,
) -> None:
    if now_ts is None:
        now_ts = int(time.time())

    gamma = GammaClient(base_url=base_url or DEFAULT_GAMMA_BASE_URL)
    offset = 0
    page = 0
    total_items = 0
    window = SlidingWindow(10)
    start_time = time.time()

    conn = connect(db_path)
    try:
        while True:
            page_start = time.time()
            markets = gamma.list_markets(limit=limit, offset=offset, **(gamma_filters or {}))
            if not markets:
                break

            with conn:
                for market in markets:
                    market_pk = _upsert_market(conn, market, now_ts)
                    short_cycle = _is_short_cycle(market.end_ts, now_ts)
                    for outcome_name, token_id in market.outcomes:
                        if not token_id:
                            continue
                        _upsert_token(conn, market_pk, outcome_name, token_id, short_cycle, now_ts)

            page += 1
            total_items += len(markets)
            page_elapsed = time.time() - page_start
            window.add(page_elapsed)
            avg = window.average() or 0.0
            elapsed = format_duration(time.time() - start_time)
            if max_pages is not None:
                remaining_pages = max_pages - page
                eta_seconds = max(0.0, remaining_pages * avg)
                eta = format_duration(eta_seconds)
            else:
                eta = "unknown"
            print(
                "[sync-markets] page={page} page_items={items} total_items={total} avg={avg:.2f}s/page elapsed={elapsed} eta={eta}".format(
                    page=page,
                    items=len(markets),
                    total=total_items,
                    avg=avg,
                    elapsed=elapsed,
                    eta=eta,
                )
            )
            if max_pages is not None and page >= max_pages:
                break
            if len(markets) < limit:
                break
            offset += limit
    finally:
        conn.close()
