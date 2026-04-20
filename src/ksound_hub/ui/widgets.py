from __future__ import annotations

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionComboBox,
    QVBoxLayout,
    QWidget,
)


class CenteredComboBox(QComboBox):
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        option.currentText = ""
        self.style().drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option, painter, self)

        arrow_space = max(18, self.height() - 6)
        symmetric_pad = arrow_space + 4
        text_rect = self.rect().adjusted(symmetric_pad, 0, -symmetric_pad, 0)

        painter.save()
        painter.setPen(option.palette.buttonText().color())
        text = option.fontMetrics.elidedText(
            self.currentText(),
            Qt.ElideRight,
            max(12, text_rect.width() - 2),
        )
        painter.drawText(text_rect, Qt.AlignCenter | Qt.AlignVCenter, text)
        painter.restore()


class StereoLevelMeterWidget(QWidget):
    def __init__(self, side: str, parent=None):
        super().__init__(parent)
        self.side = side
        self._value = 0.0
        self._segments = 14
        self.setFixedWidth(16)
        self.setMinimumHeight(154)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setToolTip(f"{side.upper()} meter. It stays idle until backend audio levels are wired.")

    def clear(self) -> None:
        self.set_level(0.0)

    def set_level(self, value: float) -> None:
        self._value = max(0.0, min(1.0, float(value)))
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.fillRect(self.rect(), QColor("#10141d"))

        width = max(1, self.width())
        height = max(1, self.height())
        margin = 3
        gap = 2
        usable_h = max(1, height - margin * 2)
        seg_h = max(2, (usable_h - gap * (self._segments - 1)) // self._segments)
        lit = int(round(self._value * self._segments))

        y = height - margin - seg_h
        for i in range(self._segments):
            level_index = self._segments - 1 - i
            active = level_index < lit
            if not active:
                color = QColor("#1a2430")
            elif i < 7:
                color = QColor("#34d3ff")
            elif i < 11:
                color = QColor("#ff65d4")
            else:
                color = QColor("#ffd166")
            painter.fillRect(margin, y, width - margin * 2, seg_h, color)
            y -= seg_h + gap

        painter.setPen(QPen(QColor("#35506a")))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


class EqBandSlider(QWidget):
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
        self.slider.setFixedHeight(112)
        self.slider.setFixedWidth(24)
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
            "background: rgba(52, 211, 255, 32); border: 1px solid rgba(52, 211, 255, 82); border-radius: 8px; padding: 3px 7px;"
        )
