"""Usage sources.

Three ways to know how much of the plan has been consumed:

* ``LocalSource`` - aggregates per-message cost from opencode's own SQLite
  database (works for every provider, no subscription required).
* ``ApiSource``   - asks the Zen/Go endpoint ``GET {base}/usage`` with a Go or
  Zen API key.  Response shapes vary, so the parser is deliberately tolerant.
* ``DemoSource``  - animated fake numbers used for UI preview and tests.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from .models import UsageSnapshot, WindowUsage, empty_window
from .paths import find_auth_file, find_database

FIVE_HOURS = 5 * 3600
ONE_WEEK = 7 * 86400
ONE_MONTH = 30 * 86400

#: window key -> (label, period seconds, share of the monthly limit)
WINDOW_SPECS: list[tuple[str, str, float, float]] = [
    ("5h", "5h", FIVE_HOURS, 0.20),
    ("1w", "1w", ONE_WEEK, 0.50),
    ("1m", "1m", ONE_MONTH, 1.00),
]


class UsageSource:
    name = "abstract"

    def fetch(self) -> UsageSnapshot:  # pragma: no cover - interface
        raise NotImplementedError


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _month_start(now: float) -> float:
    dt = datetime.fromtimestamp(now)
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()


def _month_end(now: float) -> float:
    dt = datetime.fromtimestamp(now)
    if dt.month == 12:
        nxt = dt.replace(year=dt.year + 1, month=1, day=1,
                         hour=0, minute=0, second=0, microsecond=0)
    else:
        nxt = dt.replace(month=dt.month + 1, day=1,
                         hour=0, minute=0, second=0, microsecond=0)
    return nxt.timestamp()


def _week_start(now: float) -> float:
    dt = datetime.fromtimestamp(now)
    monday = dt - timedelta(days=dt.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _week_end(now: float) -> float:
    return _week_start(now) + 7 * 86400


# --------------------------------------------------------------------------
# local database source
# --------------------------------------------------------------------------

class LocalSource(UsageSource):
    """Sum assistant-message costs stored by opencode itself."""

    name = "local"

    def __init__(
        self,
        monthly_budget: float = 60.0,
        db_path: str | None = None,
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        self.monthly_budget = float(monthly_budget)
        self._db_path = db_path
        self._now = now_fn

    # -- data ------------------------------------------------------------
    def _charges(self, since: float) -> list[tuple[float, float]]:
        db_path = self._db_path or find_database()
        if not db_path:
            raise FileNotFoundError("opencode database not found")

        rows = None
        last_error: Exception | None = None
        for params in ("mode=ro", "mode=ro&immutable=1"):
            uri = f"file:{db_path}?{params}"
            try:
                con = sqlite3.connect(uri, uri=True, timeout=5)
            except sqlite3.Error as exc:  # pragma: no cover - rare
                last_error = exc
                continue
            try:
                con.row_factory = sqlite3.Row
                rows = con.execute(
                    "SELECT time_created, data FROM message "
                    "WHERE time_created >= ?",
                    (int(since * 1000),),
                ).fetchall()
                break
            except sqlite3.Error as exc:
                last_error = exc
            finally:
                con.close()
        if rows is None:
            raise last_error or RuntimeError("cannot read opencode database")

        charges: list[tuple[float, float]] = []
        for row in rows:
            try:
                data = json.loads(row["data"])
            except (TypeError, ValueError):
                continue
            if not isinstance(data, dict) or data.get("role") != "assistant":
                continue
            cost = data.get("cost")
            if not isinstance(cost, (int, float)) or cost <= 0:
                continue
            ts_ms = (data.get("time") or {}).get("created") or row["time_created"]
            try:
                ts = float(ts_ms) / 1000.0
            except (TypeError, ValueError):
                ts = float(row["time_created"]) / 1000.0
            charges.append((ts, float(cost)))
        charges.sort()
        return charges

    # -- source ----------------------------------------------------------
    def fetch(self) -> UsageSnapshot:
        now = self._now()
        try:
            charges = self._charges(now - (ONE_MONTH + 86400))
        except Exception as exc:  # noqa: BLE001 - surfaced in the UI
            return UsageSnapshot(
                windows=[empty_window(k, label, p) for k, label, p, _ in WINDOW_SPECS],
                source=self.name,
                error=f"local data unavailable: {exc}",
                fetched_at=now,
            )

        budget = self.monthly_budget
        starts = {
            "5h": now - FIVE_HOURS,
            "1w": _week_start(now),
            "1m": _month_start(now),
        }
        windows: list[WindowUsage] = []
        for key, label, period, share in WINDOW_SPECS:
            start = starts[key]
            used = sum(c for ts, c in charges if ts >= start)
            limit = budget * share

            if key == "5h":
                inside = [ts for ts, _ in charges if ts >= start]
                reset_at = (min(inside) + FIVE_HOURS) if inside else now + FIVE_HOURS
            elif key == "1w":
                reset_at = _week_end(now)
            else:
                reset_at = _month_end(now)

            windows.append(WindowUsage(
                key=key, label=label, period=period,
                used=used, limit=limit,
                reset_in=max(0.0, reset_at - now),
            ))

        return UsageSnapshot(windows=windows, source=self.name, fetched_at=now)


# --------------------------------------------------------------------------
# API source (Zen / Go)
# --------------------------------------------------------------------------

_DEFAULT_API_BASE = "https://opencode.ai/zen/go/v1"

_WINDOW_PATTERNS = {
    "5h": re.compile(r"(5\s*h|rolling|hour|session)", re.I),
    "1w": re.compile(r"(week|7\s*d)", re.I),
    "1m": re.compile(r"(month|30\s*d)", re.I),
}

_PERCENT_KEY = re.compile(r"(percent|pct|utilization|util|ratio|fraction)", re.I)
_USED_KEY = re.compile(r"(used|usage|spent|consumed|amount|cost)", re.I)
_LIMIT_KEY = re.compile(r"(limit|max|budget|allowance|quota|total)", re.I)
_REMAIN_KEY = re.compile(r"(remaining|left|available)", re.I)
_RESET_KEY = re.compile(r"(reset|renew|expires|expiry|window.?end)", re.I)


def _walk(obj: Any, path: str = ""):
    if isinstance(obj, dict):
        yield path, obj
        for key, value in obj.items():
            yield from _walk(value, f"{path}.{key}" if path else str(key))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from _walk(value, f"{path}[{index}]")


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().rstrip("%"))
        except ValueError:
            return None
    return None


def _to_seconds(value: Any, now: float) -> float | None:
    number = _num(value)
    if number is not None:
        if number > 1e12:          # epoch milliseconds
            return max(0.0, number / 1000.0 - now)
        if number > 1e9:           # epoch seconds
            return max(0.0, number - now)
        return max(0.0, number)    # already a duration
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.astimezone()
        return max(0.0, dt.timestamp() - now)
    return None


def _extract_bucket(node: dict, now: float) -> dict | None:
    """Pull usage/reset numbers out of one candidate dict."""
    fields = {"fraction": None, "used": None, "limit": None,
              "remaining": None, "reset_in": None}
    found = False
    for key, value in node.items():
        if not isinstance(key, str):
            continue
        number = _num(value)
        if _PERCENT_KEY.search(key) and number is not None:
            fields["fraction"] = number / 100.0 if number > 1.0 else number
            found = True
        elif _REMAIN_KEY.search(key) and number is not None:
            fields["remaining"] = number
            found = True
        elif _LIMIT_KEY.search(key) and number is not None:
            fields["limit"] = number
            found = True
        elif _USED_KEY.search(key) and number is not None:
            fields["used"] = number
            found = True
        if _RESET_KEY.search(key):
            seconds = _duration_seconds(key, value, now)
            if seconds is not None:
                fields["reset_in"] = seconds
                found = True
    return fields if found else None


def _duration_seconds(key: str, value: Any, now: float) -> float | None:
    """Like ``_to_seconds`` but rescales bare numbers by the key's unit."""
    seconds = _to_seconds(value, now)
    if seconds is None:
        return None
    number = _num(value)
    if number is not None and number < 1e9:
        lowered = key.lower()
        if "day" in lowered:
            seconds = number * 86400.0
        elif "hour" in lowered or "hrs" in lowered or lowered.endswith("h"):
            seconds = number * 3600.0
        elif "min" in lowered:
            seconds = number * 60.0
        elif "week" in lowered:
            seconds = number * 7 * 86400.0
    return seconds


def parse_usage_payload(
    payload: Any,
    monthly_budget: float = 60.0,
    now: float | None = None,
) -> dict[str, dict]:
    """Best-effort extraction of the three windows from an unknown schema."""
    now = time.time() if now is None else now
    result: dict[str, dict] = {}

    for path, node in _walk(payload):
        if not isinstance(node, dict):
            continue
        keys_text = " ".join(str(k) for k in node.keys())
        for key, value in node.items():
            if isinstance(key, str) and isinstance(value, str) and \
                    key.lower() in ("name", "label", "window", "type", "id",
                                    "scope", "bucket", "period"):
                keys_text += " " + value
        parsed = _extract_bucket(node, now)
        if not parsed:
            continue
        for key, pattern in _WINDOW_PATTERNS.items():
            if key in result:
                continue
            if not (pattern.search(path) or pattern.search(keys_text)):
                continue
            result[key] = parsed
            break

    # assemble with sane fallbacks
    out: dict[str, dict] = {}
    shares = {k: share for k, _, _, share in WINDOW_SPECS}
    for key, label, period, share in WINDOW_SPECS:
        parsed = result.get(key)
        limit = monthly_budget * shares[key]
        used = None
        fraction = None
        reset_in = period
        if parsed:
            if parsed.get("fraction") is not None:
                fraction = parsed["fraction"]
            if parsed.get("used") is not None:
                used = parsed["used"]
                if parsed.get("limit"):
                    limit = parsed["limit"]
            elif parsed.get("remaining") is not None and parsed.get("limit"):
                limit = parsed["limit"]
                used = max(0.0, limit - parsed["remaining"])
            if parsed.get("reset_in") is not None:
                reset_in = parsed["reset_in"]
        if used is None and fraction is not None:
            used = fraction * limit
        if used is None:
            continue
        out[key] = {"label": label, "period": period, "share": share,
                    "used": used, "limit": limit, "reset_in": reset_in}
    return out


def read_api_key() -> str:
    """Look for a Zen/Go key in opencode's auth.json."""
    auth = find_auth_file()
    if not auth:
        return ""
    try:
        data = json.loads(auth.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    for provider in ("opencode-go", "opencode", "opencode-zen"):
        entry = data.get(provider)
        if isinstance(entry, dict) and entry.get("key"):
            return str(entry["key"])
    return ""


class ApiSource(UsageSource):
    """Query the Zen/Go usage endpoint."""

    name = "api"

    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        monthly_budget: float = 60.0,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = (base_url or _DEFAULT_API_BASE).rstrip("/")
        self.api_key = api_key or read_api_key()
        self.monthly_budget = float(monthly_budget)
        self.timeout = timeout

    def _get_json(self) -> Any:
        if not self.api_key:
            raise RuntimeError("no API key found (set one in settings)")
        request = urllib.request.Request(
            f"{self.base_url}/usage",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "User-Agent": "opencode-monitor/0.1",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def fetch(self) -> UsageSnapshot:
        now = time.time()
        try:
            payload = self._get_json()
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                body = exc.read().decode("utf-8", "replace")
                detail = json.loads(body).get("error", {}).get("message", "")
            except Exception:  # noqa: BLE001
                pass
            message = f"HTTP {exc.code}" + (f": {detail}" if detail else "")
            return UsageSnapshot(
                windows=[empty_window(k, label, p) for k, label, p, _ in WINDOW_SPECS],
                source=self.name, error=message, fetched_at=now,
            )
        except Exception as exc:  # noqa: BLE001
            return UsageSnapshot(
                windows=[empty_window(k, label, p) for k, label, p, _ in WINDOW_SPECS],
                source=self.name, error=str(exc), fetched_at=now,
            )

        windows = parse_usage_payload(payload, self.monthly_budget, now)
        if not windows:
            return UsageSnapshot(
                windows=[empty_window(k, label, p) for k, label, p, _ in WINDOW_SPECS],
                source=self.name,
                error="could not parse usage response",
                fetched_at=now,
                raw=payload,
            )

        ordered = []
        for key, label, period, _share in WINDOW_SPECS:
            item = windows.get(key)
            if item is None:
                ordered.append(empty_window(key, label, period))
            else:
                ordered.append(WindowUsage(
                    key=key, label=label, period=item["period"],
                    used=item["used"], limit=item["limit"],
                    reset_in=item["reset_in"],
                ))
        return UsageSnapshot(windows=ordered, source=self.name,
                             fetched_at=now, raw=payload)


# --------------------------------------------------------------------------
# demo source
# --------------------------------------------------------------------------

class DemoSource(UsageSource):
    """Smoothly animated numbers so the widget can be previewed."""

    name = "demo"
    CYCLE = 90.0                               # seconds per demo loop
    OFFSETS = (0.00, 0.35, 0.70)               # desync the three dials

    def __init__(self, now_fn: Callable[[], float] = time.time) -> None:
        self._now = now_fn
        self._t0 = now_fn()

    def fetch(self) -> UsageSnapshot:
        now = self._now()
        elapsed = now - self._t0
        windows = []
        for index, (key, label, win_period, _share) in enumerate(WINDOW_SPECS):
            phase = ((elapsed / (self.CYCLE * (index + 1))
                      + self.OFFSETS[index]) % 1.0)
            used = 0.06 + 0.82 * phase
            windows.append(WindowUsage(
                key=key, label=label, period=win_period,
                used=used * 100.0, limit=100.0,
                reset_in=(1.0 - phase) * win_period,
            ))
        return UsageSnapshot(windows=windows, source=self.name, fetched_at=now)


# --------------------------------------------------------------------------
# factory
# --------------------------------------------------------------------------

@dataclass
class SourceConfig:
    kind: str = "auto"          # auto | api | local | demo
    api_base: str = _DEFAULT_API_BASE
    api_key: str = ""
    monthly_budget: float = 60.0


def build_source(config: SourceConfig) -> UsageSource:
    if config.kind == "demo":
        return DemoSource()
    if config.kind == "api":
        return ApiSource(config.api_base, config.api_key, config.monthly_budget)
    if config.kind == "local":
        return LocalSource(config.monthly_budget)
    return AutoSource(config)


class AutoSource(UsageSource):
    """Try the API first (when a key exists), fall back to local data."""

    name = "auto"

    def __init__(self, config: SourceConfig,
                 local: UsageSource | None = None) -> None:
        self._api = ApiSource(config.api_base, config.api_key,
                              config.monthly_budget)
        self._local = local or LocalSource(config.monthly_budget)

    def fetch(self) -> UsageSnapshot:
        if self._api.api_key:
            snapshot = self._api.fetch()
            if snapshot.ok:
                return snapshot
        snapshot = self._local.fetch()
        if snapshot.ok:
            return snapshot
        if not self._api.api_key:
            snapshot.error = snapshot.error or "no API key configured"
        return snapshot
