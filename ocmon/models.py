"""Data model shared by every usage source."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class WindowUsage:
    """One rate-limit window (5h / 1w / 1m)."""

    key: str            # stable id: "5h" | "1w" | "1m"
    label: str          # text drawn under the dial
    period: float       # window length in seconds
    used: float         # money (or units) consumed inside the window
    limit: float        # money (or units) allowed inside the window
    reset_in: float     # seconds until the window resets
    has_data: bool = True

    @property
    def used_fraction(self) -> float:
        if self.limit <= 0:
            return 0.0
        return clamp(self.used / self.limit)

    @property
    def remaining_fraction(self) -> float:
        return clamp(1.0 - self.used_fraction)

    @property
    def reset_fraction(self) -> float:
        if self.period <= 0:
            return 0.0
        return clamp(self.reset_in / self.period)

    @property
    def used_percent(self) -> int:
        return int(round(self.used_fraction * 100))

    @property
    def remaining_percent(self) -> int:
        return max(0, 100 - self.used_percent)


@dataclass
class UsageSnapshot:
    """Everything the widget needs for one repaint."""

    windows: list[WindowUsage] = field(default_factory=list)
    source: str = "unknown"
    error: str | None = None
    fetched_at: float = field(default_factory=time.time)
    raw: Any = None

    @property
    def ok(self) -> bool:
        return self.error is None and any(w.has_data for w in self.windows)


def empty_window(key: str, label: str, period: float) -> WindowUsage:
    return WindowUsage(
        key=key, label=label, period=period,
        used=0.0, limit=0.0, reset_in=period, has_data=False,
    )
