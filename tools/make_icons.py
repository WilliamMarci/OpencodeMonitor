#!/usr/bin/env python3
"""Regenerate assets/icon-256.png and assets/icon.ico from the Qt painter.

    python tools/make_icons.py

The .ico step needs Pillow (``pip install pillow``).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from ocmon.app import make_icon_pixmap  # noqa: E402

SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128),
         (256, 256)]


def main() -> int:
    app = QApplication(sys.argv)
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)

    png_path = assets / "icon-256.png"
    make_icon_pixmap(256).save(str(png_path))
    print(f"wrote {png_path}")

    try:
        from PIL import Image
    except ImportError:
        print("Pillow not installed - skipped icon.ico")
        return 0

    ico_path = assets / "icon.ico"
    Image.open(png_path).save(ico_path, sizes=SIZES)
    print(f"wrote {ico_path}")
    app.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
