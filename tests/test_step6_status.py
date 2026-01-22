import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from market_drip.db.db import connect, init_db
from market_drip.status import get_status
from market_drip.worker.run_worker import run_worker

FIXTURES = Path(__file__).parent / "fixtures"


def _load_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="ascii"))


def _insert_market(conn: sqlite3.Connection, gamma_market_id: str) -> int:
    conn.execute(
        "INSERT INTO markets (gamma_market_id) VALUES (?)",
        (gamma_market_id,),
    )
    row = conn.execute(
        "SELECT market_pk FROM markets WHERE gamma_market_id=?",
        (gamma_market_id,),
    ).fetchone()
    return int(row[0])


def _insert_token(conn: sqlite3.Connection, market_pk: int, clob_token_id: str) -> int:
    conn.execute(
        "INSERT INTO tokens (clob_token_id, market_pk) VALUES (?, ?)",
        (clob_token_id, market_pk),
    )
    row = conn.execute(
        "SELECT token_pk FROM tokens WHERE clob_token_id=?",
        (clob_token_id,),
    ).fetchone()
    return int(row[0])


def test_get_status_empty_db(tmp_path) -> None:
    db_path = tmp_path / "status.sqlite"
    init_db(db_path)

    status = get_status(str(db_path))

    assert status["counts"] == {"markets": 0, "tokens": 0, "prices": 0}
    assert status["tasks"] == {
        "pending": 0,
        "running": 0,
        "deferred": 0,
        "done": 0,
        "error": 0,
    }
    assert status["heartbeat_ts"] is None
    assert status["db_size_bytes"] > 0


def test_status_reflects_seeded_data(tmp_path) -> None:
    db_path = tmp_path / "status-seeded.sqlite"
    init_db(db_path)

    conn = connect(db_path)
    try:
        m1 = _insert_market(conn, "m-1")
        m2 = _insert_market(conn, "m-2")
        t1 = _insert_token(conn, m1, "t-1")
        t2 = _insert_token(conn, m1, "t-2")
        t3 = _insert_token(conn, m2, "t-3")
        conn.execute(
            "INSERT INTO prices (token_pk, ts, resolution, price_bp) VALUES (?, ?, ?, ?)",
            (t1, 1, 15, 1000),
        )
        conn.execute(
            "INSERT INTO prices (token_pk, ts, resolution, price_bp) VALUES (?, ?, ?, ?)",
            (t2, 2, 15, 2000),
        )
        conn.execute(
            "INSERT INTO prices (token_pk, ts, resolution, price_bp) VALUES (?, ?, ?, ?)",
            (t3, 3, 15, 3000),
        )
        conn.execute(
            "INSERT INTO prices (token_pk, ts, resolution, price_bp) VALUES (?, ?, ?, ?)",
            (t3, 4, 15, 4000),
        )
        conn.execute(
            """
            INSERT INTO fetch_tasks (token_pk, resolution, start_ts, end_ts, status, updated_at, last_error)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (t1, 15, 0, 10, "pending", 1, None),
        )
        conn.execute(
            """
            INSERT INTO fetch_tasks (token_pk, resolution, start_ts, end_ts, status, updated_at, last_error)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (t2, 15, 0, 10, "deferred", 1, "rate limit"),
        )
        conn.execute(
            """
            INSERT INTO fetch_tasks (token_pk, resolution, start_ts, end_ts, status, updated_at, last_error)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (t3, 15, 0, 10, "error", 1, "rate limit"),
        )
        conn.execute(
            """
            INSERT INTO fetch_tasks (token_pk, resolution, start_ts, end_ts, status, updated_at, last_error)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (t3, 15, 10, 20, "done", 1, None),
        )
        conn.execute(
            "INSERT INTO run_state (key, value) VALUES (?, ?)",
            ("heartbeat_ts", "1700000000"),
        )
        conn.commit()
    finally:
        conn.close()

    status = get_status(str(db_path))
    assert status["counts"] == {"markets": 2, "tokens": 3, "prices": 4}
    assert status["tasks"] == {
        "pending": 1,
        "running": 0,
        "deferred": 1,
        "done": 1,
        "error": 1,
    }
    assert status["heartbeat_ts"] == 1700000000
    assert status["recent_errors"][0] == {"message": "rate limit", "count": 2}


def test_status_cli_output_contains_key_numbers(tmp_path) -> None:
    db_path = tmp_path / "status-cli.sqlite"
    init_db(db_path)

    conn = connect(db_path)
    try:
        m1 = _insert_market(conn, "m-1")
        _insert_token(conn, m1, "t-1")
        conn.commit()
    finally:
        conn.close()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "market_drip",
            "status",
            "--db",
            str(db_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "markets=1" in result.stdout
    assert "tokens=1" in result.stdout


def test_worker_updates_heartbeat(tmp_path, httpx_mock) -> None:
    db_path = tmp_path / "status-heartbeat.sqlite"
    init_db(db_path)

    now_ts = 1_700_000_000
    conn = connect(db_path)
    try:
        market_pk = _insert_market(conn, "m-1")
        token_pk = _insert_token(conn, market_pk, "T1")
        conn.execute(
            """
            INSERT INTO fetch_tasks (
                token_pk, resolution, start_ts, end_ts, status, attempts, next_run_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (token_pk, 15, 0, 60, "pending", 0, 0, now_ts),
        )
        conn.commit()
    finally:
        conn.close()

    data = _load_json("clob_prices_history.json")
    base_url = "https://clob.polymarket.com"
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/prices-history?market=T1&startTs=0&endTs=60",
        json=data,
        status_code=200,
    )

    run_worker(str(db_path), now_ts=now_ts, max_tasks=1, no_sleep=True, no_jitter=True)

    status = get_status(str(db_path))
    assert status["heartbeat_ts"] == now_ts