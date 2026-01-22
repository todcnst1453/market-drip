"""Status reporting for market-drip."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .db.db import connect


def _count_table(conn, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def get_status(db_path: str) -> dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        return {
            "db_path": str(path),
            "db_size_bytes": 0,
            "counts": {"markets": 0, "tokens": 0, "prices": 0},
            "tasks": {
                "pending": 0,
                "running": 0,
                "deferred": 0,
                "done": 0,
                "error": 0,
            },
            "heartbeat_ts": None,
            "recent_errors": [],
        }

    conn = connect(path)
    try:
        counts = {
            "markets": _count_table(conn, "markets"),
            "tokens": _count_table(conn, "tokens"),
            "prices": _count_table(conn, "prices"),
        }

        tasks = {"pending": 0, "running": 0, "deferred": 0, "done": 0, "error": 0}
        for status, count in conn.execute(
            "SELECT status, COUNT(*) FROM fetch_tasks GROUP BY status"
        ).fetchall():
            if status in tasks:
                tasks[status] = int(count)

        heartbeat_row = conn.execute(
            "SELECT value FROM run_state WHERE key='heartbeat_ts'"
        ).fetchone()
        heartbeat_ts = int(heartbeat_row[0]) if heartbeat_row is not None else None

        errors = conn.execute(
            """
            SELECT last_error, COUNT(*) AS c
            FROM fetch_tasks
            WHERE status IN ('deferred','error')
              AND last_error IS NOT NULL AND last_error <> ''
            GROUP BY last_error
            ORDER BY c DESC, last_error ASC
            LIMIT 5
            """,
        ).fetchall()
        recent_errors = [{"message": row[0], "count": int(row[1])} for row in errors]
    finally:
        conn.close()

    return {
        "db_path": str(path),
        "db_size_bytes": path.stat().st_size,
        "counts": counts,
        "tasks": tasks,
        "heartbeat_ts": heartbeat_ts,
        "recent_errors": recent_errors,
    }