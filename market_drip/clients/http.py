"""HTTP helpers for market-drip clients."""

from __future__ import annotations

from dataclasses import dataclass
import random
import time
from typing import Any, Optional

import httpx


@dataclass
class HttpError(Exception):
    status_code: int
    url: str
    message: str
    retriable: bool
    retry_after_seconds: Optional[int] = None
    response_text_snippet: Optional[str] = None

    def __str__(self) -> str:
        return f"{self.status_code} {self.message} ({self.url})"


def _is_retriable_status(status_code: int) -> bool:
    if status_code == 429:
        return True
    if status_code == 408:
        return True
    return 500 <= status_code <= 599


def _parse_retry_after_seconds(headers: httpx.Headers) -> Optional[int]:
    value = headers.get("Retry-After")
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _snippet(text: str, limit: int = 200) -> str:
    return text[:limit]


class HttpClient:
    def __init__(self, timeout_seconds: float = 10.0, client: httpx.Client | None = None) -> None:
        if client is None:
            timeout = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)
            client = httpx.Client(timeout=timeout)
        self._client = client
        self._rand = random.Random(0)

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        max_attempts = 5
        last_error: HttpError | None = None

        response = None
        for attempt in range(1, max_attempts + 1):
            try:
                response = self._client.get(url, params=params)
                break
            except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.RemoteProtocolError, httpx.NetworkError) as exc:
                last_error = HttpError(
                    status_code=0,
                    url=url,
                    message="request error",
                    retriable=True,
                )
                if attempt >= max_attempts:
                    raise last_error from exc
                base = min(15.0, 0.5 * (2 ** (attempt - 1)))
                jitter = 1.0 + (self._rand.random() * 0.2 - 0.1)
                time.sleep(base * jitter)
                continue

        if response is None:
            raise last_error if last_error is not None else HttpError(
                status_code=0,
                url=url,
                message="request error",
                retriable=True,
            )

        if response.status_code < 200 or response.status_code >= 300:
            retry_after = None
            if response.status_code == 429:
                retry_after = _parse_retry_after_seconds(response.headers)
            text = response.text or ""
            raise HttpError(
                status_code=response.status_code,
                url=str(response.url),
                message="http error",
                retriable=_is_retriable_status(response.status_code),
                retry_after_seconds=retry_after,
                response_text_snippet=_snippet(text) if text else None,
            )

        try:
            return response.json()
        except ValueError as exc:
            text = response.text or ""
            raise HttpError(
                status_code=response.status_code,
                url=str(response.url),
                message="invalid json",
                retriable=False,
                response_text_snippet=_snippet(text) if text else None,
            ) from exc
