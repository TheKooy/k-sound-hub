from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


CHANNELS = [
    ("ALL", "All apps", "🌐", 74, "#48bfff"),
    ("GAME", "Game bus", "🎮", 68, "#7aa8ff"),
    ("MEDIA", "Video / music", "▶", 62, "#44d7ff"),
    ("CHAT", "Discord / voice", "💬", 70, "#55e58b"),
    ("MORE", "Aux bus", "•••", 58, "#f0b84c"),
    ("MICRO", "Mic input", "🎙", 82, "#ff6aa8"),
    ("MIC OUT", "Return monitor", "🎧", 52, "#a778ff"),
]


STYLE = """
QWidget {
    color: #edf5ff;
    font-family: "Inter", "Noto Sans", "DejaVu Sans", sans-serif;
    font-size: 12px;
    background: transparent;
}

QMainWindow {
    background: #05080d;
}

QWidget#root {
    background:
        radial-gradient(circle at 18% 12%, rgba(24, 72, 112, 0.20), transparent 28%),
        radial-gradient(circle at 88% 18%, rgba(41, 91, 140, 0.14), transparent 26%),
        radial-gradient(circle at 45% 90%, rgba(0, 0, 0, 0.45), transparent 38%),
        #05080d;
}

QFrame#shell {
    background: rgba(3, 7, 12, 86);
    border: 1px solid rgba(160, 205, 255, 38);
    border-radius: 24px;
}

QFrame#topBar,
QFrame#glassCard,
QFrame#sidePanel,
QFrame#channelCard,
QFrame#miniCard,
QFrame#infoChip {
    background: rgba(0, 0, 0, 118);
    border: 1px solid rgba(160, 205, 255, 34);
    border-radius: 18px;
}

QFrame#channelCard {
    background: rgba(0, 0, 0, 108);
    border: 1px solid rgba(128, 180, 230, 36);
}

QFrame#channelCard:hover {
    background: rgba(2, 9, 16, 138);
    border: 1px solid rgba(74, 190, 255, 95);
}

QLabel#title {
    font-size: 22px;
    font-weight: 800;
    letter-spacing: 0.4px;
}

QLabel#sectionTitle {
    font-size: 12px;
    font-weight: 800;
    color: #d8e8fb;
    letter-spacing: 1.2px;
}

QLabel#muted {
    color: rgba(205, 222, 240, 155);
    font-size: 10px;
}

QLabel#deviceLabel {
    color: #9edcff;
    font-size: 13px;
    font-weight: 800;
}

QLabel#channelName {
    font-size: 13px;
    font-weight: 900;
    letter-spacing: 2px;
}

QLabel#channelIcon {
    font-size: 24px;
}

QLabel#dbText {
    color: rgba(190, 216, 238, 188);
    font-size: 11px;
    font-weight: 700;
}

QPushButton {
    background: rgba(8, 18, 30, 132);
    border: 1px solid rgba(126, 180, 232, 50);
    border-radius: 10px;
    padding: 6px 10px;
}

QPushButton:hover {
    background: rgba(14, 31, 50, 160);
    border: 1px solid rgba(74, 190, 255, 105);
}

QPushButton#primaryButton {
    color: #eaf7ff;
    background: rgba(37, 142, 226, 118);
    border: 1px solid rgba(110, 210, 255, 135);
}

QComboBox {
    background: rgba(0, 0, 0, 130);
    border: 1px solid rgba(130, 185, 240, 54);
    border-radius: 10px;
    padding: 6px 12px;
    min-height: 28px;
}

QComboBox::drop-down {
    border: none;
    width: 22px;
}

QSlider::groove:vertical {
    background: rgba(0, 0, 0, 165);
    width: 7px;
    border: 1px solid rgba(130, 180, 225, 42);
    border-radius: 4px;
}

QSlider::handle:vertical {
    background: rgba(92, 204, 255, 240);
    border: 1px solid rgba(230, 250, 255, 190);
    width: 16px;
    height: 12px;
    margin: 0px -5px;
    border-radius: 7px;
}

QSlider::sub-page:vertical {
    background: rgba(0, 0, 0, 175);
    border-radius: 4px;
}

QSlider::add-page:vertical {
    background: rgba(80, 190, 255, 118);
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


class ChannelCard(QFrame):
    def __init__(self, name: str, subtitle: str, icon: str, value: int, accent: str):
        super().__init__()
        self.setObjectName("channelCard")
        self.setFixedWidth(126)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(9)

        icon_label = QLabel(icon)
        icon_label.setObjectName("channelIcon")
        icon_label.setAlignment(Qt.AlignCenter)
        root.addWidget(icon_label)

        name_label = QLabel(name)
        name_label.setObjectName("channelName")
        name_label.setAlignment(Qt.AlignCenter)
        root.addWidget(name_label)

        sub = QLabel(subtitle)
        sub.setObjectName("muted")
        sub.setAlignment(Qt.AlignCenter)
        root.addWidget(sub)

        slider = QSlider(Qt.Vertical)
        slider.setRange(0, 100)
        slider.setValue(value)
        slider.setFixedHeight(205)
        root.addWidget(slider, 1, Qt.AlignHCenter)

        db = QLabel(f"{int((value - 100) * 0.32)} dB")
        db.setObjectName("dbText")
        db.setAlignment(Qt.AlignCenter)
        root.addWidget(db)

        mute = QPushButton("Mute")
        root.addWidget(mute)

        route = QLabel("Info hidden")
        route.setObjectName("muted")
        route.setAlignment(Qt.AlignCenter)
        root.addWidget(route)

        dot = QLabel("●")
        dot.setAlignment(Qt.AlignCenter)
        dot.setStyleSheet(f"color: {accent}; font-size: 16px;")
        root.addWidget(dot)


class EqPanel(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("sidePanel")
        self.setFixedWidth(330)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        title = QLabel("EQ")
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        channel_row = QHBoxLayout()
        channel_label = QLabel("Channel")
        channel_label.setObjectName("muted")
        channel_combo = QComboBox()
        channel_combo.addItems(["ALL", "GAME", "MEDIA", "CHAT", "MORE", "MICRO", "MIC OUT"])
        channel_combo.setCurrentText("GAME")
        channel_row.addWidget(channel_label)
        channel_row.addWidget(channel_combo, 1)
        root.addLayout(channel_row)

        preset_row = QHBoxLayout()
        preset_label = QLabel("Preset")
        preset_label.setObjectName("muted")
        preset_combo = QComboBox()
        preset_combo.addItems(["Default", "KSH Neutral", "KSH Game", "KSH Media", "KSH Chat"])
        preset_combo.setCurrentText("KSH Game")
        preset_row.addWidget(preset_label)
        preset_row.addWidget(preset_combo, 1)
        root.addLayout(preset_row)

        eq_card = QFrame()
        eq_card.setObjectName("miniCard")
        eq_layout = QHBoxLayout(eq_card)
        eq_layout.setContentsMargins(14, 12, 14, 12)
        eq_layout.setSpacing(8)

        for label, value in [
            ("32", 45), ("64", 42), ("125", 48), ("250", 50), ("500", 55),
            ("1k", 58), ("2k", 66), ("4k", 68), ("8k", 60), ("16k", 52),
        ]:
            col = QVBoxLayout()
            slider = QSlider(Qt.Vertical)
            slider.setRange(0, 100)
            slider.setValue(value)
            slider.setFixedHeight(140)
            col.addWidget(slider, 1, Qt.AlignHCenter)
            txt = QLabel(label)
            txt.setObjectName("muted")
            txt.setAlignment(Qt.AlignCenter)
            col.addWidget(txt)
            eq_layout.addLayout(col)

        root.addWidget(eq_card)

        wp = QLabel("Wallpaper preview controls")
        wp.setObjectName("sectionTitle")
        root.addWidget(wp)

        for label, value in [("Blur", 18), ("Saturation", 70), ("Dark glass", 62)]:
            line = QHBoxLayout()
            text = QLabel(label)
            text.setObjectName("muted")
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(value)
            line.addWidget(text)
            line.addWidget(slider, 1)
            root.addLayout(line)

        info = QLabel("Routing and advanced details stay behind Info mode.")
        info.setObjectName("muted")
        info.setWordWrap(True)
        root.addWidget(info)

        root.addStretch(1)


class PreviewWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("K-Sounds Hub — Glass UI Preview")
        self.resize(1420, 820)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)

        outer = QVBoxLayout(root)
        outer.setContentsMargins(14, 14, 14, 14)

        shell = QFrame()
        shell.setObjectName("shell")
        outer.addWidget(shell, 1)

        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(18, 18, 18, 18)
        shell_layout.setSpacing(16)

        top = QFrame()
        top.setObjectName("topBar")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(16, 12, 16, 12)
        top_layout.setSpacing(14)

        title = QLabel("K-Sounds Hub")
        title.setObjectName("title")
        top_layout.addWidget(title)

        top_layout.addStretch(1)

        device_box = QFrame()
        device_box.setObjectName("miniCard")
        device_layout = QVBoxLayout(device_box)
        device_layout.setContentsMargins(12, 7, 12, 7)
        device_layout.setSpacing(1)
        device_title = QLabel("Current output device")
        device_title.setObjectName("muted")
        device_label = QLabel("SteelSeries Arctis Nova Pro Wireless")
        device_label.setObjectName("deviceLabel")
        device_layout.addWidget(device_title)
        device_layout.addWidget(device_label)
        top_layout.addWidget(device_box, 0)

        status = QLabel("48 kHz · 512/48000 · UI Preview")
        status.setObjectName("muted")
        top_layout.addWidget(status)

        shell_layout.addWidget(top)

        body = QHBoxLayout()
        body.setSpacing(16)

        main = QVBoxLayout()
        main.setSpacing(14)

        output = QFrame()
        output.setObjectName("glassCard")
        output_layout = QHBoxLayout(output)
        output_layout.setContentsMargins(18, 14, 18, 14)
        output_layout.setSpacing(14)
        output_title = QLabel("OUTPUT / DEVICE")
        output_title.setObjectName("sectionTitle")
        output_layout.addWidget(output_title)
        output_layout.addStretch(1)
        output_layout.addWidget(QLabel("Global trim"))
        trim = QSlider(Qt.Horizontal)
        trim.setRange(0, 100)
        trim.setValue(88)
        trim.setFixedWidth(360)
        output_layout.addWidget(trim)
        dim = QPushButton("Dim")
        dim.setObjectName("primaryButton")
        output_layout.addWidget(dim)
        main.addWidget(output)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        for channel in CHANNELS:
            cards.addWidget(ChannelCard(*channel))
        main.addLayout(cards, 1)

        footer = QFrame()
        footer.setObjectName("glassCard")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(14, 8, 14, 8)
        footer_layout.addWidget(QLabel("Info mode: routing, active apps and advanced details are hidden by default."))
        footer_layout.addStretch(1)
        footer_layout.addWidget(QPushButton("Soundboard"))
        footer_layout.addWidget(QPushButton("Settings"))
        main.addWidget(footer)

        body.addLayout(main, 1)
        body.addWidget(EqPanel())

        shell_layout.addLayout(body, 1)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    win = PreviewWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
