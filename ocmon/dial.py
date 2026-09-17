"""A single double-ring dial (outer = usage, inner = reset countdown)."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .models import WindowUsage

TRACK = QColor(255, 255, 255, 28)
TEXT = QColor(243, 244, 246)
LABEL = QColor(156, 163, 175)
INNER = QColor(96, 165, 250)
INNER_WARN = QColor(245, 158, 11)
MUTED = QColor(148, 163, 184)


def severity_color(fraction: float) -> QColor:
    if fraction < 0.50:
        return QColor(52, 211, 153)     # green
    if fraction < 0.75:
        return QColor(251, 191, 36)     # amber
    if fraction < 0.90:
        return QColor(251, 146, 60)     # orange
    return QColor(248, 113, 113)        # red


class RingDial(QWidget):
    """Fixed-size dial: outer usage ring, inner reset ring, % in the middle."""

    DIAMETER = 64
    LABEL_HEIGHT = 14
    OUTER_WIDTH = 5.0
    INNER_WIDTH = 3.5
    GAP = 3.5

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label = label
        self._window: WindowUsage | None = None
        self._mode = "used"
        self.setFixedSize(self.DIAMETER, self.DIAMETER + self.LABEL_HEIGHT)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    # -- state -----------------------------------------------------------
    def set_usage(self, window: WindowUsage | None, mode: str) -> None:
        self._window = window
        self._mode = mode
        self.update()

    # -- painting --------------------------------------------------------
    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        size = self.DIAMETER
        cx = size / 2.0
        cy = size / 2.0

        outer_r = cx - self.OUTER_WIDTH / 2.0 - 1.0
        inner_r = outer_r - self.OUTER_WIDTH / 2.0 - self.GAP \
            - self.INNER_WIDTH / 2.0

        self._draw_track(painter, cx, cy, outer_r, self.OUTER_WIDTH)
        self._draw_track(painter, cx, cy, inner_r, self.INNER_WIDTH)

        window = self._window
        if window is not None and window.has_data:
            outer_fraction = (window.used_fraction if self._mode == "used"
                              else window.remaining_fraction)
            painter.setPen(self._arc_pen(
                severity_color(window.used_fraction), self.OUTER_WIDTH))
            self._draw_arc(painter, cx, cy, outer_r, outer_fraction)

            reset_fraction = window.reset_fraction
            inner_color = INNER_WARN if reset_fraction < 0.12 else INNER
            painter.setPen(self._arc_pen(inner_color, self.INNER_WIDTH))
            self._draw_arc(painter, cx, cy, inner_r, reset_fraction)

            percent = (window.used_percent if self._mode == "used"
                       else window.remaining_percent)
            text = f"{percent}%"
            text_color = TEXT
        else:
            text = "--"
            text_color = MUTED

        font = QFont()
        font.setFamilies(["Consolas", "Menlo", "DejaVu Sans Mono",
                          "Courier New", "monospace"])
        font.setPixelSize(12)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(text_color)
        painter.drawText(
            QRectF(0, 0, size, size), Qt.AlignCenter, text)

        label_font = QFont()
        label_font.setPixelSize(10)
        painter.setFont(label_font)
        painter.setPen(LABEL)
        painter.drawText(
            QRectF(0, size, size, self.LABEL_HEIGHT),
            Qt.AlignHCenter | Qt.AlignTop, self._label)

        painter.end()

    @staticmethod
    def _arc_pen(color: QColor, width: float) -> QPen:
        pen = QPen(color, width)
        pen.setCapStyle(Qt.RoundCap)
        return pen

    @staticmethod
    def _rect(cx: float, cy: float, radius: float) -> QRectF:
        return QRectF(cx - radius, cy - radius, radius * 2.0, radius * 2.0)

    def _draw_track(self, painter: QPainter, cx: float, cy: float,
                    radius: float, width: float) -> None:
        painter.setPen(QPen(TRACK, width))
        painter.drawArc(self._rect(cx, cy, radius), 0, 360 * 16)

    def _draw_arc(self, painter: QPainter, cx: float, cy: float,
                  radius: float, fraction: float) -> None:
        if fraction <= 0.0:
            return
        span = int(round(-360 * 16 * min(1.0, fraction)))
        painter.drawArc(self._rect(cx, cy, radius), 90 * 16, span)
