"""Polymarket CLOB public API client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .http import HttpClient

DEFAULT_CLOB_BASE_URL = "https://clob.polymarket.com"


@dataclass(frozen=True)
class PricePoint:
    ts: int
    price: float


def _parse_points(data: Any) -> list[PricePoint]:
    points_raw: Any
    if isinstance(data, dict):
        points_raw = data.get("prices") or data.get("history") or []
    elif isinstance(data, list):
        points_raw = data
    else:
        points_raw = []

    points: list[PricePoint] = []
    for entry in points_raw:
        if not isinstance(entry, dict):
            continue
        ts_val = entry.get("ts") or entry.get("t") or entry.get("timestamp")
        price_val = entry.get("price") or entry.get("p")
        if ts_val is None or price_val is None:
            continue
        try:
            ts_int = int(ts_val)
            price_float = float(price_val)
        except (TypeError, ValueError):
            continue
        points.append(PricePoint(ts=ts_int, price=price_float))

    return points


class ClobClient:
    def __init__(self, base_url: str = DEFAULT_CLOB_BASE_URL, http: HttpClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http or HttpClient()

    def prices_history(
        self,
        token_id: str,
        start_ts: int | None = None,
        end_ts: int | None = None,
        interval: str | None = None,
        fidelity: int | None = None,
    ) -> list[PricePoint]:
        has_window = start_ts is not None or end_ts is not None
        if interval is None and (start_ts is None or end_ts is None):
            raise ValueError("start_ts and end_ts or interval is required")
        if interval is not None and has_window:
            raise ValueError("use either start/end or interval, not both")
        if start_ts is not None and end_ts is None:
            raise ValueError("end_ts is required when start_ts is provided")
        if end_ts is not None and start_ts is None:
            raise ValueError("start_ts is required when end_ts is provided")

        params: dict[str, Any] = {"market": token_id}
        if interval is not None:
            params["interval"] = interval
        else:
            params["startTs"] = start_ts
            params["endTs"] = end_ts
        if fidelity is not None:
            params["fidelity"] = fidelity

        url = f"{self._base_url}/prices-history"
        data = self._http.get_json(url, params=params)
        return _parse_points(data)