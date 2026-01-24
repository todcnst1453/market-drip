"""Gamma public API client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .http import HttpClient, HttpError

DEFAULT_GAMMA_BASE_URL = "https://gamma-api.polymarket.com"


@dataclass(frozen=True)
class GammaMarket:
    gamma_market_id: str
    slug: str | None
    question: str
    status: str
    end_ts: int | None
    outcomes: list[tuple[str, str]]


@dataclass
class GammaHttpError(Exception):
    status_code: int
    message: str
    url: str
    retry_after_seconds: int | None = None

    def __str__(self) -> str:
        return f"{self.status_code} {self.message} ({self.url})"


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_status(item: dict[str, Any]) -> str:
    status = item.get("status") or item.get("state")
    if status:
        return str(status)
    if item.get("resolved") is True:
        return "resolved"
    if item.get("closed") is True:
        return "closed"
    if item.get("active") is True:
        return "active"
    return "unknown"


def _extract_outcomes(raw_outcomes: Iterable[Any]) -> list[tuple[str, str]]:
    outcomes: list[tuple[str, str]] = []
    for entry in raw_outcomes:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("outcome") or ""
        token_id = (
            entry.get("clobTokenId")
            or entry.get("clob_token_id")
            or entry.get("token_id")
            or entry.get("tokenId")
        )
        if token_id is None:
            continue
        outcomes.append((str(name), str(token_id)))
    return outcomes


def _parse_markets(data: Any) -> list[GammaMarket]:
    items: Iterable[Any]
    if isinstance(data, dict):
        if isinstance(data.get("markets"), list):
            items = data["markets"]
        elif isinstance(data.get("results"), list):
            items = data["results"]
        else:
            items = []
    elif isinstance(data, list):
        items = data
    else:
        items = []

    markets: list[GammaMarket] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        market_id = item.get("id") or item.get("marketId") or item.get("market_id") or ""
        question = item.get("question") or item.get("title") or ""
        slug = item.get("slug")
        status = _normalize_status(item)
        end_ts = _parse_int(
            item.get("end_ts")
            or item.get("endTime")
            or item.get("end_time")
            or item.get("endTimestamp")
        )
        outcomes = _extract_outcomes(item.get("outcomes", []))

        markets.append(
            GammaMarket(
                gamma_market_id=str(market_id),
                slug=str(slug) if slug is not None else None,
                question=str(question),
                status=str(status),
                end_ts=end_ts,
                outcomes=outcomes,
            )
        )
    return markets


class GammaClient:
    def __init__(self, base_url: str = DEFAULT_GAMMA_BASE_URL, http: HttpClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http or HttpClient()

    @property
    def base_url(self) -> str:
        return self._base_url

    def list_markets(self, limit: int = 100, offset: int = 0, **filters: Any) -> list[GammaMarket]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        params.update(filters)
        url = f"{self._base_url}/markets"
        data = self._http.get_json(url, params=params)
        return _parse_markets(data)

    def get_market_detail(self, market_id: str) -> dict[str, Any]:
        url = f"{self._base_url}/markets/{market_id}"
        try:
            data = self._http.get_json(url)
        except HttpError as exc:
            if exc.status_code and (exc.status_code < 200 or exc.status_code >= 300):
                raise GammaHttpError(
                    status_code=exc.status_code,
                    message=exc.message,
                    url=str(exc.url),
                    retry_after_seconds=exc.retry_after_seconds,
                ) from exc
            raise
        if not isinstance(data, dict):
            return {}
        return data
