import sqlite3
import subprocess
import sys

from market_drip.db.db import connect, init_db
from market_drip.db.maintenance import wal_checkpoint, vacuum


def _seed_rows(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO markets (gamma_market_id) VALUES (?)", ("m-1",))
    market_pk = conn.execute(
        "SELECT market_pk FROM markets WHERE gamma_market_id=?",
        ("m-1",),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO tokens (clob_token_id, market_pk) VALUES (?, ?)",
        ("t-1", market_pk),
    )
    token_pk = conn.execute(
        "SELECT token_pk FROM tokens WHERE clob_token_id=?",
        ("t-1",),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO prices (token_pk, ts, resolution, price_bp) VALUES (?, ?, ?, ?)",
        (token_pk, 1, 15, 1000),
    )
    conn.execute(
        """
        INSERT INTO fetch_tasks (token_pk, resolution, start_ts, end_ts, status, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (token_pk, 15, 0, 10, "pending", 1),
    )


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        "markets": conn.execute("SELECT COUNT(*) FROM markets").fetchone()[0],
        "tokens": conn.execute("SELECT COUNT(*) FROM tokens").fetchone()[0],
        "prices": conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0],
        "tasks": conn.execute("SELECT COUNT(*) FROM fetch_tasks").fetchone()[0],
    }


def test_db_checkpoint_runs_and_db_still_queryable(tmp_path) -> None:
    db_path = tmp_path / "checkpoint.sqlite"
    init_db(db_path)

    conn = connect(db_path)
    try:
        _seed_rows(conn)
        conn.commit()
        before = _counts(conn)
    finally:
        conn.close()

    result = wal_checkpoint(str(db_path))
    assert result["mode"] in {"TRUNCATE", "FULL"}

    conn = connect(db_path)
    try:
        after = _counts(conn)
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    finally:
        conn.close()

    assert before == after
    assert mode.lower() == "wal"


def test_db_vacuum_runs_and_data_intact(tmp_path) -> None:
    db_path = tmp_path / "vacuum.sqlite"
    init_db(db_path)

    conn = connect(db_path)
    try:
        _seed_rows(conn)
        conn.commit()
        before = _counts(conn)
    finally:
        conn.close()

    vacuum(str(db_path))

    conn = connect(db_path)
    try:
        after = _counts(conn)
    finally:
        conn.close()

    assert before == after


def test_cli_commands_exit_zero(tmp_path) -> None:
    db_path = tmp_path / "cli.sqlite"
    init_db(db_path)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "market_drip",
            "db-checkpoint",
            "--db",
            str(db_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "WAL checkpoint" in result.stdout

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "market_drip",
            "db-vacuum",
            "--db",
            str(db_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "VACUUM" in result.stdout