#!/usr/bin/env python3
"""Offscreen previews of the widget states and the settings dialog.

Handy for iterating on the visuals (and for CI screenshots):

    QT_QPA_PLATFORM=offscreen python tools/preview.py out_dir
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

from ocmon.i18n import Translator  # noqa: E402
from ocmon.models import UsageSnapshot, WindowUsage, empty_window  # noqa: E402
from ocmon.settings import AppSettings, SettingsDialog  # noqa: E402
from ocmon.sources import WINDOW_SPECS, DemoSource  # noqa: E402
from ocmon.widget import MonitorWidget  # noqa: E402


class Clock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def demo_snapshot() -> UsageSnapshot:
    clock = Clock(1000.0)
    source = DemoSource(now_fn=clock)
    clock.value += 35.0
    return source.fetch()


def live_snapshot() -> UsageSnapshot:
    values = {"5h": (0.42, 3 * 3600 + 900), "1w": (0.18, 4 * 86400),
              "1m": (0.72, 12 * 86400)}
    windows = []
    for key, label, period, _share in WINDOW_SPECS:
        fraction, reset_in = values[key]
        windows.append(WindowUsage(
            key=key, label=label, period=period,
            used=fraction * 60.0, limit=60.0, reset_in=reset_in,
        ))
    return UsageSnapshot(windows=windows, source="local")


def error_snapshot() -> UsageSnapshot:
    return UsageSnapshot(
        windows=[empty_window(k, label, p)
                 for k, label, p, _ in WINDOW_SPECS],
        source="local", error="local data unavailable: database not found",
    )


def main() -> int:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "preview")
    out_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    translator = Translator("en")

    widget = MonitorWidget(translator)
    for name, snapshot in (("widget_demo", demo_snapshot()),
                           ("widget_live", live_snapshot()),
                           ("widget_error", error_snapshot())):
        widget.set_snapshot(snapshot)
        app.processEvents()
        widget.grab().save(str(out_dir / f"{name}.png"))

    widget.set_snapshot(live_snapshot())
    widget.set_mode("remaining")
    app.processEvents()
    widget.grab().save(str(out_dir / "widget_remaining.png"))
    widget.set_mode("used")

    dialog = SettingsDialog(AppSettings(), translator)
    dialog.show()
    app.processEvents()
    dialog.grab().save(str(out_dir / "settings.png"))
    dialog.close()

    print(f"wrote previews to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
