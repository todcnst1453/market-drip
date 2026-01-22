import json
import sqlite3
from pathlib import Path

from market_drip.db.db import connect, init_db
from market_drip.sync import sync_markets

FIXTURES = Path(__file__).parent / "fixtures"


def _load_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="ascii"))


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_sync_markets_inserts_markets_and_tokens(tmp_path, httpx_mock) -> None:
    db_path = tmp_path / "sync.sqlite"
    init_db(db_path)

    base_url = "https://gamma-api.polymarket.com"
    page = _load_json("gamma_markets_page.json")
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/markets?limit=100&offset=0",
        json=page,
        status_code=200,
    )

    sync_markets(str(db_path), now_ts=1700000000, base_url=base_url)

    conn = connect(db_path)
    try:
        assert _count(conn, "markets") == 2
        assert _count(conn, "tokens") == 4
    finally:
        conn.close()


def test_sync_markets_idempotent(tmp_path, httpx_mock) -> None:
    db_path = tmp_path / "sync-idem.sqlite"
    init_db(db_path)

    base_url = "https://gamma-api.polymarket.com"
    page = _load_json("gamma_markets_page.json")

    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/markets?limit=100&offset=0",
        json=page,
        status_code=200,
    )
    sync_markets(str(db_path), now_ts=1700000000, base_url=base_url)

    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/markets?limit=100&offset=0",
        json=page,
        status_code=200,
    )
    sync_markets(str(db_path), now_ts=1700000000, base_url=base_url)

    conn = connect(db_path)
    try:
        assert _count(conn, "markets") == 2
        assert _count(conn, "tokens") == 4
    finally:
        conn.close()


def test_sync_markets_updates_existing_rows(tmp_path, httpx_mock) -> None:
    db_path = tmp_path / "sync-update.sqlite"
    init_db(db_path)

    base_url = "https://gamma-api.polymarket.com"
    page_a = {
        "markets": [
            {
                "id": "m-1",
                "slug": "a",
                "question": "Question A",
                "status": "active",
                "end_ts": 1700000000,
                "outcomes": [{"name": "Yes", "clobTokenId": "t-1"}],
            }
        ]
    }
    page_b = {
        "markets": [
            {
                "id": "m-1",
                "slug": "a",
                "question": "Question B",
                "status": "closed",
                "end_ts": 1700000000,
                "outcomes": [{"name": "Maybe", "clobTokenId": "t-1"}],
            }
        ]
    }

    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/markets?limit=100&offset=0",
        json=page_a,
        status_code=200,
    )
    sync_markets(str(db_path), now_ts=1700000000, base_url=base_url)

    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/markets?limit=100&offset=0",
        json=page_b,
        status_code=200,
    )
    sync_markets(str(db_path), now_ts=1700000000, base_url=base_url)

    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT question, status FROM markets WHERE gamma_market_id=?",
            ("m-1",),
        ).fetchone()
        assert row == ("Question B", "closed")

        token_row = conn.execute(
            "SELECT outcome_name FROM tokens WHERE clob_token_id=?",
            ("t-1",),
        ).fetchone()
        assert token_row == ("Maybe",)
    finally:
        conn.close()


def test_short_cycle_flagging(tmp_path, httpx_mock) -> None:
    db_path = tmp_path / "short-cycle.sqlite"
    init_db(db_path)

    base_url = "https://gamma-api.polymarket.com"
    now_ts = 1700000000
    near_end = now_ts + 7 * 24 * 60 * 60
    far_end = now_ts + 60 * 24 * 60 * 60
    page = {
        "markets": [
            {
                "id": "m-1",
                "question": "Near",
                "status": "active",
                "end_ts": near_end,
                "outcomes": [{"name": "Yes", "clobTokenId": "t-near"}],
            },
            {
                "id": "m-2",
                "question": "Far",
                "status": "active",
                "end_ts": far_end,
                "outcomes": [{"name": "Yes", "clobTokenId": "t-far"}],
            },
        ]
    }

    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/markets?limit=100&offset=0",
        json=page,
        status_code=200,
    )

    sync_markets(str(db_path), now_ts=now_ts, base_url=base_url)

    conn = connect(db_path)
    try:
        near = conn.execute(
            "SELECT is_short_cycle FROM tokens WHERE clob_token_id=?",
            ("t-near",),
        ).fetchone()[0]
        far = conn.execute(
            "SELECT is_short_cycle FROM tokens WHERE clob_token_id=?",
            ("t-far",),
        ).fetchone()[0]
    finally:
        conn.close()

    assert near == 1
    assert far == 0
