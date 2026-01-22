import sqlite3

from market_drip.db.db import connect, init_db


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {row[0] for row in rows}


def _seed_market_and_token(conn: sqlite3.Connection) -> int:
    conn.execute(
        "INSERT INTO markets (gamma_market_id) VALUES (?)",
        ("m-1",),
    )
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
    return token_pk


def test_init_db_creates_tables(tmp_path) -> None:
    db_path = tmp_path / "x.sqlite"
    init_db(db_path)

    conn = connect(db_path)
    try:
        tables = _table_names(conn)
    finally:
        conn.close()

    assert {
        "markets",
        "tokens",
        "prices",
        "fetch_tasks",
        "run_state",
    }.issubset(tables)


def test_wal_enabled(tmp_path) -> None:
    db_path = tmp_path / "wal.sqlite"
    init_db(db_path)

    conn = connect(db_path)
    try:
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    finally:
        conn.close()

    assert mode.lower() == "wal"


def test_prices_unique_constraint(tmp_path) -> None:
    db_path = tmp_path / "prices.sqlite"
    init_db(db_path)

    conn = connect(db_path)
    try:
        token_pk = _seed_market_and_token(conn)
        conn.execute(
            "INSERT INTO prices (token_pk, ts, resolution, price_bp) VALUES (?, ?, ?, ?)",
            (token_pk, 100, 60, 12345),
        )
        try:
            conn.execute(
                "INSERT INTO prices (token_pk, ts, resolution, price_bp) VALUES (?, ?, ?, ?)",
                (token_pk, 100, 60, 12345),
            )
        except sqlite3.IntegrityError:
            pass

        count = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    finally:
        conn.close()

    assert count == 1


def test_fetch_tasks_unique_constraint(tmp_path) -> None:
    db_path = tmp_path / "tasks.sqlite"
    init_db(db_path)

    conn = connect(db_path)
    try:
        token_pk = _seed_market_and_token(conn)
        conn.execute(
            """
            INSERT INTO fetch_tasks (
                token_pk, resolution, start_ts, end_ts, status, attempts, next_run_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (token_pk, 60, 0, 3600, "ready", 0, 0, 1),
        )
        try:
            conn.execute(
                """
                INSERT INTO fetch_tasks (
                    token_pk, resolution, start_ts, end_ts, status, attempts, next_run_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (token_pk, 60, 0, 3600, "ready", 0, 0, 1),
            )
        except sqlite3.IntegrityError:
            pass

        count = conn.execute("SELECT COUNT(*) FROM fetch_tasks").fetchone()[0]
    finally:
        conn.close()

    assert count == 1


def test_init_db_idempotent(tmp_path) -> None:
    db_path = tmp_path / "idempotent.sqlite"
    init_db(db_path)
    init_db(db_path)

    conn = connect(db_path)
    try:
        tables = _table_names(conn)
    finally:
        conn.close()

    assert "markets" in tables