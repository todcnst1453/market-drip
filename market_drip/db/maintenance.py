"""Database maintenance helpers for market-drip."""

from __future__ import annotations

from typing import Any

from .db import connect


def wal_checkpoint(db_path: str) -> dict[str, Any]:
    conn = connect(db_path)
    try:
        row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE);").fetchone()
        mode = "TRUNCATE"
        if row is None:
            conn.execute("PRAGMA wal_checkpoint(FULL);")
            mode = "FULL"
            row = conn.execute("PRAGMA wal_checkpoint;").fetchone()
        return {"mode": mode, "result": row}
    finally:
        conn.close()


def vacuum(db_path: str) -> None:
    conn = connect(db_path)
    try:
        conn.execute("VACUUM;")
    finally:
        conn.close()
