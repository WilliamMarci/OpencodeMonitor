"""Launch-at-login helpers for Linux (XDG autostart) and Windows (registry)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

DESKTOP_FILE = "opencode-monitor.desktop"


def _command() -> list[str]:
    if getattr(sys, "frozen", False):          # PyInstaller build
        return [sys.executable, "--autostart"]
    main_py = Path(__file__).resolve().parent.parent / "main.py"
    return [sys.executable, str(main_py), "--autostart"]


def is_supported() -> bool:
    return os.name == "nt" or sys.platform.startswith("linux")


def is_enabled() -> bool:
    if os.name == "nt":
        import winreg
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
            )
            winreg.QueryValueEx(key, "OpencodeMonitor")
            return True
        except OSError:
            return False
    path = Path.home() / ".config" / "autostart" / DESKTOP_FILE
    return path.is_file()


def set_enabled(enabled: bool) -> None:
    if os.name == "nt":
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        )
        try:
            if enabled:
                winreg.SetValueEx(key, "OpencodeMonitor", 0, winreg.REG_SZ,
                                  " ".join(f'"{part}"' for part in _command()))
            else:
                try:
                    winreg.DeleteValue(key, "OpencodeMonitor")
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)
        return

    path = Path.home() / ".config" / "autostart" / DESKTOP_FILE
    if not enabled:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    exec_line = " ".join(f'"{part}"' for part in _command())
    path.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=OpencodeMonitor\n"
        "Comment=opencode usage widget\n"
        f"Exec={exec_line}\n"
        "X-GNOME-Autostart-enabled=true\n"
        "Terminal=false\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
