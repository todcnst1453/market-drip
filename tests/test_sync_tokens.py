import sqlite3

import pytest

from market_drip.clients.gamma import GammaHttpError, GammaClient
from market_drip.db.db import connect, init_db
from market_drip.sync_tokens import _extract_outcome_pairs, _select_markets, sync_tokens


def _insert_market(
    conn: sqlite3.Connection,
    gamma_market_id: str,
    status: str,
    end_ts: int | None,
    updated_ts: int,
) -> int:
    conn.execute(
        """
        INSERT INTO markets (gamma_market_id, status, end_ts, updated_ts)
        VALUES (?, ?, ?, ?)
        """,
        (gamma_market_id, status, end_ts, updated_ts),
    )
    row = conn.execute(
        "SELECT market_pk FROM markets WHERE gamma_market_id=?",
        (gamma_market_id,),
    ).fetchone()
    return int(row[0])


def _insert_token(conn: sqlite3.Connection, market_pk: int, token_id: str, outcome: str = "Yes") -> None:
    conn.execute(
        """
        INSERT INTO tokens (clob_token_id, market_pk, outcome_name, is_short_cycle)
        VALUES (?, ?, ?, ?)
        """,
        (token_id, market_pk, outcome, 0),
    )


def test_extract_outcome_pairs_dicts_clob_token_id() -> None:
    data = {"outcomes": [{"name": "Yes", "clobTokenId": "t-yes"}]}
    pairs = _extract_outcome_pairs(data)
    assert pairs == [("Yes", "t-yes")]


def test_extract_outcome_pairs_dicts_token_id_variants() -> None:
    data = {"outcomes": [{"outcome": "No", "token_id": "t-no"}, {"name": "Maybe", "id": "t-maybe"}]}
    pairs = _extract_outcome_pairs(data)
    assert ("No", "t-no") in pairs
    assert ("Maybe", "t-maybe") in pairs


def test_extract_outcome_pairs_strings_with_token_ids() -> None:
    data = {"outcomes": ["Yes", "No"], "tokenIds": ["t-yes", "t-no"]}
    pairs = _extract_outcome_pairs(data)
    assert pairs == [("Yes", "t-yes"), ("No", "t-no")]


def test_extract_outcome_pairs_missing_outcomes() -> None:
    assert _extract_outcome_pairs({}) == []
    assert _extract_outcome_pairs({"outcomes": []}) == []


def test_extract_outcome_pairs_malformed_structures() -> None:
    assert _extract_outcome_pairs({"outcomes": "Yes"}) == []
    assert _extract_outcome_pairs({"outcomes": [1, 2, 3]}) == []


def test_select_markets_excludes_tokenized_and_filters_status_and_window(tmp_path) -> None:
    db_path = tmp_path / "select.sqlite"
    init_db(db_path)

    now_ts = 1_700_000_000
    recent_end_ts = now_ts + 3600
    old_end_ts = now_ts - 200 * 24 * 60 * 60

    conn = connect(db_path)
    try:
        market_a = _insert_market(conn, "m-active-has-token", "active", recent_end_ts, now_ts)
        market_b = _insert_market(conn, "m-open-no-token", "open", recent_end_ts, now_ts)
        _insert_market(conn, "m-closed", "closed", recent_end_ts, now_ts)
        _insert_market(conn, "m-active-old", "active", old_end_ts, now_ts)
        _insert_token(conn, market_a, "t-1")
        conn.commit()
    finally:
        conn.close()

    conn = connect(db_path)
    try:
        rows = _select_markets(conn, now_ts, limit=100, offset=0, rolling_days=90, statuses=["active", "open"])
    finally:
        conn.close()

    ids = [row[1] for row in rows]
    assert ids == ["m-open-no-token"]


def test_sync_tokens_end_to_end_idempotent(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "sync.sqlite"
    init_db(db_path)

    now_ts = 1_700_000_000

    conn = connect(db_path)
    try:
        _insert_market(conn, "m-1", "active", None, now_ts)
        _insert_market(conn, "m-2", "closed", None, now_ts)
        conn.commit()
    finally:
        conn.close()

    def fake_detail(self, market_id: str):
        if market_id == "m-1":
            return {"outcomes": [{"name": "Yes", "clobTokenId": "t-yes"}]}
        return {"outcomes": [{"name": "No", "clobTokenId": "t-no"}]}

    monkeypatch.setattr(GammaClient, "get_market_detail", fake_detail)
    monkeypatch.setattr("market_drip.sync_tokens.time.time", lambda: float(now_ts))

    sync_tokens(str(db_path), limit=10, offset=0, rolling_days=90, concurrency=1, max_attempts=3)

    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT clob_token_id, outcome_name FROM tokens ORDER BY clob_token_id"
        ).fetchall()
    finally:
        conn.close()

    assert rows == [("t-yes", "Yes")]

    sync_tokens(str(db_path), limit=10, offset=0, rolling_days=90, concurrency=1, max_attempts=3)

    conn = connect(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM tokens").fetchone()[0]
    finally:
        conn.close()

    assert count == 1


def test_sync_tokens_retries_then_succeeds(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "retry.sqlite"
    init_db(db_path)

    now_ts = 1_700_000_000
    conn = connect(db_path)
    try:
        _insert_market(conn, "m-retry", "active", None, now_ts)
        conn.commit()
    finally:
        conn.close()

    calls = {"count": 0}

    def flaky_detail(self, market_id: str):
        calls["count"] += 1
        if calls["count"] <= 2:
            raise GammaHttpError(status_code=429, message="rate limit", url="x", retry_after_seconds=0)
        return {"outcomes": [{"name": "Yes", "clobTokenId": "t-yes"}]}

    monkeypatch.setattr(GammaClient, "get_market_detail", flaky_detail)
    monkeypatch.setattr("market_drip.sync_tokens.time.sleep", lambda _: None)
    monkeypatch.setattr("market_drip.sync_tokens.time.time", lambda: float(now_ts))

    stats = sync_tokens(str(db_path), limit=10, offset=0, rolling_days=90, concurrency=1, max_attempts=5)

    assert calls["count"] == 3
    assert stats["tokens_inserted"] == 1
    assert stats["failed_http"] == 0


def test_sync_tokens_non_retryable_http(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "no-retry.sqlite"
    init_db(db_path)

    now_ts = 1_700_000_000
    conn = connect(db_path)
    try:
        _insert_market(conn, "m-404", "active", None, now_ts)
        conn.commit()
    finally:
        conn.close()

    calls = {"count": 0}

    def not_found(self, market_id: str):
        calls["count"] += 1
        raise GammaHttpError(status_code=404, message="not found", url="x", retry_after_seconds=None)

    monkeypatch.setattr(GammaClient, "get_market_detail", not_found)
    monkeypatch.setattr("market_drip.sync_tokens.time.time", lambda: float(now_ts))

    stats = sync_tokens(str(db_path), limit=10, offset=0, rolling_days=90, concurrency=1, max_attempts=5)

    assert calls["count"] == 1
    assert stats["failed_http"] == 1
    assert stats["tokens_inserted"] == 0
