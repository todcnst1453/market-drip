import json
import re
from pathlib import Path

from market_drip.db.db import connect, init_db
from market_drip.sync import sync_markets
from market_drip.tasks.build_tasks import build_tasks
from market_drip.worker.run_worker import run_worker

FIXTURES = Path(__file__).parent / "fixtures"


def _load_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="ascii"))


def test_sync_markets_emits_progress_line(tmp_path, httpx_mock, capsys) -> None:
    db_path = tmp_path / "sync-log.sqlite"
    init_db(db_path)

    base_url = "https://gamma-api.polymarket.com"
    page = _load_json("gamma_markets_page.json")
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/markets?limit=100&offset=0",
        json=page,
        status_code=200,
    )

    sync_markets(str(db_path), now_ts=1700000000, max_pages=1, base_url=base_url)

    out = capsys.readouterr().out
    assert "[sync-markets] page=1" in out
    pattern = r"\[sync-markets\] page=\d+ page_items=\d+ total_items=\d+ avg=\d+\.\d+s/page elapsed=\d\d:\d\d:\d\d eta=(?:\d\d:\d\d:\d\d|unknown)"
    assert re.search(pattern, out)


def test_build_tasks_emits_start_and_done(tmp_path, capsys) -> None:
    db_path = tmp_path / "tasks-log.sqlite"
    init_db(db_path)

    conn = connect(db_path)
    try:
        conn.execute("INSERT INTO markets (gamma_market_id) VALUES (?)", ("m-1",))
        market_pk = conn.execute(
            "SELECT market_pk FROM markets WHERE gamma_market_id=?",
            ("m-1",),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO tokens (clob_token_id, market_pk) VALUES (?, ?)",
            ("t-1", market_pk),
        )
        conn.commit()
    finally:
        conn.close()

    build_tasks(str(db_path), now_ts=1700000000)

    out = capsys.readouterr().out
    assert "[build-tasks] start" in out
    assert "[build-tasks] done elapsed=" in out


def test_worker_emits_start_and_heartbeat(tmp_path, capsys, monkeypatch) -> None:
    db_path = tmp_path / "worker-log.sqlite"
    init_db(db_path)

    monkeypatch.setattr("market_drip.worker.run_worker.time.time", lambda: 0.0)

    run_worker(str(db_path), now_ts=1700000000, max_tasks=0, no_sleep=True, no_jitter=True)

    out = capsys.readouterr().out
    assert "[worker] start" in out
    assert "[worker] heartbeat" in out
