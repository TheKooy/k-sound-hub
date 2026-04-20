from __future__ import annotations

from collections import deque
from typing import Iterable

from PySide6.QtCore import QEasingCurve, Property, QPropertyAnimation, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class LevelMeterWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._values: deque[float] = deque([0.0] * 14, maxlen=14)
        self._phase = 0
        self._running = True

        self._timer = QTimer(self)
        self._timer.setInterval(95)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self.setMinimumHeight(54)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_running(self, running: bool) -> None:
        self._running = running
        self.update()

    def _tick(self) -> None:
        if not self._running:
            self._values.append(0.0)
            self.update()
            return
        self._phase = (self._phase + 1) % 18
        level = ((self._phase * 11) % 13) / 12.0
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
            bar_height = max(2, int((height - 8) * value))
            y = height - bar_height - 4
            if value < 0.55:
                color = QColor("#4ea1ff")
            elif value < 0.85:
                color = QColor("#8fd16a")
            else:
                color = QColor("#f6c945")
            painter.fillRect(x, y, bar_width, bar_height, color)
            x += bar_width + gap

        painter.setPen(QPen(QColor("#31405d")))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


class EqBandSlider(QWidget):
    valueChanged = Property(int)

    def __init__(self, label: str, value: int = 0, parent=None):
        super().__init__(parent)
        self._label_text = label
        self._value = value

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        self.value_label = QLabel(f"{value:+d}")
        self.value_label.setAlignment(Qt.AlignCenter)
        self.value_label.setObjectName("mutedLabel")
        root.addWidget(self.value_label)

        from PySide6.QtWidgets import QSlider

        self.slider = QSlider(Qt.Vertical)
        self.slider.setRange(-12, 12)
        self.slider.setValue(value)
        self.slider.setTickPosition(QSlider.NoTicks)
        self.slider.valueChanged.connect(self._on_value_changed)
        self.slider.setFixedHeight(120)
        self.slider.setFixedWidth(28)
        root.addWidget(self.slider, alignment=Qt.AlignHCenter)

        self.label = QLabel(label)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setObjectName("mutedLabel")
        root.addWidget(self.label)

    def _on_value_changed(self, value: int) -> None:
        self._value = value
        self.value_label.setText(f"{value:+d}")

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, value: int) -> None:
        self.slider.setValue(value)


class CollapsibleSection(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("sectionCard")
        self._expanded = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        self.toggle_button = QPushButton(f"▸ {title}")
        self.toggle_button.setObjectName("sectionToggle")
        self.toggle_button.setCheckable(True)
        self.toggle_button.clicked.connect(self.setExpanded)
        header.addWidget(self.toggle_button)
        header.addStretch(1)
        outer.addLayout(header)

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(6)
        self.content.setVisible(False)
        outer.addWidget(self.content)

    def setExpanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self.toggle_button.setChecked(self._expanded)
        text = self.toggle_button.text()
        if text.startswith("▸") or text.startswith("▾"):
            text = text[1:].lstrip()
        self.toggle_button.setText(("▾ " if self._expanded else "▸ ") + text)
        self.content.setVisible(self._expanded)

    def isExpanded(self) -> bool:
        return self._expanded


class HeaderBadge(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            "background: rgba(77, 120, 173, 70); border: 1px solid rgba(128, 170, 255, 80); border-radius: 8px; padding: 3px 7px;"
        )
