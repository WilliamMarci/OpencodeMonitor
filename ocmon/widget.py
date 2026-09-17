"""Frameless, always-on-top usage widget made of three double-ring dials."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QPainter, QPen
from PySide6.QtWidgets import QMenu, QToolTip, QWidget

from .dial import RingDial
from .i18n import Translator
from .models import UsageSnapshot

MARGIN = 10
GAP = 8
RADIUS = 14


def format_duration(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds >= 86400:
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        return f"{days}d {hours}h"
    if seconds >= 3600:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes:02d}m"
    if seconds >= 60:
        return f"{int(seconds // 60)}m"
    return f"{int(seconds)}s"


class MonitorWidget(QWidget):
    settings_requested = Signal()
    refresh_requested = Signal()
    mode_changed = Signal(str)
    topmost_changed = Signal(bool)
    quit_requested = Signal()
    position_changed = Signal(int, int)

    def __init__(self, translator: Translator, mode: str = "used",
                 topmost: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._t = translator
        self._mode = mode
        self._topmost = topmost
        self._snapshot: UsageSnapshot | None = None
        self._drag_offset: QPoint | None = None
        self._hover_index = -1

        self.setWindowTitle(translator("window_title"))
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.Tool
            | (Qt.WindowStaysOnTopHint if topmost else Qt.WindowType(0))
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        self.dials = [RingDial("5h", self), RingDial("1w", self),
                      RingDial("1m", self)]
        width = MARGIN * 2 + RingDial.DIAMETER * 3 + GAP * 2
        height = MARGIN * 2 + RingDial.DIAMETER + RingDial.LABEL_HEIGHT
        self.setFixedSize(width, height)
        for index, dial in enumerate(self.dials):
            dial.move(MARGIN + index * (RingDial.DIAMETER + GAP), MARGIN)

    # -- public API ------------------------------------------------------
    def set_snapshot(self, snapshot: UsageSnapshot) -> None:
        self._snapshot = snapshot
        for index, dial in enumerate(self.dials):
            window = snapshot.windows[index] \
                if index < len(snapshot.windows) else None
            dial.set_usage(window, self._mode)
        self.update()

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self.set_snapshot(self._snapshot) if self._snapshot else self.update()

    def apply_topmost(self, topmost: bool) -> None:
        self._topmost = topmost
        flags = self.windowFlags()
        if topmost:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()

    # -- painting --------------------------------------------------------
    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        painter.setPen(QPen(QColor(255, 255, 255, 26), 1.0))
        painter.setBrush(QColor(14, 17, 23, 240))
        painter.drawRoundedRect(rect, RADIUS, RADIUS)

        if self._snapshot is not None:
            self._draw_status_dot(painter)
        painter.end()

    def _draw_status_dot(self, painter: QPainter) -> None:
        snapshot = self._snapshot
        if snapshot is None:
            return
        if snapshot.error and not snapshot.ok:
            color = QColor(248, 113, 113)
        elif snapshot.source in ("demo", "auto"):
            color = QColor(251, 191, 36) if snapshot.source == "demo" \
                else QColor(52, 211, 153)
        else:
            color = QColor(52, 211, 153)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QRectF(self.width() - 12.0, 6.0, 5.0, 5.0))

    # -- interaction -----------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint()
                - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None and \
                event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        self._update_tooltip(event.position().toPoint())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            position = self.pos()
            self.position_changed.emit(position.x(), position.y())
            event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.settings_requested.emit()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = QMenu(self)
        menu.setAttribute(Qt.WA_TranslucentBackground, False)

        refresh = QAction(self._t("refresh_now"), menu)
        refresh.triggered.connect(self.refresh_requested.emit)
        menu.addAction(refresh)

        settings = QAction(self._t("settings"), menu)
        settings.triggered.connect(self.settings_requested.emit)
        menu.addAction(settings)
        menu.addSeparator()

        used = QAction(self._t("show_used"), menu)
        used.setCheckable(True)
        used.setChecked(self._mode == "used")
        used.triggered.connect(lambda: self.mode_changed.emit("used"))
        menu.addAction(used)

        remaining = QAction(self._t("show_remaining"), menu)
        remaining.setCheckable(True)
        remaining.setChecked(self._mode == "remaining")
        remaining.triggered.connect(lambda: self.mode_changed.emit("remaining"))
        menu.addAction(remaining)
        menu.addSeparator()

        topmost = QAction(self._t("always_on_top"), menu)
        topmost.setCheckable(True)
        topmost.setChecked(self._topmost)
        topmost.triggered.connect(self.topmost_changed.emit)
        menu.addAction(topmost)
        menu.addSeparator()

        quit_action = QAction(self._t("quit"), menu)
        quit_action.triggered.connect(self.quit_requested.emit)
        menu.addAction(quit_action)

        menu.exec(event.globalPos())

    def _dial_index_at(self, position: QPoint) -> int:
        x = position.x()
        for index in range(len(self.dials)):
            start = MARGIN + index * (RingDial.DIAMETER + GAP)
            if start <= x <= start + RingDial.DIAMETER:
                return index
        return -1

    def _update_tooltip(self, position: QPoint) -> None:
        index = self._dial_index_at(position)
        if index < 0 or index == self._hover_index:
            if index < 0:
                self._hover_index = -1
                QToolTip.hideText()
            return
        self._hover_index = index
        snapshot = self._snapshot
        if snapshot is None or index >= len(snapshot.windows):
            QToolTip.hideText()
            return
        window = snapshot.windows[index]
        if not window.has_data:
            text = self._t("tip_no_data", label=window.label)
        else:
            text = self._t(
                "tip_window",
                label=window.label,
                used=f"${window.used:,.2f}",
                limit=f"${window.limit:,.2f}",
                percent=window.used_percent,
                reset=format_duration(window.reset_in),
            )
        QToolTip.showText(self.mapToGlobal(position), text, self)
