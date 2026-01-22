"""Progress helpers for market-drip."""

from __future__ import annotations

from collections import deque


class SlidingWindow:
    def __init__(self, size: int) -> None:
        self._values: deque[float] = deque(maxlen=size)

    def add(self, value: float) -> None:
        self._values.append(value)

    def average(self) -> float | None:
        if not self._values:
            return None
        return sum(self._values) / len(self._values)


def format_duration(seconds: float) -> str:
    total = int(seconds)
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"