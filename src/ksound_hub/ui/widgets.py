from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QDoubleValidator, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
    QLineEdit,
)


class NoWheelSlider(QSlider):
    def wheelEvent(self, event) -> None:
        event.accept()

    def _position_to_value(self, pos) -> int:
        minimum = self.minimum()
        maximum = self.maximum()
        span = max(1, maximum - minimum)

        if self.orientation() == Qt.Vertical:
            usable = max(1, self.height() - 1)
            ratio = 1.0 - (max(0, min(usable, pos.y())) / usable)
        else:
            usable = max(1, self.width() - 1)
            ratio = max(0, min(usable, pos.x())) / usable

        if self.invertedAppearance():
            ratio = 1.0 - ratio

        return int(round(minimum + ratio * span))

    def _set_value_from_mouse_event(self, event) -> None:
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        self.setValue(self._position_to_value(pos))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.setSliderDown(True)
            self.sliderPressed.emit()
            self._set_value_from_mouse_event(event)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.LeftButton:
            self._set_value_from_mouse_event(event)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.isSliderDown():
            self._set_value_from_mouse_event(event)
            self.setSliderDown(False)
            self.sliderReleased.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class SelectorFrame(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        pen = QPen(QColor(62, 216, 255, 96), 1.7)
        pen.setJoinStyle(Qt.RoundJoin)
        inset = pen.widthF() / 2.0
        rect = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)

        painter.setPen(pen)
        painter.setBrush(QColor(8, 12, 19, 220))
        painter.drawRoundedRect(rect, 12, 12)


class SelectorPopupItem(QPushButton):
    def __init__(self, text: str, selected: bool, parent=None):
        super().__init__(text, parent)
        self._selected = selected
        self._hover_scroll_offset = 0
        self._hover_scroll_timer = QTimer(self)
        self._hover_scroll_timer.setInterval(45)
        self._hover_scroll_timer.timeout.connect(self._advance_hover_scroll)

        self.setMouseTracking(True)
        self.setFlat(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(32)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet("background: transparent; border: none; color: #edf4ff;")
        self.setToolTip(text)

    def _text_rect(self):
        return self.rect().adjusted(10, 0, -10, 0)

    def _text_overflows(self) -> bool:
        text_rect = self._text_rect()
        return self.fontMetrics().horizontalAdvance(self.text()) > max(12, text_rect.width() - 2)

    def _sync_hover_scroll_timer(self) -> None:
        if self.underMouse() and self._text_overflows():
            if not self._hover_scroll_timer.isActive():
                self._hover_scroll_timer.start()
        else:
            self._hover_scroll_timer.stop()
            self._hover_scroll_offset = 0

    def _advance_hover_scroll(self) -> None:
        if not self.underMouse() or not self._text_overflows():
            self._sync_hover_scroll_timer()
            self.update()
            return

        text_rect = self._text_rect()
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        max_offset = max(1, text_width - max(12, text_rect.width() - 2) + 28)
        self._hover_scroll_offset = (self._hover_scroll_offset + 2) % (max_offset + 28)
        self.update()

    def enterEvent(self, event) -> None:
        self._hover_scroll_offset = 0
        self._sync_hover_scroll_timer()
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_scroll_offset = 0
        self._sync_hover_scroll_timer()
        self.update()
        super().leaveEvent(event)

    def resizeEvent(self, event) -> None:
        self._hover_scroll_offset = 0
        self._sync_hover_scroll_timer()
        super().resizeEvent(event)

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

        text_rect = self._text_rect()
        painter.setPen(QColor("#edf4ff"))

        if self.underMouse() and self._text_overflows():
            painter.save()
            painter.setClipRect(text_rect)
            text_width = self.fontMetrics().horizontalAdvance(self.text())
            x = text_rect.left() - self._hover_scroll_offset
            painter.drawText(
                x,
                text_rect.top(),
                text_width + 8,
                text_rect.height(),
                Qt.AlignLeft | Qt.AlignVCenter,
                self.text(),
            )
            painter.restore()
        else:
            text = self.fontMetrics().elidedText(
                self.text(),
                Qt.ElideRight,
                max(12, text_rect.width() - 2),
            )
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, text)


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

        pen = QPen(QColor(62, 216, 255, 96), 1.7)
        pen.setJoinStyle(Qt.RoundJoin)
        inset = pen.widthF() / 2.0
        rect = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)

        painter.setPen(pen)
        painter.setBrush(QColor(8, 12, 19, 245))
        painter.drawRoundedRect(rect, 12, 12)


class MenuSelectorButton(QPushButton):
    currentTextChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[str] = []
        self._current_text = ""
        self._popup: SelectorPopup | None = None
        self._hover_scroll_offset = 0
        self._hover_scroll_timer = QTimer(self)
        self._hover_scroll_timer.setInterval(45)
        self._hover_scroll_timer.timeout.connect(self._advance_hover_scroll)
        self.setMouseTracking(True)
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
        self._hover_scroll_offset = 0
        self._sync_hover_scroll_timer()
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

    def _text_rect(self):
        return self.rect().adjusted(10, 0, -10, 0)

    def _text_overflows(self) -> bool:
        text_rect = self._text_rect()
        return self.fontMetrics().horizontalAdvance(self._current_text) > max(12, text_rect.width() - 2)

    def _sync_hover_scroll_timer(self) -> None:
        if self.underMouse() and self._text_overflows():
            if not self._hover_scroll_timer.isActive():
                self._hover_scroll_timer.start()
        else:
            self._hover_scroll_timer.stop()
            self._hover_scroll_offset = 0

    def _advance_hover_scroll(self) -> None:
        if not self.underMouse() or not self._text_overflows():
            self._sync_hover_scroll_timer()
            self.update()
            return

        text_rect = self._text_rect()
        text_width = self.fontMetrics().horizontalAdvance(self._current_text)
        max_offset = max(1, text_width - max(12, text_rect.width() - 2) + 28)
        self._hover_scroll_offset = (self._hover_scroll_offset + 2) % (max_offset + 28)
        self.update()

    def enterEvent(self, event) -> None:
        self._hover_scroll_offset = 0
        self._sync_hover_scroll_timer()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_scroll_offset = 0
        self._sync_hover_scroll_timer()
        self.update()
        super().leaveEvent(event)

    def resizeEvent(self, event) -> None:
        self._hover_scroll_offset = 0
        self._sync_hover_scroll_timer()
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        text_rect = self._text_rect()

        painter.save()
        painter.setPen(self.palette().buttonText().color())

        if self.underMouse() and self._text_overflows():
            painter.setClipRect(text_rect)
            text_width = self.fontMetrics().horizontalAdvance(self._current_text)
            x = text_rect.left() - self._hover_scroll_offset
            painter.drawText(
                x,
                text_rect.top(),
                text_width + 8,
                text_rect.height(),
                Qt.AlignLeft | Qt.AlignVCenter,
                self._current_text,
            )
        else:
            text = self.fontMetrics().elidedText(
                self._current_text,
                Qt.ElideRight,
                max(12, text_rect.width() - 2),
            )
            painter.drawText(text_rect, Qt.AlignCenter | Qt.AlignVCenter, text)

        painter.restore()


class ChannelVolumeSlider(NoWheelSlider):
    def __init__(self, parent=None):
        super().__init__(Qt.Vertical, parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent; border: none;")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        groove_w = 12.0
        groove_margin = 5.0
        groove_radius = groove_w / 2.0
        handle_d = 15.0
        handle_radius = handle_d / 2.0

        groove = QRectF(
            rect.center().x() - groove_w / 2.0,
            rect.top() + groove_margin,
            groove_w,
            max(1.0, rect.height() - groove_margin * 2.0),
        )

        groove_path = QPainterPath()
        groove_path.addRoundedRect(groove, groove_radius, groove_radius)

        painter.setPen(QPen(QColor(74, 101, 138, 150), 1.25))
        painter.setBrush(QColor(9, 13, 20, 235))
        painter.drawPath(groove_path)

        span = max(1, self.maximum() - self.minimum())
        ratio = (self.value() - self.minimum()) / span
        handle_center_y = groove.bottom() - ratio * groove.height()
        handle_center_y = max(
            rect.top() + handle_radius,
            min(rect.bottom() - handle_radius, handle_center_y),
        )

        fill_top = max(groove.top() + 1.0, min(handle_center_y, groove.bottom() - 0.01))
        fill_h = groove.bottom() - fill_top
        if fill_h > 0.5:
            fill = QRectF(
                groove.left() + 1.0,
                fill_top,
                groove.width() - 2.0,
                fill_h,
            )
            fill_radius = min(fill.width() / 2.0, fill.height() / 2.0)

            painter.save()
            painter.setClipPath(groove_path)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(62, 216, 255, 224))
            painter.drawRoundedRect(fill, fill_radius, fill_radius)
            painter.restore()

        handle_rect = QRectF(
            groove.center().x() - handle_radius,
            handle_center_y - handle_radius,
            handle_d,
            handle_d,
        )
        painter.setPen(QPen(QColor(255, 255, 255, 220), 1.25))
        painter.setBrush(QColor(247, 251, 255, 245))
        painter.drawEllipse(handle_rect)



def _meter_visual_level(value: float) -> float:
    raw = max(0.0, min(1.0, float(value)))
    if raw <= 0.0:
        return 0.0
    boosted = raw ** 0.48
    if boosted < 0.02:
        return 0.0
    return max(0.0, min(1.0, boosted))


class StereoLevelMeterWidget(QWidget):
    def __init__(self, side: str, parent=None):
        super().__init__(parent)
        self.side = side
        self._value = 0.0
        self._segments = 14
        self.setFixedWidth(16)
        self.setMinimumHeight(154)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setToolTip(f"{side.upper()} live meter from backend monitor source.")

    def clear(self) -> None:
        self.set_level(0.0)

    def set_level(self, value: float) -> None:
        visual = _meter_visual_level(value)
        old_lit = int(round(self._value * self._segments))
        new_lit = int(round(visual * self._segments))
        if new_lit == old_lit and abs(visual - self._value) < 0.03:
            return
        self._value = visual
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
            active = i < lit
            if not active:
                color = QColor("#1a2430")
            elif i < 8:
                color = QColor("#48d66b")
            elif i < 11:
                color = QColor("#f2cf5b")
            else:
                color = QColor("#ff6666")
            painter.fillRect(margin, y, width - margin * 2, seg_h, color)
            y -= seg_h + gap

        painter.setPen(QPen(QColor("#35506a")))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


class EditableFrequencyEdit(QLineEdit):
    editStarted = Signal()

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setReadOnly(True)
        self.setAlignment(Qt.AlignCenter)
        self.setObjectName("eqFrequencyPill")
        self.setToolTip("Advanced: double-click to edit this EQ band frequency in Hz.")
        self.setFixedWidth(46)
        self.setMinimumHeight(18)
        self.setMaximumHeight(18)
        self.setTextMargins(0, 0, 0, 0)
        self.setMaxLength(8)

        validator = QDoubleValidator(20.0, 20000.0, 1, self)
        validator.setNotation(QDoubleValidator.StandardNotation)
        self.setValidator(validator)

    def mouseDoubleClickEvent(self, event) -> None:
        self.setReadOnly(False)
        self.selectAll()
        self.setFocus(Qt.MouseFocusReason)
        self.editStarted.emit()
        event.accept()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.setReadOnly(True)


class EditableGainEdit(QLineEdit):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setReadOnly(True)
        self.setAlignment(Qt.AlignCenter)
        self.setObjectName("eqValuePill")
        self.setToolTip("Advanced: double-click to edit this EQ band gain in dB.")
        self.setFixedWidth(40)
        self.setMinimumHeight(18)
        self.setMaximumHeight(18)
        self.setTextMargins(0, 0, 0, 0)
        self.setMaxLength(6)

        validator = QDoubleValidator(-12.0, 12.0, 1, self)
        validator.setNotation(QDoubleValidator.StandardNotation)
        self.setValidator(validator)

    def mouseDoubleClickEvent(self, event) -> None:
        self.setReadOnly(False)
        self.selectAll()
        self.setFocus(Qt.MouseFocusReason)
        event.accept()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.setReadOnly(True)


class EqBandSlider(QWidget):
    frequencyChanged = Signal(float)

    GAIN_SCALE = 2
    MIN_GAIN_DB = -12.0
    MAX_GAIN_DB = 12.0
    MIN_FREQUENCY = 20.0
    MAX_FREQUENCY = 20000.0

    def __init__(self, label: str, value: float = 0.0, parent=None, *, frequency: float | None = None):
        super().__init__(parent)
        self._label_text = label
        self._frequency = self._clamp_frequency(frequency if frequency is not None else self._parse_frequency(label))
        self._value = self._clamp_gain(float(value))

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.value_label = EditableGainEdit(self._format_gain(self._value))
        self.value_label.editingFinished.connect(self._on_gain_edit_finished)
        root.addWidget(self.value_label, alignment=Qt.AlignHCenter)
        root.addSpacing(14)

        self.slider = NoWheelSlider(Qt.Vertical)
        self.slider.setObjectName("eqGainSlider")
        self.slider.setRange(
            int(self.MIN_GAIN_DB * self.GAIN_SCALE),
            int(self.MAX_GAIN_DB * self.GAIN_SCALE),
        )
        self.slider.setSingleStep(1)
        self.slider.setPageStep(2)
        self.slider.setValue(self._gain_to_slider_value(self._value))
        self.slider.setTickPosition(QSlider.NoTicks)
        self.slider.valueChanged.connect(self._on_value_changed)
        self.slider.setFixedHeight(124)
        self.slider.setFixedWidth(46)
        root.addWidget(self.slider, alignment=Qt.AlignHCenter)
        root.addSpacing(4)

        self.frequency_edit = EditableFrequencyEdit(self._format_frequency(self._frequency))
        self.frequency_edit.editingFinished.connect(self._on_frequency_edit_finished)
        root.addWidget(self.frequency_edit, alignment=Qt.AlignHCenter)

    def _clamp_gain(self, value: float) -> float:
        value = max(self.MIN_GAIN_DB, min(self.MAX_GAIN_DB, float(value)))
        return round(value * 2.0) / 2.0

    def _clamp_frequency(self, value: float) -> float:
        return max(self.MIN_FREQUENCY, min(self.MAX_FREQUENCY, float(value)))

    def _parse_frequency(self, text: str) -> float:
        raw = str(text or "").strip().lower().replace("hz", "").replace(" ", "").replace(",", ".")
        multiplier = 1.0
        if raw.endswith("k"):
            multiplier = 1000.0
            raw = raw[:-1]
        try:
            return self._clamp_frequency(float(raw) * multiplier)
        except Exception:
            return 1000.0

    def _format_frequency(self, frequency: float) -> str:
        frequency = self._clamp_frequency(frequency)
        if float(frequency).is_integer():
            return str(int(frequency))
        return f"{frequency:.1f}"

    def _format_gain(self, value: float) -> str:
        return f"{self._clamp_gain(value):+.1f}"

    def _parse_gain(self, text: str) -> float:
        raw = str(text or "").strip().lower().replace("db", "").replace(",", ".")
        try:
            return self._clamp_gain(float(raw))
        except Exception:
            return self._value

    def _gain_to_slider_value(self, value: float) -> int:
        return int(round(self._clamp_gain(value) * self.GAIN_SCALE))

    def _slider_value_to_gain(self, value: int) -> float:
        return self._clamp_gain(float(value) / self.GAIN_SCALE)

    def _on_value_changed(self, value: int) -> None:
        self._value = self._slider_value_to_gain(value)
        if not self.value_label.hasFocus() or self.value_label.isReadOnly():
            self.value_label.setText(self._format_gain(self._value))

    def _on_gain_edit_finished(self) -> None:
        gain = self._parse_gain(self.value_label.text())
        self.value_label.setReadOnly(True)
        self.value_label.setText(self._format_gain(gain))
        self.slider.setValue(self._gain_to_slider_value(gain))

    def _on_frequency_edit_finished(self) -> None:
        old_frequency = self._frequency
        self._frequency = self._parse_frequency(self.frequency_edit.text())
        self.frequency_edit.setReadOnly(True)
        self.frequency_edit.setText(self._format_frequency(self._frequency))
        if abs(self._frequency - old_frequency) > 0.001:
            self.frequencyChanged.emit(self._frequency)

    def value(self) -> float:
        return self._slider_value_to_gain(self.slider.value())

    def setValue(self, value: float) -> None:
        self.slider.setValue(self._gain_to_slider_value(float(value)))

    def frequency(self) -> float:
        return self._frequency

    def setFrequency(self, frequency: float) -> None:
        self._frequency = self._clamp_frequency(frequency)
        self.frequency_edit.setText(self._format_frequency(self._frequency))


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
