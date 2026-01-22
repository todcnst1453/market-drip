"""SQLite helpers for market-drip."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Union

from .schema import SCHEMA_SQL

PathLike = Union[str, Path]


def connect(db_path: PathLike) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(db_path: PathLike) -> None:
    conn = connect(db_path)
    try:
        with conn:
            conn.executescript(SCHEMA_SQL)
    finally:
        conn.close()