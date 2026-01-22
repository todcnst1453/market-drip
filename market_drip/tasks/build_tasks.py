"""Task building for market-drip."""

from __future__ import annotations

from dataclasses import dataclass

import time

from ..db.db import connect
from ..utils.progress import format_duration

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 60 * 60
SECONDS_PER_DAY = 24 * 60 * 60


@dataclass(frozen=True)
class BuildStats:
    inserted_15m: int
    inserted_1m: int

    @property
    def total_inserted(self) -> int:
        return self.inserted_15m + self.inserted_1m


def _iter_chunks(start_ts: int, end_ts: int, chunk_seconds: int) -> list[tuple[int, int]]:
    chunks: list[tuple[int, int]] = []
    cursor = start_ts
    while cursor < end_ts:
        next_end = cursor + chunk_seconds
        if next_end > end_ts:
            next_end = end_ts
        chunks.append((cursor, next_end))
        cursor = next_end
    return chunks


def build_tasks(
    db_path: str,
    now_ts: int,
    rolling_days: int = 30,
    res15_chunk_days: int = 7,
    close_start_hours: int = 6,
    close_end_hours: int = 1,
    res1_chunk_hours: int = 2,
) -> BuildStats:
    start_time = time.time()
    print("[build-tasks] start")

    rolling_seconds = rolling_days * SECONDS_PER_DAY
    res15_chunk_seconds = res15_chunk_days * SECONDS_PER_DAY
    close_start_seconds = close_start_hours * SECONDS_PER_HOUR
    close_end_seconds = close_end_hours * SECONDS_PER_HOUR
    res1_chunk_seconds = res1_chunk_hours * SECONDS_PER_HOUR

    window_end = now_ts
    window_start = now_ts - rolling_seconds
    window_chunks = _iter_chunks(window_start, window_end, res15_chunk_seconds)

    inserted_15m = 0
    inserted_1m = 0
    attempted_15m = 0
    attempted_1m = 0

    conn = connect(db_path)
    try:
        markets_count = conn.execute("SELECT COUNT(*) FROM markets").fetchone()[0]
        tokens_count = conn.execute("SELECT COUNT(*) FROM tokens").fetchone()[0]
        print(f"[build-tasks] scanned markets={markets_count} tokens={tokens_count}")

        rows = conn.execute(
            """
            SELECT tokens.token_pk, tokens.is_short_cycle, markets.end_ts
            FROM tokens
            JOIN markets ON markets.market_pk = tokens.market_pk
            """
        ).fetchall()

        with conn:
            for token_pk, is_short_cycle, end_ts in rows:
                for start_ts, end_ts_chunk in window_chunks:
                    attempted_15m += 1
                    cur = conn.execute(
                        """
                        INSERT OR IGNORE INTO fetch_tasks (
                            token_pk, resolution, start_ts, end_ts, status, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (token_pk, 15, start_ts, end_ts_chunk, "pending", now_ts),
                    )
                    inserted_15m += cur.rowcount

                if int(is_short_cycle) != 1 or end_ts is None:
                    continue

                close_start = int(end_ts) - close_start_seconds
                close_end = int(end_ts) + close_end_seconds
                close_chunks = _iter_chunks(close_start, close_end, res1_chunk_seconds)

                for start_ts, end_ts_chunk in close_chunks:
                    attempted_1m += 1
                    cur = conn.execute(
                        """
                        INSERT OR IGNORE INTO fetch_tasks (
                            token_pk, resolution, start_ts, end_ts, status, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (token_pk, 1, start_ts, end_ts_chunk, "pending", now_ts),
                    )
                    inserted_1m += cur.rowcount
    finally:
        conn.close()

    inserted_total = inserted_15m + inserted_1m
    attempted_total = attempted_15m + attempted_1m
    skipped_existing = max(0, attempted_total - inserted_total)
    print("[build-tasks] inserted={ins} skipped_existing={skip}".format(ins=inserted_total, skip=skipped_existing))
    print("[build-tasks] done elapsed={elapsed}".format(elapsed=format_duration(time.time() - start_time)))

    return BuildStats(inserted_15m=inserted_15m, inserted_1m=inserted_1m)
