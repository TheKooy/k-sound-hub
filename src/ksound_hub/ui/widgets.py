from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class SelectorFrame(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = self.rect().adjusted(0, 0, -1, -1)
        pen = QPen(QColor(62, 216, 255, 88), 1.45)
        painter.setPen(pen)
        painter.setBrush(QColor(8, 12, 19, 220))
        painter.drawRoundedRect(rect, 12, 12)


class SelectorPopupItem(QPushButton):
    def __init__(self, text: str, selected: bool, parent=None):
        super().__init__(text, parent)
        self._selected = selected
        self.setFlat(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(32)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet("background: transparent; border: none; color: #edf4ff;")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        rect = self.rect().adjusted(0, 0, -1, -1)

        if self._selected:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(62, 216, 255, 56))
            painter.drawRoundedRect(rect.adjusted(2, 1, -2, -1), 8, 8)
        elif self.underMouse():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 92, 199, 70))
            painter.drawRoundedRect(rect.adjusted(2, 1, -2, -1), 8, 8)

        painter.setPen(QColor("#edf4ff"))
        painter.drawText(self.rect().adjusted(10, 0, -10, 0), Qt.AlignCenter | Qt.AlignVCenter, self.text())


class SelectorPopup(QWidget):
    itemChosen = Signal(str)

    def __init__(self, parent=None):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self._content = QWidget(self)
        self._content.setAttribute(Qt.WA_TranslucentBackground, True)
        self._content.setAutoFillBackground(False)
        self._content.setStyleSheet("background: transparent;")

        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(4, 4, 4, 6)
        self._content_layout.setSpacing(2)

        self._layout.addWidget(self._content)

    def clear_items(self) -> None:
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def set_items(self, items: list[str], current_text: str) -> None:
        self.clear_items()
        for item_text in items:
            btn = SelectorPopupItem(item_text, item_text == current_text, self._content)
            btn.clicked.connect(lambda checked=False, text=item_text: self._choose(text))
            self._content_layout.addWidget(btn)

    def _choose(self, text: str) -> None:
        self.itemChosen.emit(text)
        self.close()

    def show_below(self, anchor: QWidget) -> None:
        self.setFixedWidth(anchor.width())
        self.adjustSize()

        top_left = anchor.mapToGlobal(anchor.rect().topLeft())
        x = top_left.x() + (anchor.width() - self.width()) // 2
        y = top_left.y() + anchor.height() + 3
        self.move(x, y)
        self.show()
        self.raise_()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.setPen(QPen(QColor(62, 216, 255, 88), 1.45))
        painter.setBrush(QColor(8, 12, 19, 245))
        painter.drawRoundedRect(rect, 12, 12)


class MenuSelectorButton(QPushButton):
    currentTextChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[str] = []
        self._current_text = ""
        self._popup: SelectorPopup | None = None
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.clicked.connect(self._open_menu)

    def set_items(self, items: list[str]) -> None:
        self._items = [str(x) for x in items]
        if self._items and self._current_text not in self._items:
            self._current_text = self._items[0]
        self.update()

    def currentText(self) -> str:
        return self._current_text

    def setCurrentText(self, value: str) -> None:
        if self._items:
            new_value = value if value in self._items else self._items[0]
        else:
            new_value = str(value)

        changed = new_value != self._current_text
        self._current_text = new_value
        self.update()
        if changed:
            self.currentTextChanged.emit(new_value)

    def _open_menu(self) -> None:
        if not self._items:
            return

        anchor = self.parentWidget() if self.parentWidget() is not None else self

        if self._popup is not None:
            self._popup.close()
            self._popup.deleteLater()
            self._popup = None

        popup = SelectorPopup(self)
        popup.set_items(self._items, self._current_text)
        popup.itemChosen.connect(self.setCurrentText)
        popup.show_below(anchor)
        self._popup = popup

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        text_rect = self.rect().adjusted(10, 0, -10, 0)

        painter.save()
        painter.setPen(self.palette().buttonText().color())
        text = self.fontMetrics().elidedText(
            self._current_text,
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
