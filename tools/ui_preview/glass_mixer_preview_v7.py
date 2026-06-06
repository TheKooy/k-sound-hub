from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QRectF, Qt, QEvent
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QScrollArea,
    QSlider,
    QStackedLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


ROOT = Path(__file__).resolve().parents[2]
APP_ICON = ROOT / "src/ksound_hub/assets/app_icon.png"
APP_BG = ROOT / "src/ksound_hub/assets/backgrounds/ksound_hub_wallpaper_4k_blurfill_3840x2160.png"

CHANNELS = [
    ("ALL", "A", ["Arctis Nova Pro", "USB / SPDIF", "System default"], 76),
    ("GAME", "G", ["Arctis Nova Pro", "USB / SPDIF", "System default"], 72),
    ("MEDIA", "M", ["USB / SPDIF", "Arctis Nova Pro", "System default"], 64),
    ("CHAT", "C", ["Arctis Nova Pro", "USB / SPDIF", "System default"], 70),
    ("MORE", "+", ["System default", "Arctis Nova Pro", "USB / SPDIF"], 58),
    ("MICRO", "µ", ["RØDE NT-USB", "Arctis Mic", "System default"], 84),
    ("MIC OUT", "R", ["Arctis monitor", "USB / SPDIF", "System default"], 52),
]


STYLE = """
QWidget {
    color: #edf5ff;
    background: transparent;
    font-family: "Inter", "Noto Sans", "DejaVu Sans", sans-serif;
    font-size: 12px;
}

QMainWindow {
    background: #02050a;
}

QWidget#root,
QWidget#foreground,
QWidget#contentHost {
    background: transparent;
}

QLabel#backgroundImage {
    background: #02050a;
}

QFrame#backgroundTint {
    background: rgba(0, 0, 0, 154);
    border: none;
}

QFrame#titleBar {
    background: rgba(0, 0, 0, 126);
    border: none;
}

QFrame#contentFrame {
    background: rgba(0, 0, 0, 52);
    border: none;
}

QFrame#navRail,
QFrame#channelCard,
QFrame#drawer {
    background: rgba(0, 0, 0, 116);
    border: 1px solid rgba(145, 198, 255, 28);
    border-radius: 15px;
}

QFrame#channelCard {
    background: rgba(0, 0, 0, 102);
}

QFrame#channelCard:hover {
    background: rgba(5, 13, 22, 142);
    border: 1px solid rgba(86, 197, 255, 82);
}

QFrame#drawer {
    background: rgba(0, 0, 0, 134);
}

QPushButton#windowButton {
    min-width: 30px;
    max-width: 30px;
    min-height: 24px;
    max-height: 24px;
    padding: 0px;
    border-radius: 6px;
    background: transparent;
    border: 1px solid transparent;
    color: rgba(226, 242, 255, 190);
}

QPushButton#windowButton:hover {
    background: rgba(30, 56, 84, 150);
    border: 1px solid rgba(120, 205, 255, 82);
}

QPushButton#closeButton {
    min-width: 30px;
    max-width: 30px;
    min-height: 24px;
    max-height: 24px;
    padding: 0px;
    border-radius: 6px;
    background: transparent;
    border: 1px solid transparent;
    color: rgba(255, 220, 228, 205);
}

QPushButton#closeButton:hover {
    background: rgba(190, 38, 58, 170);
    border: 1px solid rgba(255, 110, 128, 120);
}

QPushButton#navButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 12px;
    padding: 7px 2px;
    color: rgba(218, 236, 250, 170);
    font-size: 10px;
}

QPushButton#navButton:checked {
    background: rgba(20, 106, 176, 82);
    border: 1px solid rgba(96, 206, 255, 102);
    color: #f2fbff;
}

QPushButton#navButton:hover {
    background: rgba(18, 40, 62, 115);
    border: 1px solid rgba(96, 206, 255, 70);
}

QLabel#appIcon {
    min-width: 22px;
    min-height: 22px;
    max-width: 22px;
    max-height: 22px;
    border-radius: 11px;
    background: rgba(25, 130, 215, 100);
    border: 1px solid rgba(95, 210, 255, 105);
    color: #dff7ff;
    font-size: 12px;
    font-weight: 900;
}

QLabel#titleText {
    color: rgba(222, 238, 250, 190);
    font-size: 11px;
    font-weight: 700;
}

QLabel#muted {
    color: rgba(205, 224, 242, 150);
    font-size: 10px;
}

QLabel#channelIcon {
    min-width: 36px;
    min-height: 36px;
    max-width: 36px;
    max-height: 36px;
    border-radius: 18px;
    border: 1px solid rgba(105, 198, 255, 62);
    background: rgba(7, 18, 30, 112);
    color: #86dcff;
    font-size: 17px;
    font-weight: 900;
}

QLabel#channelName {
    font-size: 12px;
    font-weight: 900;
    letter-spacing: 1.7px;
}

QLabel#volumeValue {
    color: rgba(225, 242, 255, 212);
    font-size: 11px;
    font-weight: 850;
}

QLabel#sectionTitle {
    color: #e8f5ff;
    font-size: 13px;
    font-weight: 900;
    letter-spacing: 1.2px;
}

QPushButton {
    background: rgba(8, 17, 28, 128);
    border: 1px solid rgba(132, 188, 240, 44);
    border-radius: 10px;
    padding: 5px 9px;
}

QPushButton:hover {
    background: rgba(14, 32, 50, 150);
    border: 1px solid rgba(92, 205, 255, 95);
}

QPushButton#muteButton {
    padding: 4px 5px;
    font-size: 10px;
}

QPushButton#primaryButton {
    background: rgba(35, 142, 226, 112);
    border: 1px solid rgba(112, 212, 255, 132);
}

QComboBox {
    background: rgba(0, 0, 0, 132);
    border: 1px solid rgba(130, 185, 240, 50);
    border-radius: 9px;
    padding: 4px 8px;
    min-height: 24px;
    font-size: 10px;
}

QComboBox::drop-down {
    border: none;
    width: 18px;
}

QSlider::groove:vertical {
    background: rgba(0, 0, 0, 172);
    width: 7px;
    border: 1px solid rgba(130, 180, 225, 36);
    border-radius: 4px;
}

QSlider::handle:vertical {
    background: rgba(92, 204, 255, 235);
    border: 1px solid rgba(230, 250, 255, 176);
    width: 15px;
    height: 12px;
    margin: 0px -5px;
    border-radius: 7px;
}

QSlider::sub-page:vertical {
    background: rgba(0, 0, 0, 180);
    border-radius: 4px;
}

QSlider::add-page:vertical {
    background: rgba(76, 188, 255, 128);
    border-radius: 4px;
}

QSlider::groove:horizontal {
    background: rgba(0, 0, 0, 155);
    height: 8px;
    border: 1px solid rgba(130, 180, 225, 40);
    border-radius: 5px;
}

QSlider::handle:horizontal {
    background: rgba(92, 204, 255, 235);
    border: 1px solid rgba(230, 250, 255, 170);
    width: 14px;
    margin: -4px 0px;
    border-radius: 7px;
}

QSlider::sub-page:horizontal {
    background: rgba(82, 190, 255, 120);
    border-radius: 5px;
}

QScrollArea {
    border: none;
    background: transparent;
}

QScrollArea#drawerScroll {
    border: none;
    background: transparent;
}

QScrollBar:vertical,
QScrollBar:horizontal {
    background: transparent;
    width: 6px;
    height: 6px;
}

QScrollBar::handle:vertical,
QScrollBar::handle:horizontal {
    background: rgba(92, 204, 255, 70);
    border-radius: 3px;
}
"""


class NoWheelComboBox(QComboBox):
    def wheelEvent(self, event) -> None:
        event.ignore()


class NoWheelSlider(QSlider):
    def wheelEvent(self, event) -> None:
        event.ignore()


class LevelMeter(QWidget):
    def __init__(self, level: float, parent=None):
        super().__init__(parent)
        self.level = max(0.0, min(1.0, float(level)))
        self.setFixedWidth(7)
        self.setMinimumHeight(92)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        painter.setPen(QColor(90, 140, 180, 42))
        painter.setBrush(QColor(0, 0, 0, 148))
        painter.drawRoundedRect(rect, 3.0, 3.0)

        fill_h = max(2.0, rect.height() * self.level)
        fill = QRectF(rect.left(), rect.bottom() - fill_h, rect.width(), fill_h)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(74, 188, 255, 122))
        painter.drawRoundedRect(fill, 3.0, 3.0)

        peak_h = max(rect.top(), fill.top())
        painter.setBrush(QColor(105, 220, 255, 210))
        painter.drawRoundedRect(QRectF(rect.left() - 1.0, peak_h, rect.width() + 2.0, 3.0), 2.0, 2.0)


class TitleBar(QFrame):
    def __init__(self, window: QMainWindow):
        super().__init__()
        self.window = window
        self.setObjectName("titleBar")
        self.setFixedHeight(34)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        icon = QLabel("K")
        icon.setObjectName("appIcon")
        icon.setAlignment(Qt.AlignCenter)
        if APP_ICON.is_file():
            pixmap = QPixmap(str(APP_ICON))
            if not pixmap.isNull():
                icon.setPixmap(pixmap.scaled(18, 18, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(icon)

        title = QLabel("K-Sounds Hub")
        title.setObjectName("titleText")
        layout.addWidget(title)

        layout.addStretch(1)

        min_btn = QPushButton("—")
        min_btn.setObjectName("windowButton")
        min_btn.clicked.connect(window.showMinimized)
        layout.addWidget(min_btn)

        max_btn = QPushButton("□")
        max_btn.setObjectName("windowButton")
        max_btn.clicked.connect(self._toggle_maximized)
        layout.addWidget(max_btn)

        close_btn = QPushButton("×")
        close_btn.setObjectName("closeButton")
        close_btn.clicked.connect(window.close)
        layout.addWidget(close_btn)

    def _toggle_maximized(self) -> None:
        if self.window.isMaximized():
            self.window.showNormal()
        else:
            self.window.showMaximized()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            handle = self.window.windowHandle()
            if handle is not None:
                try:
                    if handle.startSystemMove():
                        event.accept()
                        return
                except Exception:
                    pass
            event.accept()


class NavButton(QPushButton):
    def __init__(self, icon: str, label: str):
        super().__init__(f"{icon}\n{label}")
        self.setObjectName("navButton")
        self.setCheckable(True)
        self.setMinimumHeight(58)


class ChannelCard(QFrame):
    def __init__(self, name: str, icon: str, devices: list[str], value: int):
        super().__init__()
        self.setObjectName("channelCard")
        self.setMinimumWidth(74)
        self.setMaximumWidth(160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(5)

        icon_label = QLabel(icon)
        icon_label.setObjectName("channelIcon")
        icon_label.setAlignment(Qt.AlignCenter)
        root.addWidget(icon_label, 0, Qt.AlignHCenter)

        name_label = QLabel(name)
        name_label.setObjectName("channelName")
        name_label.setAlignment(Qt.AlignCenter)
        root.addWidget(name_label)

        device_combo = NoWheelComboBox()
        device_combo.addItems(devices)
        device_combo.setCurrentIndex(0)
        device_combo.setMinimumWidth(0)
        device_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        root.addWidget(device_combo)

        meter_row = QHBoxLayout()
        meter_row.setContentsMargins(0, 0, 0, 0)
        meter_row.setSpacing(6)
        meter_row.addStretch(1)

        left_meter = LevelMeter(min(1.0, value / 100.0 * 0.82))
        right_meter = LevelMeter(min(1.0, value / 100.0 * 0.68 + 0.08))
        meter_row.addWidget(left_meter, 0, Qt.AlignBottom)

        slider = NoWheelSlider(Qt.Vertical)
        slider.setRange(0, 100)
        slider.setValue(value)
        slider.setMinimumHeight(92)
        slider.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        meter_row.addWidget(slider, 0, Qt.AlignHCenter)

        meter_row.addWidget(right_meter, 0, Qt.AlignBottom)
        meter_row.addStretch(1)

        root.addLayout(meter_row, 1)

        value_label = QLabel(f"{value}%")
        value_label.setObjectName("volumeValue")
        value_label.setAlignment(Qt.AlignCenter)
        root.addWidget(value_label)

        mute = QPushButton("Mute")
        mute.setObjectName("muteButton")
        root.addWidget(mute)


class Drawer(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("drawer")
        self.setFixedWidth(358)

        self.stack = QStackedWidget()
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.addWidget(self.stack)

        self.stack.addWidget(self._eq_page())
        self.stack.addWidget(self._settings_page())
        self.stack.addWidget(self._pads_page())

    def _make_scroll_page(self, content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("drawerScroll")
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def _eq_page(self) -> QWidget:
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        title = QLabel("EQ editor")
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        root.addWidget(QLabel("Channel"))
        channel = NoWheelComboBox()
        channel.addItems(["ALL", "GAME", "MEDIA", "CHAT", "MORE", "MICRO", "MIC OUT"])
        channel.setCurrentText("GAME")
        root.addWidget(channel)

        root.addWidget(QLabel("Preset"))
        preset = NoWheelComboBox()
        preset.addItems(["Default", "KSH Neutral", "KSH Game", "KSH Media", "KSH Chat"])
        preset.setCurrentText("KSH Chat")
        root.addWidget(preset)

        bands_card = QFrame()
        bands_card.setObjectName("channelCard")
        bands_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        bands_layout = QHBoxLayout(bands_card)
        bands_layout.setContentsMargins(8, 8, 8, 8)
        bands_layout.setSpacing(4)

        bands = [("32", 44), ("64", 42), ("125", 48), ("250", 50), ("500", 54),
                 ("1k", 58), ("2k", 66), ("4k", 68), ("8k", 60), ("16k", 52)]

        for label, value in bands:
            col = QVBoxLayout()
            col.setSpacing(3)

            gain = QLabel("+0.0")
            gain.setObjectName("muted")
            gain.setAlignment(Qt.AlignCenter)
            col.addWidget(gain)

            slider = NoWheelSlider(Qt.Vertical)
            slider.setRange(0, 100)
            slider.setValue(value)
            slider.setMinimumHeight(112)
            slider.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            col.addWidget(slider, 1, Qt.AlignHCenter)

            freq = QLabel(label)
            freq.setObjectName("muted")
            freq.setAlignment(Qt.AlignCenter)
            col.addWidget(freq)

            bands_layout.addLayout(col)

        root.addWidget(bands_card, 1)

        actions = QHBoxLayout()
        save = QPushButton("Save")
        save.setObjectName("primaryButton")
        cancel = QPushButton("Cancel")
        actions.addWidget(save)
        actions.addWidget(cancel)
        root.addLayout(actions)

        return self._make_scroll_page(content)

    def _settings_page(self) -> QWidget:
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        title = QLabel("Settings")
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        for label, value in [
            ("Background blur", 18),
            ("Background saturation", 72),
            ("Black glass strength", 66),
            ("More info mode", 0),
        ]:
            root.addWidget(QLabel(label))
            slider = NoWheelSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(value)
            root.addWidget(slider)

        root.addStretch(1)
        return self._make_scroll_page(content)

    def _pads_page(self) -> QWidget:
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        title = QLabel("Pads hub")
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        for name in ["Pad page", "Mobile remote", "Soundboard bridge"]:
            root.addWidget(QPushButton(name))

        root.addStretch(1)
        return self._make_scroll_page(content)

    def show_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)


class PreviewWindow(QMainWindow):
    resize_margin = 9

    def __init__(self):
        super().__init__()
        self.setWindowTitle("K-Sounds Hub")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.resize(1320, 560)
        self.setMinimumSize(860, 430)

        if APP_ICON.is_file():
            self.setWindowIcon(QIcon(str(APP_ICON)))

        self._background_source = QPixmap(str(APP_BG)) if APP_BG.is_file() else QPixmap()

        central = QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)

        stack = QStackedLayout(central)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setStackingMode(QStackedLayout.StackAll)

        self.background_label = QLabel()
        self.background_label.setObjectName("backgroundImage")
        self.background_label.setAlignment(Qt.AlignCenter)
        self.background_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        tint = QFrame()
        tint.setObjectName("backgroundTint")
        tint.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        foreground = QWidget()
        foreground.setObjectName("foreground")

        stack.addWidget(self.background_label)
        stack.addWidget(tint)
        stack.addWidget(foreground)

        outer = QVBoxLayout(foreground)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.title_bar = TitleBar(self)
        outer.addWidget(self.title_bar)

        content = QFrame()
        content.setObjectName("contentFrame")
        outer.addWidget(content, 1)

        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(8)

        nav = QFrame()
        nav.setObjectName("navRail")
        nav.setFixedWidth(68)
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(6, 7, 6, 7)
        nav_layout.setSpacing(7)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        nav_buttons = [
            NavButton("▥", "Mixer"),
            NavButton("≋", "EQ"),
            NavButton("⚙", "Settings"),
            NavButton("▦", "Pads"),
        ]

        for idx, button in enumerate(nav_buttons):
            self.nav_group.addButton(button, idx)
            nav_layout.addWidget(button)

        nav_layout.addStretch(1)
        nav_buttons[0].setChecked(True)

        content_layout.addWidget(nav)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(8)
        cards_row.setContentsMargins(0, 0, 0, 0)

        for channel in CHANNELS:
            cards_row.addWidget(ChannelCard(*channel))

        content_layout.addLayout(cards_row, 1)

        self.drawer = Drawer()
        self.drawer.setVisible(False)
        content_layout.addWidget(self.drawer)

        self.nav_group.idClicked.connect(self._on_nav_clicked)

        self._install_resize_event_filter()
        self._refresh_background()

    def _install_resize_event_filter(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        def enable_tracking(widget: QWidget) -> None:
            widget.setMouseTracking(True)
            for child in widget.findChildren(QWidget):
                child.setMouseTracking(True)

        enable_tracking(self)

    def eventFilter(self, obj, event) -> bool:
        if not isinstance(obj, QWidget):
            return super().eventFilter(obj, event)

        owner_attr = getattr(obj, "window", None)
        try:
            owner = owner_attr() if callable(owner_attr) else owner_attr
        except TypeError:
            owner = None

        if owner is not self:
            return super().eventFilter(obj, event)

        if self.isMaximized():
            return super().eventFilter(obj, event)

        if event.type() == QEvent.MouseMove:
            edges = self._edges_for_global_pos(event.globalPosition().toPoint())
            self.setCursor(self._cursor_for_edges(edges))
            return super().eventFilter(obj, event)

        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            edges = self._edges_for_global_pos(event.globalPosition().toPoint())
            if edges:
                handle = self.windowHandle()
                edge_flags = Qt.Edges()
                if "left" in edges:
                    edge_flags |= Qt.LeftEdge
                if "right" in edges:
                    edge_flags |= Qt.RightEdge
                if "top" in edges:
                    edge_flags |= Qt.TopEdge
                if "bottom" in edges:
                    edge_flags |= Qt.BottomEdge

                if handle is not None:
                    try:
                        if handle.startSystemResize(edge_flags):
                            event.accept()
                            return True
                    except Exception:
                        pass

        return super().eventFilter(obj, event)

    def _on_nav_clicked(self, idx: int) -> None:
        if idx == 0:
            self.drawer.setVisible(False)
            return
        self.drawer.setVisible(True)
        self.drawer.show_page(idx - 1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_background()

    def _refresh_background(self) -> None:
        if self._background_source.isNull():
            self.background_label.clear()
            return

        size = self.background_label.size()
        if size.width() <= 1 or size.height() <= 1:
            return

        scaled = self._background_source.scaled(
            size,
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        self.background_label.setPixmap(scaled)

    def _edges_for_global_pos(self, global_pos: QPoint) -> set[str]:
        local = self.mapFromGlobal(global_pos)
        margin = self.resize_margin
        rect = self.rect()
        edges: set[str] = set()

        if local.x() <= margin:
            edges.add("left")
        elif local.x() >= rect.width() - margin:
            edges.add("right")

        if local.y() <= margin:
            edges.add("top")
        elif local.y() >= rect.height() - margin:
            edges.add("bottom")

        return edges

    def _cursor_for_edges(self, edges: set[str]) -> Qt.CursorShape:
        if {"left", "top"}.issubset(edges) or {"right", "bottom"}.issubset(edges):
            return Qt.SizeFDiagCursor
        if {"right", "top"}.issubset(edges) or {"left", "bottom"}.issubset(edges):
            return Qt.SizeBDiagCursor
        if "left" in edges or "right" in edges:
            return Qt.SizeHorCursor
        if "top" in edges or "bottom" in edges:
            return Qt.SizeVerCursor
        return Qt.ArrowCursor


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    window = PreviewWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
