import sqlite3

from market_drip.db.db import connect, init_db
from market_drip.tasks.build_tasks import build_tasks, SECONDS_PER_DAY, SECONDS_PER_HOUR


def _insert_market(conn: sqlite3.Connection, gamma_market_id: str, end_ts: int | None) -> int:
    conn.execute(
        "INSERT INTO markets (gamma_market_id, end_ts) VALUES (?, ?)",
        (gamma_market_id, end_ts),
    )
    row = conn.execute(
        "SELECT market_pk FROM markets WHERE gamma_market_id=?",
        (gamma_market_id,),
    ).fetchone()
    return int(row[0])


def _insert_token(
    conn: sqlite3.Connection,
    market_pk: int,
    clob_token_id: str,
    is_short_cycle: int,
    outcome_name: str = "Yes",
) -> int:
    conn.execute(
        """
        INSERT INTO tokens (clob_token_id, market_pk, outcome_name, is_short_cycle)
        VALUES (?, ?, ?, ?)
        """,
        (clob_token_id, market_pk, outcome_name, is_short_cycle),
    )
    row = conn.execute(
        "SELECT token_pk FROM tokens WHERE clob_token_id=?",
        (clob_token_id,),
    ).fetchone()
    return int(row[0])


def _fetch_tasks(conn: sqlite3.Connection, resolution: int, token_pk: int | None = None):
    if token_pk is None:
        return conn.execute(
            "SELECT start_ts, end_ts FROM fetch_tasks WHERE resolution=? ORDER BY start_ts",
            (resolution,),
        ).fetchall()
    return conn.execute(
        """
        SELECT start_ts, end_ts FROM fetch_tasks
        WHERE resolution=? AND token_pk=? ORDER BY start_ts
        """,
        (resolution, token_pk),
    ).fetchall()


def test_build_tasks_creates_expected_15m_chunks_per_token(tmp_path) -> None:
    db_path = tmp_path / "tasks.sqlite"
    init_db(db_path)

    conn = connect(db_path)
    try:
        market_pk = _insert_market(conn, "m-1", None)
        _insert_token(conn, market_pk, "t-1", 0)
        conn.commit()
    finally:
        conn.close()

    now_ts = 1_700_000_000
    stats = build_tasks(str(db_path), now_ts=now_ts)
    assert stats.inserted_15m == 5

    conn = connect(db_path)
    try:
        rows = _fetch_tasks(conn, resolution=15)
    finally:
        conn.close()

    assert len(rows) == 5
    assert rows[0][0] == now_ts - 30 * SECONDS_PER_DAY
    assert rows[-1][1] == now_ts

    for idx in range(len(rows) - 1):
        assert rows[idx][1] == rows[idx + 1][0]
        assert rows[idx][0] < rows[idx][1]


def test_build_tasks_multiple_tokens(tmp_path) -> None:
    db_path = tmp_path / "tasks-multi.sqlite"
    init_db(db_path)

    conn = connect(db_path)
    try:
        market_pk = _insert_market(conn, "m-1", None)
        _insert_token(conn, market_pk, "t-1", 0)
        _insert_token(conn, market_pk, "t-2", 0)
        _insert_token(conn, market_pk, "t-3", 0)
        conn.commit()
    finally:
        conn.close()

    now_ts = 1_700_000_000
    build_tasks(str(db_path), now_ts=now_ts)

    conn = connect(db_path)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM fetch_tasks WHERE resolution=15"
        ).fetchone()[0]
    finally:
        conn.close()

    assert count == 3 * 5


def test_build_tasks_creates_1m_close_window_for_short_cycle_only(tmp_path) -> None:
    db_path = tmp_path / "tasks-short.sqlite"
    init_db(db_path)

    now_ts = 1_700_000_000
    end_ts_near = now_ts + 2 * SECONDS_PER_DAY

    conn = connect(db_path)
    try:
        market_a = _insert_market(conn, "m-1", end_ts_near)
        market_b = _insert_market(conn, "m-2", end_ts_near)
        market_c = _insert_market(conn, "m-3", None)

        token_a = _insert_token(conn, market_a, "t-1", 1)
        token_b = _insert_token(conn, market_b, "t-2", 0)
        token_c = _insert_token(conn, market_c, "t-3", 1)
        conn.commit()
    finally:
        conn.close()

    build_tasks(str(db_path), now_ts=now_ts)

    conn = connect(db_path)
    try:
        rows_a = _fetch_tasks(conn, resolution=1, token_pk=token_a)
        rows_b = _fetch_tasks(conn, resolution=1, token_pk=token_b)
        rows_c = _fetch_tasks(conn, resolution=1, token_pk=token_c)
    finally:
        conn.close()

    assert len(rows_a) == 4
    assert rows_b == []
    assert rows_c == []

    expected_start = end_ts_near - 6 * SECONDS_PER_HOUR
    expected_end = end_ts_near + 1 * SECONDS_PER_HOUR
    assert rows_a[0][0] == expected_start
    assert rows_a[-1][1] == expected_end

    for idx in range(len(rows_a) - 1):
        assert rows_a[idx][1] == rows_a[idx + 1][0]
        assert rows_a[idx][0] < rows_a[idx][1]


def test_build_tasks_idempotent_no_duplicates(tmp_path) -> None:
    db_path = tmp_path / "tasks-idem.sqlite"
    init_db(db_path)

    conn = connect(db_path)
    try:
        market_pk = _insert_market(conn, "m-1", None)
        _insert_token(conn, market_pk, "t-1", 0)
        conn.commit()
    finally:
        conn.close()

    now_ts = 1_700_000_000
    first = build_tasks(str(db_path), now_ts=now_ts)
    second = build_tasks(str(db_path), now_ts=now_ts)

    conn = connect(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM fetch_tasks").fetchone()[0]
    finally:
        conn.close()

    assert count == first.total_inserted
    assert second.total_inserted == 0


def test_build_tasks_unique_constraint_guard(tmp_path) -> None:
    db_path = tmp_path / "tasks-unique.sqlite"
    init_db(db_path)

    now_ts = 1_700_000_000
    window_start = now_ts - 30 * SECONDS_PER_DAY

    conn = connect(db_path)
    try:
        market_pk = _insert_market(conn, "m-1", None)
        token_pk = _insert_token(conn, market_pk, "t-1", 0)
        conn.execute(
            """
            INSERT INTO fetch_tasks (
                token_pk, resolution, start_ts, end_ts, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (token_pk, 15, window_start, window_start + 7 * SECONDS_PER_DAY, "pending", now_ts),
        )
        conn.commit()
    finally:
        conn.close()

    build_tasks(str(db_path), now_ts=now_ts)

    conn = connect(db_path)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM fetch_tasks WHERE resolution=15"
        ).fetchone()[0]
    finally:
        conn.close()

    assert count == 5
