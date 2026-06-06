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
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


CHANNELS = [
    ("ALL", "Arctis Nova Pro", "A", 76),
    ("GAME", "Arctis Nova Pro", "G", 72),
    ("MEDIA", "USB / SPDIF", "M", 64),
    ("CHAT", "Arctis Nova Pro", "C", 70),
    ("MORE", "System default", "+", 58),
    ("MICRO", "RØDE NT-USB", "µ", 84),
    ("MIC OUT", "Arctis monitor", "R", 52),
]


STYLE = """
QWidget {
    color: #edf5ff;
    background: transparent;
    font-family: "Inter", "Noto Sans", "DejaVu Sans", sans-serif;
    font-size: 12px;
}

QMainWindow {
    background: #04070c;
}

QWidget#root {
    background: #04070c;
}

QFrame#appShell {
    background: rgba(0, 0, 0, 78);
    border: 1px solid rgba(148, 200, 255, 30);
    border-radius: 22px;
}

QFrame#topBar,
QFrame#channelCard,
QFrame#drawer,
QFrame#footerBar {
    background: rgba(0, 0, 0, 118);
    border: 1px solid rgba(142, 198, 255, 34);
    border-radius: 18px;
}

QFrame#channelCard {
    background: rgba(0, 0, 0, 106);
    border: 1px solid rgba(145, 196, 255, 30);
}

QFrame#channelCard:hover {
    background: rgba(3, 12, 22, 134);
    border: 1px solid rgba(88, 195, 255, 90);
}

QFrame#navRail {
    background: rgba(0, 0, 0, 128);
    border: 1px solid rgba(145, 196, 255, 28);
    border-radius: 18px;
}

QPushButton#navButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 13px;
    padding: 8px 4px;
    color: rgba(220, 235, 250, 178);
    font-size: 10px;
}

QPushButton#navButton:checked {
    background: rgba(22, 112, 178, 82);
    border: 1px solid rgba(98, 205, 255, 105);
    color: #edf8ff;
}

QPushButton#navButton:hover {
    background: rgba(20, 42, 64, 120);
    border: 1px solid rgba(98, 205, 255, 70);
}

QLabel#appTitle {
    font-size: 22px;
    font-weight: 850;
    letter-spacing: 0.3px;
}

QLabel#windowHint,
QLabel#muted {
    color: rgba(207, 225, 244, 150);
    font-size: 10px;
}

QLabel#channelIcon {
    min-width: 44px;
    min-height: 44px;
    max-width: 44px;
    max-height: 44px;
    border-radius: 22px;
    border: 1px solid rgba(105, 198, 255, 70);
    background: rgba(8, 18, 30, 120);
    color: #86dcff;
    font-size: 19px;
    font-weight: 900;
}

QLabel#channelName {
    font-size: 13px;
    font-weight: 900;
    letter-spacing: 1.8px;
}

QLabel#deviceName {
    color: rgba(175, 208, 235, 172);
    font-size: 9px;
    font-weight: 700;
}

QLabel#volumeValue {
    color: rgba(220, 240, 255, 205);
    font-size: 11px;
    font-weight: 800;
}

QLabel#sectionTitle {
    color: #e8f5ff;
    font-size: 13px;
    font-weight: 900;
    letter-spacing: 1.4px;
}

QPushButton {
    background: rgba(8, 17, 28, 132);
    border: 1px solid rgba(132, 188, 240, 48);
    border-radius: 10px;
    padding: 6px 10px;
}

QPushButton:hover {
    background: rgba(14, 32, 50, 150);
    border: 1px solid rgba(92, 205, 255, 95);
}

QPushButton#muteButton {
    padding: 5px 6px;
    font-size: 10px;
}

QPushButton#primaryButton {
    background: rgba(35, 142, 226, 112);
    border: 1px solid rgba(112, 212, 255, 132);
}

QComboBox {
    background: rgba(0, 0, 0, 135);
    border: 1px solid rgba(130, 185, 240, 54);
    border-radius: 10px;
    padding: 6px 10px;
    min-height: 26px;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QSlider::groove:vertical {
    background: rgba(0, 0, 0, 170);
    width: 7px;
    border: 1px solid rgba(130, 180, 225, 38);
    border-radius: 4px;
}

QSlider::handle:vertical {
    background: rgba(92, 204, 255, 235);
    border: 1px solid rgba(230, 250, 255, 180);
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
"""


class NavButton(QPushButton):
    def __init__(self, icon: str, label: str):
        super().__init__(f"{icon}\n{label}")
        self.setObjectName("navButton")
        self.setCheckable(True)
        self.setMinimumHeight(62)


class ChannelCard(QFrame):
    def __init__(self, name: str, device: str, icon: str, value: int):
        super().__init__()
        self.setObjectName("channelCard")
        self.setMinimumWidth(96)
        self.setMaximumWidth(160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 11, 10, 10)
        root.setSpacing(7)

        icon_label = QLabel(icon)
        icon_label.setObjectName("channelIcon")
        icon_label.setAlignment(Qt.AlignCenter)
        root.addWidget(icon_label, 0, Qt.AlignHCenter)

        name_label = QLabel(name)
        name_label.setObjectName("channelName")
        name_label.setAlignment(Qt.AlignCenter)
        root.addWidget(name_label)

        device_label = QLabel(device)
        device_label.setObjectName("deviceName")
        device_label.setAlignment(Qt.AlignCenter)
        device_label.setWordWrap(False)
        root.addWidget(device_label)

        slider = QSlider(Qt.Vertical)
        slider.setRange(0, 100)
        slider.setValue(value)
        slider.setMinimumHeight(190)
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
        self.setFixedWidth(338)

        self.stack = QStackedWidget()
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.addWidget(self.stack)

        self.stack.addWidget(self._empty_page())
        self.stack.addWidget(self._eq_page())
        self.stack.addWidget(self._settings_page())
        self.stack.addWidget(self._soundboard_page())

    def _empty_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        msg = QLabel("Mixer view")
        msg.setObjectName("sectionTitle")
        msg.setAlignment(Qt.AlignCenter)
        layout.addWidget(msg)
        hint = QLabel("Side panels stay hidden until needed.")
        hint.setObjectName("muted")
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _eq_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        title = QLabel("EQ editor")
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        hint = QLabel("Appears only while editing a preset. Channel and preset are explicit.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

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

        eq_card = QFrame()
        eq_card.setObjectName("channelCard")
        eq_layout = QHBoxLayout(eq_card)
        eq_layout.setContentsMargins(12, 10, 12, 10)
        eq_layout.setSpacing(6)

        bands = [("32", 44), ("64", 42), ("125", 48), ("250", 50), ("500", 54),
                 ("1k", 58), ("2k", 66), ("4k", 68), ("8k", 60), ("16k", 52)]

        for label, value in bands:
            col = QVBoxLayout()
            col.setSpacing(4)
            s = QSlider(Qt.Vertical)
            s.setRange(0, 100)
            s.setValue(value)
            s.setFixedHeight(126)
            col.addWidget(s, 1, Qt.AlignHCenter)
            t = QLabel(label)
            t.setObjectName("muted")
            t.setAlignment(Qt.AlignCenter)
            col.addWidget(t)
            eq_layout.addLayout(col)

        root.addWidget(eq_card)

        row = QHBoxLayout()
        save = QPushButton("Save")
        save.setObjectName("primaryButton")
        cancel = QPushButton("Cancel")
        row.addWidget(save)
        row.addWidget(cancel)
        root.addLayout(row)

        root.addStretch(1)
        return page

    def _settings_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        title = QLabel("Visual settings")
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        hint = QLabel("Wallpaper controls live here, separate from EQ.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        for label, value in [("Background blur", 18), ("Saturation", 72), ("Black glass strength", 66)]:
            root.addWidget(QLabel(label))
            s = QSlider(Qt.Horizontal)
            s.setRange(0, 100)
            s.setValue(value)
            root.addWidget(s)

        root.addStretch(1)
        return page

    def _soundboard_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        title = QLabel("Soundboard")
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        hint = QLabel("Placeholder entry point. Real soundboard remains a separate window for now.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        open_btn = QPushButton("Open soundboard")
        open_btn.setObjectName("primaryButton")
        root.addWidget(open_btn)

        root.addStretch(1)
        return page

    def show_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)


class PreviewWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("K-Sounds Hub — Glass UI Preview V2")
        self.resize(1320, 720)
        self.setMinimumSize(1020, 620)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)

        outer = QVBoxLayout(root)
        outer.setContentsMargins(12, 12, 12, 12)

        shell = QFrame()
        shell.setObjectName("appShell")
        outer.addWidget(shell, 1)

        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(14, 14, 14, 14)
        shell_layout.setSpacing(12)

        top = QFrame()
        top.setObjectName("topBar")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(15, 10, 15, 10)
        top_layout.setSpacing(12)

        title = QLabel("K-Sounds Hub")
        title.setObjectName("appTitle")
        top_layout.addWidget(title)

        top_layout.addStretch(1)

        hint = QLabel("Preview V2 · mixer-first · all channels visible")
        hint.setObjectName("windowHint")
        top_layout.addWidget(hint)

        shell_layout.addWidget(top)

        body = QHBoxLayout()
        body.setSpacing(12)

        nav = QFrame()
        nav.setObjectName("navRail")
        nav.setFixedWidth(74)
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(7, 8, 7, 8)
        nav_layout.setSpacing(8)

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

        mixer_area = QVBoxLayout()
        mixer_area.setSpacing(10)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(10)

        for channel in CHANNELS:
            cards_row.addWidget(ChannelCard(*channel))

        mixer_area.addLayout(cards_row, 1)

        footer = QFrame()
        footer.setObjectName("footerBar")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(12, 8, 12, 8)
        footer_layout.setSpacing(10)

        footer_layout.addWidget(QLabel("48 kHz"))
        footer_layout.addWidget(QLabel("512/48000"))
        footer_layout.addStretch(1)
        info = QLabel("Routing and app details hidden by default. Use side panels when needed.")
        info.setObjectName("muted")
        footer_layout.addWidget(info)

        mixer_area.addWidget(footer)
        body.addLayout(mixer_area, 1)

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
        self.drawer.show_page(idx)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    window = PreviewWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
