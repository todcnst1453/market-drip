import json
import sqlite3
from pathlib import Path

import pytest

from market_drip.db.db import connect, init_db
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


def _insert_task(conn: sqlite3.Connection, token_pk: int, now_ts: int) -> int:
    conn.execute(
        """
        INSERT INTO fetch_tasks (
            token_pk, resolution, start_ts, end_ts, status, attempts, next_run_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (token_pk, 15, 0, 60, "pending", 0, 0, now_ts),
    )
    row = conn.execute("SELECT task_pk FROM fetch_tasks WHERE token_pk=?", (token_pk,)).fetchone()
    return int(row[0])


def test_worker_processes_one_task_to_done_and_inserts_prices(tmp_path, httpx_mock) -> None:
    db_path = tmp_path / "worker.sqlite"
    init_db(db_path)

    now_ts = 1_700_000_000
    conn = connect(db_path)
    try:
        market_pk = _insert_market(conn, "m-1")
        token_pk = _insert_token(conn, market_pk, "T1")
        _insert_task(conn, token_pk, now_ts)
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

    stats = run_worker(str(db_path), now_ts=now_ts, max_tasks=1, no_sleep=True, no_jitter=True)
    assert stats["tasks_done"] == 1

    conn = connect(db_path)
    try:
        status = conn.execute(
            "SELECT status FROM fetch_tasks WHERE token_pk=?",
            (token_pk,),
        ).fetchone()[0]
        assert status == "done"

        rows = conn.execute(
            "SELECT ts, price_bp FROM prices WHERE token_pk=? ORDER BY ts",
            (token_pk,),
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == len(data["prices"])
    first_price = data["prices"][0]["price"]
    assert rows[0][1] == int(round(first_price * 1_000_000))


def test_worker_idempotent_prices_on_rerun(tmp_path, httpx_mock) -> None:
    db_path = tmp_path / "worker-idem.sqlite"
    init_db(db_path)

    now_ts = 1_700_000_000
    conn = connect(db_path)
    try:
        market_pk = _insert_market(conn, "m-1")
        token_pk = _insert_token(conn, market_pk, "T1")
        task_pk = _insert_task(conn, token_pk, now_ts)
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

    conn = connect(db_path)
    try:
        count_first = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
        conn.execute(
            "UPDATE fetch_tasks SET status='pending' WHERE task_pk=?",
            (task_pk,),
        )
        conn.commit()
    finally:
        conn.close()

    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/prices-history?market=T1&startTs=0&endTs=60",
        json=data,
        status_code=200,
    )
    run_worker(str(db_path), now_ts=now_ts, max_tasks=1, no_sleep=True, no_jitter=True)

    conn = connect(db_path)
    try:
        count_second = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    finally:
        conn.close()

    assert count_second == count_first


def test_worker_handles_429_retry_after(tmp_path, httpx_mock) -> None:
    db_path = tmp_path / "worker-429.sqlite"
    init_db(db_path)

    now_ts = 1_700_000_000
    conn = connect(db_path)
    try:
        market_pk = _insert_market(conn, "m-1")
        token_pk = _insert_token(conn, market_pk, "T1")
        _insert_task(conn, token_pk, now_ts)
        conn.commit()
    finally:
        conn.close()

    base_url = "https://clob.polymarket.com"
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/prices-history?market=T1&startTs=0&endTs=60",
        status_code=429,
        headers={"Retry-After": "7"},
        text="rate limit",
    )

    stats = run_worker(str(db_path), now_ts=now_ts, max_tasks=1, no_sleep=True, no_jitter=True)
    assert stats["tasks_deferred"] == 1

    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT status, attempts, next_run_at FROM fetch_tasks WHERE token_pk=?",
            (token_pk,),
        ).fetchone()
    finally:
        conn.close()

    assert row == ("deferred", 1, now_ts + 7)


def test_worker_handles_503_deferred_with_backoff(tmp_path, httpx_mock) -> None:
    db_path = tmp_path / "worker-503.sqlite"
    init_db(db_path)

    now_ts = 1_700_000_000
    conn = connect(db_path)
    try:
        market_pk = _insert_market(conn, "m-1")
        token_pk = _insert_token(conn, market_pk, "T1")
        _insert_task(conn, token_pk, now_ts)
        conn.commit()
    finally:
        conn.close()

    base_url = "https://clob.polymarket.com"
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/prices-history?market=T1&startTs=0&endTs=60",
        status_code=503,
        text="service unavailable",
    )

    run_worker(str(db_path), now_ts=now_ts, max_tasks=1, no_sleep=True, no_jitter=True)

    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT status, attempts, next_run_at FROM fetch_tasks WHERE token_pk=?",
            (token_pk,),
        ).fetchone()
    finally:
        conn.close()

    assert row == ("deferred", 1, now_ts + 10)


def test_worker_handles_400_error(tmp_path, httpx_mock) -> None:
    db_path = tmp_path / "worker-400.sqlite"
    init_db(db_path)

    now_ts = 1_700_000_000
    conn = connect(db_path)
    try:
        market_pk = _insert_market(conn, "m-1")
        token_pk = _insert_token(conn, market_pk, "T1")
        _insert_task(conn, token_pk, now_ts)
        conn.commit()
    finally:
        conn.close()

    base_url = "https://clob.polymarket.com"
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/prices-history?market=T1&startTs=0&endTs=60",
        status_code=400,
        text="bad request",
    )

    run_worker(str(db_path), now_ts=now_ts, max_tasks=1, no_sleep=True, no_jitter=True)

    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT status, attempts FROM fetch_tasks WHERE token_pk=?",
            (token_pk,),
        ).fetchone()
    finally:
        conn.close()

    assert row == ("error", 1)


def test_worker_stale_running_task_is_recovered(tmp_path, httpx_mock) -> None:
    db_path = tmp_path / "worker-stale.sqlite"
    init_db(db_path)

    now_ts = 1_700_000_000
    conn = connect(db_path)
    try:
        market_pk = _insert_market(conn, "m-1")
        token_pk = _insert_token(conn, market_pk, "T1")
        task_pk = _insert_task(conn, token_pk, now_ts)
        conn.execute(
            "UPDATE fetch_tasks SET status='running', updated_at=? WHERE task_pk=?",
            (now_ts - 7200, task_pk),
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

    conn = connect(db_path)
    try:
        status = conn.execute(
            "SELECT status FROM fetch_tasks WHERE token_pk=?",
            (token_pk,),
        ).fetchone()[0]
    finally:
        conn.close()

    assert status == "done"