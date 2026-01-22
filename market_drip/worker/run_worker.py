"""Worker loop for market-drip."""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from typing import Any

from ..clients.clob import ClobClient
from ..clients.http import HttpError
from ..db.db import connect

STALE_RUNNING_SECONDS = 60 * 60
BASE_DELAY_SECONDS = 3.0


@dataclass(frozen=True)
class WorkerStats:
    tasks_processed: int
    tasks_done: int
    tasks_deferred: int
    tasks_error: int
    prices_inserted: int


def _compute_backoff_seconds(attempts: int, no_jitter: bool) -> int:
    base = min(600, 5 * (2 ** min(attempts, 7)))
    if no_jitter:
        return int(base)
    jitter = random.uniform(0.8, 1.2)
    return int(base * jitter)


def _sleep_between_tasks(no_sleep: bool, no_jitter: bool) -> None:
    if no_sleep:
        return
    delay = BASE_DELAY_SECONDS
    if not no_jitter:
        delay = delay * random.uniform(0.7, 1.3)
    time.sleep(delay)


def _recover_stale_running(conn, now_ts: int) -> None:
    conn.execute(
        """
        UPDATE fetch_tasks
        SET status='deferred', next_run_at=?, updated_at=?
        WHERE status='running' AND updated_at <= ?
        """,
        (now_ts, now_ts, now_ts - STALE_RUNNING_SECONDS),
    )


def _set_run_state(conn, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO run_state (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, value),
    )


def _update_heartbeat(conn, now_ts: int, stats: WorkerStats) -> None:
    _set_run_state(conn, "heartbeat_ts", str(now_ts))
    _set_run_state(conn, "last_run_now_ts", str(now_ts))
    stats_payload = {
        "tasks_processed": stats.tasks_processed,
        "tasks_done": stats.tasks_done,
        "tasks_deferred": stats.tasks_deferred,
        "tasks_error": stats.tasks_error,
        "prices_inserted": stats.prices_inserted,
    }
    _set_run_state(conn, "last_worker_stats", json.dumps(stats_payload, separators=(",", ":")))


def _select_next_task(conn, now_ts: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT t.task_pk, t.token_pk, t.resolution, t.start_ts, t.end_ts,
               t.attempts, t.status, t.next_run_at, k.clob_token_id
        FROM fetch_tasks t
        JOIN tokens k ON k.token_pk = t.token_pk
        WHERE t.status IN ('pending', 'deferred')
          AND t.next_run_at <= ?
        ORDER BY t.next_run_at ASC, t.task_pk ASC
        LIMIT 1
        """,
        (now_ts,),
    ).fetchone()
    if row is None:
        return None
    return {
        "task_pk": row[0],
        "token_pk": row[1],
        "resolution": row[2],
        "start_ts": row[3],
        "end_ts": row[4],
        "attempts": row[5],
        "status": row[6],
        "next_run_at": row[7],
        "clob_token_id": row[8],
    }


def _mark_running(conn, task_pk: int, now_ts: int) -> None:
    conn.execute(
        "UPDATE fetch_tasks SET status='running', updated_at=? WHERE task_pk=?",
        (now_ts, task_pk),
    )


def _insert_prices(conn, token_pk: int, resolution: int, points: list[dict[str, Any]]) -> int:
    inserted = 0
    for point in points:
        ts = point["ts"]
        price = point["price"]
        price_bp = int(round(price * 1_000_000))
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO prices (token_pk, ts, resolution, price_bp)
            VALUES (?, ?, ?, ?)
            """,
            (token_pk, ts, resolution, price_bp),
        )
        inserted += cur.rowcount
    return inserted


def _mark_done(conn, task_pk: int, now_ts: int) -> None:
    conn.execute(
        """
        UPDATE fetch_tasks
        SET status='done', updated_at=?, last_error=NULL
        WHERE task_pk=?
        """,
        (now_ts, task_pk),
    )


def _mark_deferred(
    conn,
    task_pk: int,
    now_ts: int,
    attempts: int,
    next_run_at: int,
    last_error: str,
) -> None:
    conn.execute(
        """
        UPDATE fetch_tasks
        SET status='deferred', attempts=?, next_run_at=?, updated_at=?, last_error=?
        WHERE task_pk=?
        """,
        (attempts, next_run_at, now_ts, last_error, task_pk),
    )


def _mark_error(conn, task_pk: int, now_ts: int, attempts: int, last_error: str) -> None:
    conn.execute(
        """
        UPDATE fetch_tasks
        SET status='error', attempts=?, updated_at=?, last_error=?
        WHERE task_pk=?
        """,
        (attempts, now_ts, last_error, task_pk),
    )


def run_worker(
    db_path: str,
    now_ts: int,
    max_tasks: int | None = None,
    no_sleep: bool = False,
    no_jitter: bool = False,
) -> dict[str, int]:
    stats = WorkerStats(0, 0, 0, 0, 0)
    clob = ClobClient()

    conn = connect(db_path)
    try:
        with conn:
            _recover_stale_running(conn, now_ts)
            _update_heartbeat(conn, now_ts, stats)

        while True:
            if max_tasks is not None and stats.tasks_processed >= max_tasks:
                break

            with conn:
                _update_heartbeat(conn, now_ts, stats)
                task = _select_next_task(conn, now_ts)
                if task is None:
                    break
                _mark_running(conn, task["task_pk"], now_ts)

            stats = WorkerStats(
                stats.tasks_processed + 1,
                stats.tasks_done,
                stats.tasks_deferred,
                stats.tasks_error,
                stats.prices_inserted,
            )

            try:
                points = clob.prices_history(
                    token_id=task["clob_token_id"],
                    start_ts=task["start_ts"],
                    end_ts=task["end_ts"],
                )

                with conn:
                    inserted = _insert_prices(
                        conn,
                        token_pk=task["token_pk"],
                        resolution=task["resolution"],
                        points=[{"ts": p.ts, "price": p.price} for p in points],
                    )
                    _mark_done(conn, task["task_pk"], now_ts)

                stats = WorkerStats(
                    stats.tasks_processed,
                    stats.tasks_done + 1,
                    stats.tasks_deferred,
                    stats.tasks_error,
                    stats.prices_inserted + inserted,
                )
                with conn:
                    _update_heartbeat(conn, now_ts, stats)
            except HttpError as exc:
                attempts = int(task["attempts"]) + 1
                if exc.status_code == 429:
                    if exc.retry_after_seconds is not None:
                        next_run_at = now_ts + exc.retry_after_seconds
                    else:
                        next_run_at = now_ts + _compute_backoff_seconds(attempts, no_jitter)
                    with conn:
                        _mark_deferred(conn, task["task_pk"], now_ts, attempts, next_run_at, str(exc))
                    stats = WorkerStats(
                        stats.tasks_processed,
                        stats.tasks_done,
                        stats.tasks_deferred + 1,
                        stats.tasks_error,
                        stats.prices_inserted,
                    )
                    with conn:
                        _update_heartbeat(conn, now_ts, stats)
                elif exc.retriable:
                    next_run_at = now_ts + _compute_backoff_seconds(attempts, no_jitter)
                    with conn:
                        _mark_deferred(conn, task["task_pk"], now_ts, attempts, next_run_at, str(exc))
                    stats = WorkerStats(
                        stats.tasks_processed,
                        stats.tasks_done,
                        stats.tasks_deferred + 1,
                        stats.tasks_error,
                        stats.prices_inserted,
                    )
                    with conn:
                        _update_heartbeat(conn, now_ts, stats)
                else:
                    with conn:
                        _mark_error(conn, task["task_pk"], now_ts, attempts, str(exc))
                    stats = WorkerStats(
                        stats.tasks_processed,
                        stats.tasks_done,
                        stats.tasks_deferred,
                        stats.tasks_error + 1,
                        stats.prices_inserted,
                    )
                    with conn:
                        _update_heartbeat(conn, now_ts, stats)
            _sleep_between_tasks(no_sleep, no_jitter)
    finally:
        conn.close()

    return {
        "tasks_processed": stats.tasks_processed,
        "tasks_done": stats.tasks_done,
        "tasks_deferred": stats.tasks_deferred,
        "tasks_error": stats.tasks_error,
        "prices_inserted": stats.prices_inserted,
    }
