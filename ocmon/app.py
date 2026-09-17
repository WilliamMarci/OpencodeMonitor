"""Application controller: tray icon, timers, settings, widget wiring."""

from __future__ import annotations

import argparse
import sys

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor, QGuiApplication, QIcon, QPainter, \
    QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import APP_NAME, ORG_NAME, __version__
from .i18n import Translator
from .models import UsageSnapshot, empty_window
from .settings import AppSettings, SettingsDialog
from .sources import WINDOW_SPECS, SourceConfig, build_source
from .widget import MonitorWidget


def make_icon_pixmap(size: int = 64) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    margin = size * 0.10
    box = size - margin * 2.0
    painter.setPen(QPen(QColor(52, 211, 153), size * 0.11,
                        Qt.SolidLine, Qt.RoundCap))
    painter.drawArc(int(margin), int(margin), int(box), int(box),
                    90 * 16, -int(0.72 * 360 * 16))
    inner = margin + size * 0.18
    painter.setPen(QPen(QColor(96, 165, 250), size * 0.08,
                        Qt.SolidLine, Qt.RoundCap))
    painter.drawArc(int(inner), int(inner), int(box - size * 0.36),
                    int(box - size * 0.36), 90 * 16, -int(0.45 * 360 * 16))
    painter.end()
    return pixmap


def make_icon(size: int = 64) -> QIcon:
    return QIcon(make_icon_pixmap(size))


class _TaskSignals(QObject):
    done = Signal(object)


class _FetchTask(QRunnable):
    def __init__(self, config: SourceConfig) -> None:
        super().__init__()
        self.signals = _TaskSignals()
        self._config = config

    def run(self) -> None:  # noqa: D102
        try:
            snapshot = build_source(self._config).fetch()
        except Exception as exc:  # noqa: BLE001
            snapshot = UsageSnapshot(
                windows=[empty_window(k, label, p)
                         for k, label, p, _ in WINDOW_SPECS],
                source=self._config.kind, error=str(exc),
            )
        self.signals.done.emit(snapshot)


class Controller(QObject):
    def __init__(self, app: QApplication, settings: AppSettings,
                 args: argparse.Namespace) -> None:
        super().__init__()
        self._app = app
        self._settings = settings
        self._args = args
        self._snapshot: UsageSnapshot | None = None
        self._busy = False
        self._pool = QThreadPool.globalInstance()
        self._t = Translator(settings.language)

        self.widget = MonitorWidget(
            self._t,
            mode=settings.mode,
            topmost=settings.always_on_top,
        )
        self.widget.setWindowIcon(make_icon(64))
        self._restore_position()
        self._apply_opacity()

        self.widget.settings_requested.connect(self.open_settings)
        self.widget.refresh_requested.connect(self.refresh)
        self.widget.mode_changed.connect(self.set_mode)
        self.widget.topmost_changed.connect(self.set_topmost)
        self.widget.quit_requested.connect(self.quit)
        self.widget.position_changed.connect(self._remember_position)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.refresh)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._tick)

        self._tray = self._build_tray()

        self.refresh()
        self._restart_refresh_timer()
        self._tick_timer.start()

    # -- lifecycle -------------------------------------------------------
    def start(self) -> None:
        self.widget.show()

    def quit(self) -> None:
        self._remember_position(self.widget.x(), self.widget.y())
        self._settings.save()
        self._tray.hide()
        self._app.quit()

    # -- data ------------------------------------------------------------
    def refresh(self) -> None:
        if self._busy:
            return
        config = self._settings.source_config()
        if getattr(self._args, "demo", False):
            config = SourceConfig(kind="demo")
        self._busy = True
        task = _FetchTask(config)
        task.signals.done.connect(self._on_snapshot)
        self._pool.start(task)

    def _on_snapshot(self, snapshot: UsageSnapshot) -> None:
        self._busy = False
        self._snapshot = snapshot
        self.widget.set_snapshot(snapshot)
        self._update_tray_tooltip()

    def _tick(self) -> None:
        self.widget.update()

    def _restart_refresh_timer(self) -> None:
        self._refresh_timer.start(max(15, self._settings.refresh_sec) * 1000)

    # -- appearance ------------------------------------------------------
    def _apply_opacity(self) -> None:
        self.widget.setWindowOpacity(max(0.3, self._settings.opacity / 100.0))

    def _restore_position(self) -> None:
        screen = QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen else None
        x, y = self._settings.pos_x, self._settings.pos_y
        if x is None or y is None:
            if area:
                x = area.right() - self.widget.width() - 24
                y = area.bottom() - self.widget.height() - 48
            else:
                x, y = 60, 60
        if area:
            x = min(max(x, area.left()), area.right() - self.widget.width())
            y = min(max(y, area.top()), area.bottom() - self.widget.height())
        self.widget.move(int(x), int(y))

    def _remember_position(self, x: int, y: int) -> None:
        self._settings.pos_x = int(x)
        self._settings.pos_y = int(y)

    def set_mode(self, mode: str) -> None:
        self._settings.mode = mode
        self._settings.save()
        self.widget.set_mode(mode)

    def set_topmost(self, topmost: bool) -> None:
        self._settings.always_on_top = topmost
        self._settings.save()
        self.widget.apply_topmost(topmost)
        self._topmost_action.setChecked(topmost)

    # -- settings --------------------------------------------------------
    def open_settings(self) -> None:
        dialog = SettingsDialog(self._settings, self._t, self.widget)
        if dialog.exec() != SettingsDialog.Accepted:
            return
        dialog.apply_to_settings()
        self._settings.save()
        self._t.set_language(self._settings.language)
        self._retranslate()
        self.widget.set_mode(self._settings.mode)
        self.widget.apply_topmost(self._settings.always_on_top)
        self._apply_opacity()
        self._restart_refresh_timer()
        self.refresh()

    def _retranslate(self) -> None:
        self.widget.setWindowTitle(self._t("window_title"))
        self._refresh_action.setText(self._t("refresh_now"))
        self._settings_action.setText(self._t("settings"))
        self._topmost_action.setText(self._t("always_on_top"))
        self._quit_action.setText(self._t("quit"))
        self._show_action.setText(self._t("show"))
        self._hide_action.setText(self._t("hide"))
        self._tray.setToolTip(self._t("window_title"))

    # -- tray ------------------------------------------------------------
    def _build_tray(self) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(make_icon(64), self)
        menu = QMenu()

        self._show_action = QAction(self._t("show"), menu)
        self._show_action.triggered.connect(self.widget.show)
        menu.addAction(self._show_action)

        self._hide_action = QAction(self._t("hide"), menu)
        self._hide_action.triggered.connect(self.widget.hide)
        menu.addAction(self._hide_action)
        menu.addSeparator()

        self._refresh_action = QAction(self._t("refresh_now"), menu)
        self._refresh_action.triggered.connect(self.refresh)
        menu.addAction(self._refresh_action)

        self._settings_action = QAction(self._t("settings"), menu)
        self._settings_action.triggered.connect(self.open_settings)
        menu.addAction(self._settings_action)

        self._topmost_action = QAction(self._t("always_on_top"), menu)
        self._topmost_action.setCheckable(True)
        self._topmost_action.setChecked(self._settings.always_on_top)
        self._topmost_action.triggered.connect(self.set_topmost)
        menu.addAction(self._topmost_action)
        menu.addSeparator()

        self._quit_action = QAction(self._t("quit"), menu)
        self._quit_action.triggered.connect(self.quit)
        menu.addAction(self._quit_action)

        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)

        if QSystemTrayIcon.isSystemTrayAvailable():
            tray.show()
        return tray

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            if self.widget.isVisible():
                self.widget.hide()
            else:
                self.widget.show()

    def _update_tray_tooltip(self) -> None:
        if self._snapshot is None:
            self._tray.setToolTip(self._t("window_title"))
            return
        lines = [self._t("window_title")]
        for window in self._snapshot.windows:
            if window.has_data:
                lines.append(
                    f"{window.label}: {window.used_percent}%  "
                    f"(${window.used:,.2f}/${window.limit:,.2f})")
        if self._snapshot.error:
            lines.append(f"! {self._snapshot.error}")
        self._tray.setToolTip("\n".join(lines))


def run(args: argparse.Namespace) -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)

    settings = AppSettings.load()
    controller = Controller(app, settings, args)
    controller.start()

    if getattr(args, "screenshot", None):
        def _shoot() -> None:
            controller.widget.grab().save(args.screenshot)
            controller.quit()
        QTimer.singleShot(1200, _shoot)

    return app.exec()
