from __future__ import annotations

from collections import deque

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class LevelMeterWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._values: deque[float] = deque([0.0] * 16, maxlen=16)
        self._phase = 0

        self._timer = QTimer(self)
        self._timer.setInterval(110)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self.setMinimumHeight(48)

    def _tick(self) -> None:
        self._phase = (self._phase + 1) % 16
        level = ((self._phase * 7) % 11) / 10.0
        self._values.append(level)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.fillRect(self.rect(), QColor("#141821"))

        if not self._values:
            return

        width = max(1, self.width())
        height = max(1, self.height())
        gap = 2
        bar_count = len(self._values)
        bar_width = max(3, (width - gap * (bar_count - 1)) // bar_count)

        x = 0
        for value in self._values:
            bar_height = max(3, int((height - 6) * value))
            y = height - bar_height - 3
            color = QColor("#4ea1ff") if value < 0.8 else QColor("#f6c945")
            painter.fillRect(x, y, bar_width, bar_height, color)
            x += bar_width + gap

        painter.setPen(QPen(QColor("#31405d")))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
