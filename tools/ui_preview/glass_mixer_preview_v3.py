from __future__ import annotations

import sys

from PySide6.QtCore import Qt
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
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


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
    background: #03060a;
}

QWidget#root {
    background:
        radial-gradient(circle at 16% 10%, rgba(32, 92, 142, 0.13), transparent 24%),
        radial-gradient(circle at 90% 18%, rgba(72, 30, 120, 0.10), transparent 24%),
        #03060a;
}

QFrame#shell {
    background: rgba(0, 0, 0, 78);
    border: 1px solid rgba(150, 205, 255, 26);
    border-radius: 20px;
}

QFrame#navRail,
QFrame#channelCard,
QFrame#drawer,
QFrame#topChip {
    background: rgba(0, 0, 0, 116);
    border: 1px solid rgba(145, 198, 255, 30);
    border-radius: 16px;
}

QFrame#channelCard {
    background: rgba(0, 0, 0, 104);
    border: 1px solid rgba(145, 198, 255, 26);
}

QFrame#channelCard:hover {
    background: rgba(5, 13, 22, 142);
    border: 1px solid rgba(86, 197, 255, 86);
}

QFrame#drawer {
    background: rgba(0, 0, 0, 130);
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

QLabel#miniLogo {
    min-width: 34px;
    min-height: 34px;
    max-width: 34px;
    max-height: 34px;
    border-radius: 17px;
    background: rgba(25, 130, 215, 90);
    border: 1px solid rgba(95, 210, 255, 105);
    color: #dff7ff;
    font-size: 17px;
    font-weight: 900;
}

QLabel#channelIcon {
    min-width: 38px;
    min-height: 38px;
    max-width: 38px;
    max-height: 38px;
    border-radius: 19px;
    border: 1px solid rgba(105, 198, 255, 62);
    background: rgba(7, 18, 30, 112);
    color: #86dcff;
    font-size: 18px;
    font-weight: 900;
}

QLabel#channelName {
    font-size: 12px;
    font-weight: 900;
    letter-spacing: 1.8px;
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

QLabel#muted {
    color: rgba(205, 224, 242, 150);
    font-size: 10px;
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

QScrollBar:vertical {
    background: transparent;
    width: 6px;
}

QScrollBar::handle:vertical {
    background: rgba(92, 204, 255, 90);
    border-radius: 3px;
}
"""


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
        self.setMinimumWidth(86)
        self.setMaximumWidth(160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 9, 8, 9)
        root.setSpacing(6)

        icon_label = QLabel(icon)
        icon_label.setObjectName("channelIcon")
        icon_label.setAlignment(Qt.AlignCenter)
        root.addWidget(icon_label, 0, Qt.AlignHCenter)

        name_label = QLabel(name)
        name_label.setObjectName("channelName")
        name_label.setAlignment(Qt.AlignCenter)
        root.addWidget(name_label)

        device_combo = QComboBox()
        device_combo.addItems(devices)
        device_combo.setCurrentIndex(0)
        device_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        root.addWidget(device_combo)

        slider = QSlider(Qt.Vertical)
        slider.setRange(0, 100)
        slider.setValue(value)
        slider.setMinimumHeight(120)
        slider.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        root.addWidget(slider, 1, Qt.AlignHCenter)

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
        self.setFixedWidth(330)

        self.stack = QStackedWidget()
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.addWidget(self.stack)

        self.stack.addWidget(self._eq_page())
        self.stack.addWidget(self._settings_page())
        self.stack.addWidget(self._pads_page())

    def _scroll_page(self, content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def _eq_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        title = QLabel("EQ editor")
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        channel = QComboBox()
        channel.addItems(["ALL", "GAME", "MEDIA", "CHAT", "MORE", "MICRO", "MIC OUT"])
        channel.setCurrentText("GAME")
        root.addWidget(QLabel("Channel"))
        root.addWidget(channel)

        preset = QComboBox()
        preset.addItems(["Default", "KSH Neutral", "KSH Game", "KSH Media", "KSH Chat"])
        preset.setCurrentText("KSH Game")
        root.addWidget(QLabel("Preset"))
        root.addWidget(preset)

        content = QWidget()
        eq_root = QVBoxLayout(content)
        eq_root.setContentsMargins(0, 8, 0, 0)
        eq_root.setSpacing(10)

        bands_card = QFrame()
        bands_card.setObjectName("channelCard")
        bands_layout = QHBoxLayout(bands_card)
        bands_layout.setContentsMargins(10, 10, 10, 10)
        bands_layout.setSpacing(5)

        bands = [("32", 44), ("64", 42), ("125", 48), ("250", 50), ("500", 54),
                 ("1k", 58), ("2k", 66), ("4k", 68), ("8k", 60), ("16k", 52)]

        for label, value in bands:
            col = QVBoxLayout()
            col.setSpacing(4)
            gain = QLabel("+0.0")
            gain.setObjectName("muted")
            gain.setAlignment(Qt.AlignCenter)
            col.addWidget(gain)
            s = QSlider(Qt.Vertical)
            s.setRange(0, 100)
            s.setValue(value)
            s.setMinimumHeight(118)
            s.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            col.addWidget(s, 1, Qt.AlignHCenter)
            t = QLabel(label)
            t.setObjectName("muted")
            t.setAlignment(Qt.AlignCenter)
            col.addWidget(t)
            bands_layout.addLayout(col)

        eq_root.addWidget(bands_card)

        hint = QLabel("Only this EQ section scrolls. Channel and preset menus stay fixed above.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        eq_root.addWidget(hint)
        eq_root.addStretch(1)

        root.addWidget(self._scroll_page(content), 1)

        actions = QHBoxLayout()
        save = QPushButton("Save")
        save.setObjectName("primaryButton")
        cancel = QPushButton("Cancel")
        actions.addWidget(save)
        actions.addWidget(cancel)
        root.addLayout(actions)

        return page

    def _settings_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        title = QLabel("Settings")
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        content = QWidget()
        c = QVBoxLayout(content)
        c.setContentsMargins(0, 0, 0, 0)
        c.setSpacing(12)

        for label, value in [
            ("Background blur", 18),
            ("Background saturation", 72),
            ("Black glass strength", 66),
            ("More info mode", 0),
        ]:
            c.addWidget(QLabel(label))
            s = QSlider(Qt.Horizontal)
            s.setRange(0, 100)
            s.setValue(value)
            c.addWidget(s)

        info = QLabel("When More info is enabled, routing, backend and meter details can appear in compact secondary areas.")
        info.setObjectName("muted")
        info.setWordWrap(True)
        c.addWidget(info)
        c.addStretch(1)

        root.addWidget(self._scroll_page(content), 1)
        return page

    def _pads_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        title = QLabel("Pads hub")
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        content = QWidget()
        c = QVBoxLayout(content)
        c.setContentsMargins(0, 0, 0, 0)
        c.setSpacing(10)

        for name in ["Pad page", "Mobile remote", "Soundboard bridge"]:
            btn = QPushButton(name)
            c.addWidget(btn)

        hint = QLabel("Placeholder for the future PC pads hub and later Android remote UI.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        c.addWidget(hint)
        c.addStretch(1)

        root.addWidget(self._scroll_page(content), 1)
        return page

    def show_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)


class PreviewWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("K-Sounds Hub — Glass UI Preview V3")
        self.resize(1320, 620)
        self.setMinimumSize(900, 520)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)

        outer = QVBoxLayout(root)
        outer.setContentsMargins(10, 10, 10, 10)

        shell = QFrame()
        shell.setObjectName("shell")
        outer.addWidget(shell, 1)

        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(12, 12, 12, 12)
        shell_layout.setSpacing(10)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)

        logo = QLabel("K")
        logo.setObjectName("miniLogo")
        logo.setAlignment(Qt.AlignCenter)
        top.addWidget(logo)
        top.addStretch(1)

        chip = QFrame()
        chip.setObjectName("topChip")
        chip_layout = QHBoxLayout(chip)
        chip_layout.setContentsMargins(10, 5, 10, 5)
        chip_layout.addWidget(QLabel("UI Preview V3"))
        top.addWidget(chip)

        shell_layout.addLayout(top)

        body = QHBoxLayout()
        body.setSpacing(10)

        nav = QFrame()
        nav.setObjectName("navRail")
        nav.setFixedWidth(70)
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

        body.addWidget(nav)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(9)

        for channel in CHANNELS:
            cards_row.addWidget(ChannelCard(*channel))

        body.addLayout(cards_row, 1)

        self.drawer = Drawer()
        self.drawer.setVisible(False)
        body.addWidget(self.drawer)

        shell_layout.addLayout(body, 1)

        self.nav_group.idClicked.connect(self._on_nav_clicked)

    def _on_nav_clicked(self, idx: int) -> None:
        if idx == 0:
            self.drawer.setVisible(False)
            return

        self.drawer.setVisible(True)
        self.drawer.show_page(idx - 1)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    window = PreviewWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
