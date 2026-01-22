import json
from pathlib import Path

import httpx
import pytest

from market_drip.clients.clob import ClobClient
from market_drip.clients.gamma import GammaClient
from market_drip.clients.http import HttpClient, HttpError

FIXTURES = Path(__file__).parent / "fixtures"


def _load_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="ascii"))


def test_gamma_list_markets_parses_fixture(httpx_mock) -> None:
    data = _load_json("gamma_markets_page.json")
    base_url = "https://gamma-api.polymarket.com"
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/markets?limit=100&offset=0",
        json=data,
        status_code=200,
    )

    client = GammaClient(base_url=base_url)
    markets = client.list_markets(limit=100, offset=0)

    assert len(markets) == 2
    assert markets[0].gamma_market_id == "m-1"
    assert markets[0].question == "Will it rain tomorrow?"
    assert ("Yes", "t-yes") in markets[0].outcomes
    assert ("No", "t-no") in markets[0].outcomes


def test_gamma_parsing_tolerates_missing_optional_fields(httpx_mock) -> None:
    data = {
        "markets": [
            {
                "id": "m-3",
                "question": "Minimal market",
                "outcomes": [{"name": "Yes", "clobTokenId": "t-1"}],
            }
        ]
    }
    base_url = "https://gamma-api.polymarket.com"
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/markets?limit=1&offset=0",
        json=data,
        status_code=200,
    )

    client = GammaClient(base_url=base_url)
    markets = client.list_markets(limit=1, offset=0)

    assert len(markets) == 1
    assert markets[0].slug is None
    assert markets[0].end_ts is None


def test_clob_prices_history_parses_fixture(httpx_mock) -> None:
    data = _load_json("clob_prices_history.json")
    base_url = "https://clob.polymarket.com"
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/prices-history?market=t-1&startTs=0&endTs=3600",
        json=data,
        status_code=200,
    )

    client = ClobClient(base_url=base_url)
    points = client.prices_history(token_id="t-1", start_ts=0, end_ts=3600)

    assert len(points) == 5
    for point in points:
        assert isinstance(point.ts, int)
        assert isinstance(point.price, float)
        assert 0.0 <= point.price <= 1.0


def test_clob_prices_history_empty_ok(httpx_mock) -> None:
    data = _load_json("clob_prices_history_empty.json")
    base_url = "https://clob.polymarket.com"
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/prices-history?market=t-2&startTs=0&endTs=60",
        json=data,
        status_code=200,
    )

    client = ClobClient(base_url=base_url)
    points = client.prices_history(token_id="t-2", start_ts=0, end_ts=60)

    assert points == []


def test_http_429_raises_with_retry_after(httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://example.com/ratelimited",
        status_code=429,
        headers={"Retry-After": "7"},
        text="rate limit",
    )

    client = HttpClient()
    with pytest.raises(HttpError) as exc_info:
        client.get_json("https://example.com/ratelimited")

    err = exc_info.value
    assert err.status_code == 429
    assert err.retry_after_seconds == 7
    assert err.retriable is True


def test_http_5xx_raises_retriable(httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://example.com/unavailable",
        status_code=503,
        text="service unavailable",
    )

    client = HttpClient()
    with pytest.raises(HttpError) as exc_info:
        client.get_json("https://example.com/unavailable")

    err = exc_info.value
    assert err.status_code == 503
    assert err.retriable is True


def test_http_retries_on_read_timeout_then_succeeds(httpx_mock, monkeypatch) -> None:
    base_url = "https://example.com/timeout"
    httpx_mock.add_exception(method="GET", url=base_url, exception=httpx.ReadTimeout("timeout"))
    httpx_mock.add_response(method="GET", url=base_url, json={"ok": True}, status_code=200)

    monkeypatch.setattr("market_drip.clients.http.time.sleep", lambda _: None)

    client = HttpClient()
    result = client.get_json(base_url)

    assert result == {"ok": True}
    assert len(httpx_mock.get_requests()) == 2


def test_clob_requires_window_or_interval(httpx_mock) -> None:
    base_url = "https://clob.polymarket.com"
    client = ClobClient(base_url=base_url)
    with pytest.raises(ValueError):
        client.prices_history(token_id="t-1")

    with pytest.raises(ValueError):
        client.prices_history(token_id="t-1", start_ts=0)

    with pytest.raises(ValueError):
        client.prices_history(token_id="t-1", end_ts=1)

    with pytest.raises(ValueError):
        client.prices_history(token_id="t-1", start_ts=0, end_ts=1, interval="1m")

    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/prices-history?market=t-1&interval=1m",
        json={"prices": []},
        status_code=200,
    )
    result = client.prices_history(token_id="t-1", interval="1m")
    assert isinstance(result, list)
