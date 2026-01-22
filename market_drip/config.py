"""Configuration stubs for market-drip."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    """Placeholder config container."""

    data_dir: str = "."