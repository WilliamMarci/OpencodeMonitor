#!/usr/bin/env python3
"""OpencodeMonitor - compact always-on-top opencode usage widget."""

from __future__ import annotations

import argparse
import sys

from ocmon.app import run


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="opencode-monitor",
        description="Always-on-top widget showing opencode usage "
                    "(5h / 1w / 1m).",
    )
    parser.add_argument("--demo", action="store_true",
                        help="use animated demo data (no opencode needed)")
    parser.add_argument("--screenshot", metavar="PATH",
                        help="render the widget to a PNG and exit")
    parser.add_argument("--autostart", action="store_true",
                        help="hint that the app was launched at login")
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
