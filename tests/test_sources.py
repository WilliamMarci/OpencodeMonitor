"""Unit tests for the usage sources (stdlib unittest, no network)."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocmon.sources import (  # noqa: E402
    ApiSource, AutoSource, DemoSource, LocalSource, SourceConfig,
    parse_usage_payload,
)

# Thursday 2026-09-17 12:00 local time
NOW = datetime(2026, 9, 17, 12, 0, 0).timestamp()


def make_db(charges: list[tuple[float, float]]) -> str:
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    con = sqlite3.connect(handle.name)
    con.execute(
        "CREATE TABLE message (id TEXT, session_id TEXT, time_created INTEGER,"
        " time_updated INTEGER, data TEXT)")
    for ts, cost in charges:
        con.execute(
            "INSERT INTO message VALUES (?,?,?,?,?)",
            ("msg", "ses", int(ts * 1000), int(ts * 1000),
             json.dumps({"role": "assistant", "cost": cost,
                         "time": {"created": int(ts * 1000)}})))
    con.execute(
        "INSERT INTO message VALUES (?,?,?,?,?)",
        ("user", "ses", int(NOW * 1000), int(NOW * 1000),
         json.dumps({"role": "user"})))
    con.commit()
    con.close()
    return handle.name


class LocalSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.charges = [
            (NOW - 3600, 1.0),        # 5h / 1w / 1m
            (NOW - 3 * 3600, 2.0),    # 5h / 1w / 1m
            (NOW - 5.5 * 3600, 4.0),  # 1w / 1m
            (NOW - 8 * 86400, 8.0),   # 1m only
            (NOW - 20 * 86400, 16.0), # outside everything
        ]
        self.db = make_db(self.charges)
        self.source = LocalSource(monthly_budget=60.0, db_path=self.db,
                                  now_fn=lambda: NOW)

    def test_window_sums(self) -> None:
        snapshot = self.source.fetch()
        windows = {w.key: w for w in snapshot.windows}
        self.assertAlmostEqual(windows["5h"].used, 3.0)
        self.assertAlmostEqual(windows["1w"].used, 7.0)
        self.assertAlmostEqual(windows["1m"].used, 15.0)
        self.assertAlmostEqual(windows["5h"].limit, 12.0)
        self.assertAlmostEqual(windows["1w"].limit, 30.0)
        self.assertAlmostEqual(windows["1m"].limit, 60.0)
        self.assertIsNone(snapshot.error)

    def test_5h_reset_is_oldest_charge_plus_window(self) -> None:
        snapshot = self.source.fetch()
        five_h = {w.key: w for w in snapshot.windows}["5h"]
        # oldest charge inside the window is 3h old -> resets in 2h
        self.assertAlmostEqual(five_h.reset_in, 2 * 3600, delta=1)

    def test_calendar_resets(self) -> None:
        snapshot = self.source.fetch()
        windows = {w.key: w for w in snapshot.windows}
        # next Monday 00:00 = +84h from Thursday noon
        self.assertAlmostEqual(windows["1w"].reset_in, 84 * 3600, delta=1)
        # 1st of October 00:00 = 13.5 days away
        self.assertAlmostEqual(windows["1m"].reset_in, 13.5 * 86400, delta=1)

    def test_percentages(self) -> None:
        snapshot = self.source.fetch()
        windows = {w.key: w for w in snapshot.windows}
        self.assertEqual(windows["5h"].used_percent, 25)
        self.assertEqual(windows["1w"].used_percent, 23)
        self.assertEqual(windows["1m"].used_percent, 25)

    def test_missing_database_reports_error(self) -> None:
        source = LocalSource(db_path="/nonexistent/db.sqlite",
                             now_fn=lambda: NOW)
        snapshot = source.fetch()
        self.assertFalse(snapshot.ok)
        self.assertIn("local data unavailable", snapshot.error or "")


class ParseUsagePayloadTest(unittest.TestCase):
    def test_camel_case_buckets(self) -> None:
        payload = {
            "rollingUsage": {"usagePercent": 42, "resetInSec": 3600},
            "weeklyUsage": {"usagePercent": 10, "resetInSec": 86400},
            "monthlyUsage": {"usagePercent": 80, "resetInSec": 172800},
        }
        parsed = parse_usage_payload(payload, monthly_budget=60, now=NOW)
        self.assertAlmostEqual(parsed["5h"]["used"], 0.42 * 12)
        self.assertAlmostEqual(parsed["5h"]["reset_in"], 3600)
        self.assertAlmostEqual(parsed["1w"]["used"], 0.10 * 30)
        self.assertAlmostEqual(parsed["1m"]["used"], 0.80 * 60)

    def test_used_and_limit(self) -> None:
        payload = {
            "5h": {"used": 3.0, "limit": 12.0, "resetIn": 7200},
            "week": {"used": 7.0, "limit": 30.0, "resetInDays": 3},
            "month": {"used": 15.0, "limit": 60.0, "resetAt":
                      "2026-10-01T00:00:00+00:00"},
        }
        parsed = parse_usage_payload(payload, now=NOW)
        self.assertAlmostEqual(parsed["5h"]["used"], 3.0)
        self.assertAlmostEqual(parsed["5h"]["limit"], 12.0)
        self.assertAlmostEqual(parsed["1w"]["reset_in"], 3 * 86400)
        self.assertGreater(parsed["1m"]["reset_in"], 0)

    def test_remaining_only(self) -> None:
        payload = {"window_5h": {"limit": 12.0, "remaining": 9.0,
                                 "reset": 3600}}
        parsed = parse_usage_payload(payload, now=NOW)
        self.assertAlmostEqual(parsed["5h"]["used"], 3.0)

    def test_envelope_and_fractions(self) -> None:
        payload = {"data": {"rate_limits": [
            {"name": "5 hour", "utilization": 0.25, "reset_in_seconds": 60},
            {"name": "week", "utilization": 0.5, "reset_in_seconds": 120},
            {"name": "month", "utilization": 1.0, "reset_in_seconds": 180},
        ]}}
        parsed = parse_usage_payload(payload, monthly_budget=100, now=NOW)
        self.assertAlmostEqual(parsed["5h"]["used"], 0.25 * 20)
        self.assertAlmostEqual(parsed["1w"]["used"], 0.5 * 50)
        self.assertAlmostEqual(parsed["1m"]["used"], 1.0 * 100)

    def test_unparseable_payload(self) -> None:
        self.assertEqual(parse_usage_payload({"hello": "world"}, now=NOW), {})


class FakeApi(ApiSource):
    def __init__(self, payload=None, error: Exception | None = None) -> None:
        super().__init__(api_key="test-key")
        self._payload = payload
        self._error = error

    def _get_json(self):
        if self._error:
            raise self._error
        return self._payload


class AutoSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_db([(NOW - 3600, 2.5)])
        self.local = LocalSource(monthly_budget=60.0, db_path=self.db,
                                 now_fn=lambda: NOW)

    def test_uses_api_when_it_works(self) -> None:
        source = AutoSource(SourceConfig(kind="auto"), local=self.local)
        source._api = FakeApi({"rollingUsage": {"usagePercent": 5,
                                                "resetInSec": 10}})
        snapshot = source.fetch()
        self.assertEqual(snapshot.source, "api")

    def test_falls_back_to_local(self) -> None:
        source = AutoSource(SourceConfig(kind="auto"), local=self.local)
        source._api = FakeApi(error=RuntimeError("nope"))
        snapshot = source.fetch()
        self.assertEqual(snapshot.source, "local")
        self.assertTrue(snapshot.ok)

    def test_no_key_uses_local(self) -> None:
        class NoKeyApi(ApiSource):
            def __init__(self):
                super().__init__(api_key="x")

            @property
            def api_key(self):  # type: ignore[override]
                return ""

            @api_key.setter
            def api_key(self, value):
                pass

        source = AutoSource(SourceConfig(kind="auto"), local=self.local)
        source._api = NoKeyApi()
        snapshot = source.fetch()
        self.assertEqual(snapshot.source, "local")


class DemoSourceTest(unittest.TestCase):
    def test_produces_three_windows(self) -> None:
        snapshot = DemoSource(now_fn=lambda: NOW).fetch()
        self.assertEqual(len(snapshot.windows), 3)
        self.assertTrue(snapshot.ok)
        for window in snapshot.windows:
            self.assertGreaterEqual(window.used_fraction, 0.0)
            self.assertLessEqual(window.used_fraction, 1.0)
            self.assertGreater(window.reset_in, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
