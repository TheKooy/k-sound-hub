from __future__ import annotations

import json
import socket
import sys

from PySide6.QtCore import QLockFile
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication

from .config import APP_ICON_PATH, APP_NAME, IPC_SOCKET_PATH, ORG_DOMAIN, ORG_NAME, RUNTIME_DIR
from .settings_store import SettingsStore
from .ui.main_window import MainWindow

STYLE_SHEET = """
QWidget {
    background: #0d1118;
    color: #edf4ff;
    font-size: 12px;
}
QMainWindow, QDialog {
    background: #0d1118;
}
QWidget#centralStack,
QWidget#mainRoot,
QWidget#columnsHost,
QWidget#backgroundBase,
QWidget#scrollViewport,
QLabel#wallpaperLabel,
QFrame#wallpaperTint {
    background: transparent;
}
QLabel#pageTitle {
    font-size: 20px;
    font-weight: 800;
}
QLabel#mutedLabel {
    color: #9eabc2;
    font-size: 10px;
}
QFrame#channelCard {
    background: rgba(16, 22, 34, 238);
    border: 1px solid rgba(62, 216, 255, 68);
    border-radius: 18px;
}
QFrame#channelCard:hover {
    border: 1px solid rgba(255, 92, 199, 84);
}
QFrame#sectionCard,
QFrame#footerBar,
QFrame#appRuleRow {
    background: rgba(11, 16, 26, 228);
    border: 1px solid rgba(74, 101, 138, 108);
    border-radius: 12px;
}
QFrame#appRuleRow:hover {
    background: rgba(17, 24, 38, 235);
    border: 1px solid rgba(255, 92, 199, 84);
}
QPushButton {
    background: rgba(21, 31, 48, 235);
    border: 1px solid rgba(62, 216, 255, 76);
    border-radius: 10px;
    padding: 7px 10px;
}
QPushButton:hover {
    background: rgba(28, 40, 61, 240);
    border: 1px solid rgba(255, 92, 199, 84);
}
QPushButton:pressed {
    background: rgba(18, 28, 42, 245);
}
QPushButton#tinyButton,
QPushButton#muteButton,
QPushButton#sectionToggle,
QPushButton#deviceButton,
QPushButton#titleButton,
QPushButton#ghostButton {
    padding: 3px 6px;
    border-radius: 8px;
    font-size: 10px;
}
QPushButton#ghostButton {
    background: rgba(12, 18, 28, 175);
}
QPushButton#deviceButton {
    font-weight: 700;
}
QPushButton#muteButton:checked {
    background: rgba(92, 35, 61, 230);
    border: 1px solid rgba(255, 112, 164, 196);
}
QListWidget {
    background: rgba(8, 12, 19, 200);
    border: 1px solid rgba(63, 84, 114, 126);
    border-radius: 10px;
    padding: 4px;
}
QComboBox, QSpinBox, QLineEdit {
    background: rgba(8, 12, 19, 220);
    border: 1px solid rgba(62, 216, 255, 68);
    border-radius: 8px;
    padding: 4px 8px;
    min-height: 28px;
}
QComboBox {
    padding-left: 8px;
    padding-right: 18px;
}
QComboBox::drop-down {
    border: none;
    width: 18px;
}
QFrame#selectorFrame {
    background: transparent;
    border: none;
}
QPushButton#selectorButton {
    background: transparent;
    border: none;
    padding: 0px 6px 0px 6px;
    margin: 0px;
}
QPushButton#selectorButton:hover {
    background: transparent;
    border: none;
}
QPushButton#selectorButton:pressed {
    background: transparent;
    border: none;
}
QComboBox#selectorCombo {
    background: transparent;
    border: none;
    min-height: 26px;
    padding: 0px 6px 0px 6px;
}
QComboBox#selectorCombo::drop-down {
    border: none;
    width: 0px;
}
QComboBox#selectorCombo::down-arrow {
    image: none;
    width: 0px;
    height: 0px;
}
QComboBox QAbstractItemView {
    background: rgba(8, 12, 19, 245);
    border: 1px solid rgba(62, 216, 255, 68);
    border-radius: 10px;
    outline: none;
    selection-background-color: rgba(255, 92, 199, 120);
    selection-color: #edf4ff;
}

QLineEdit#eqValuePill,
QLineEdit#eqFrequencyPill {
    color: #c8d4e3;
    background: rgba(8, 12, 19, 120);
    border: 1px solid rgba(130, 170, 210, 45);
    border-radius: 6px;
    padding: 0px;
    font-family: "Noto Sans Mono", "DejaVu Sans Mono", monospace;
    font-size: 10px;
    font-weight: 700;
}

QLineEdit#eqValuePill,
QLineEdit#eqFrequencyPill {
    selection-background-color: rgba(62, 216, 255, 110);
}

QLineEdit#eqValuePill:focus,
QLineEdit#eqFrequencyPill:focus {
    color: #edf4ff;
    background: rgba(10, 18, 28, 190);
    border: 1px solid rgba(62, 216, 255, 125);
}

QSlider#eqGainSlider::groove:vertical {
    background: rgba(2, 5, 9, 225);
    border: 1px solid rgba(110, 145, 180, 55);
    border-radius: 5px;
    width: 8px;
}

QSlider#eqGainSlider::handle:vertical {
    background: rgba(62, 216, 255, 230);
    border: 1px solid rgba(210, 245, 255, 190);
    height: 11px;
    margin: 0px -7px;
    border-radius: 6px;
}

QSlider#eqGainSlider::sub-page:vertical {
    background: rgba(62, 216, 255, 92);
    border-radius: 5px;
}

QSlider#eqGainSlider::add-page:vertical {
    background: rgba(0, 0, 0, 185);
    border-radius: 5px;
}

QSlider::groove:vertical {
    background: rgba(11, 16, 24, 235);
    width: 14px;
    border: 1px solid rgba(63, 84, 114, 158);
    border-radius: 7px;
}
QSlider::handle:vertical {
    background: #f7fbff;
    border: 1px solid #ffffff;
    width: 14px;
    height: 11px;
    margin: 0px;
    border-radius: 5px;
}
QSlider::sub-page:vertical {
    background: rgba(11, 16, 24, 235);
    border-radius: 6px;
}
QSlider::add-page:vertical {
    background: rgba(62, 216, 255, 210);
    border-radius: 6px;
}
QSlider#channelVolumeSlider::groove:vertical {
    background: rgba(9, 13, 20, 235);
    width: 10px;
    border: 1px solid rgba(74, 101, 138, 150);
    border-radius: 5px;
}
QSlider#channelVolumeSlider::handle:vertical {
    background: rgba(247, 251, 255, 245);
    border: 1px solid rgba(255, 255, 255, 214);
    width: 14px;
    height: 14px;
    margin: -1px -3px;
    border-radius: 7px;
}
QSlider#channelVolumeSlider::sub-page:vertical {
    background: rgba(16, 24, 36, 240);
    border-radius: 5px;
}
QSlider#channelVolumeSlider::add-page:vertical {
    background: rgba(62, 216, 255, 224);
    border-radius: 5px;
}
QSlider::groove:horizontal {
    background: rgba(11, 16, 24, 235);
    height: 10px;
    border: 1px solid rgba(63, 84, 114, 158);
    border-radius: 5px;
}
QSlider::handle:horizontal {
    background: #f7fbff;
    border: 1px solid #ffffff;
    width: 12px;
    margin: -4px 0px;
    border-radius: 6px;
}
QSlider::sub-page:horizontal {
    background: rgba(255, 92, 199, 185);
    border-radius: 4px;
}
QCheckBox {
    spacing: 8px;
}
QScrollArea {
    border: none;
    background: transparent;
}
QScrollBar:vertical {
    background: transparent;
    width: 6px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: rgba(62, 216, 255, 160);
    min-height: 24px;
    border-radius: 3px;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical,
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: transparent;
    border: none;
}
QScrollBar:horizontal {
    background: transparent;
    height: 8px;
    margin: 0px;
}
QScrollBar::handle:horizontal {
    background: rgba(255, 92, 199, 155);
    min-width: 24px;
    border-radius: 4px;
}
"""



def _notify_existing_instance(payload: dict) -> None:
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.2)
        sock.connect(IPC_SOCKET_PATH)
        sock.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        sock.close()
    except Exception:
        pass

def _apply_palette(app: QApplication) -> None:
    palette = app.palette()
    palette.setColor(QPalette.Window, QColor("#0d1118"))
    palette.setColor(QPalette.WindowText, QColor("#edf4ff"))
    palette.setColor(QPalette.Base, QColor("#09101a"))
    palette.setColor(QPalette.AlternateBase, QColor("#0f1621"))
    palette.setColor(QPalette.ToolTipBase, QColor("#0d1118"))
    palette.setColor(QPalette.ToolTipText, QColor("#edf4ff"))
    palette.setColor(QPalette.Text, QColor("#edf4ff"))
    palette.setColor(QPalette.Button, QColor("#152031"))
    palette.setColor(QPalette.ButtonText, QColor("#edf4ff"))
    palette.setColor(QPalette.Highlight, QColor("#3ed8ff"))
    palette.setColor(QPalette.HighlightedText, QColor("#0d1118"))
    app.setPalette(palette)


def main() -> int:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(RUNTIME_DIR / "app.lock"))
    lock.setStaleLockTime(5000)
    if not lock.tryLock(0):
        _notify_existing_instance({"command": "restore"})
        return 0

    app = QApplication(sys.argv)
    app.setProperty("ksound_instance_lock", lock)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setOrganizationDomain(ORG_DOMAIN)
    if APP_ICON_PATH.is_file():
        app.setWindowIcon(QIcon(str(APP_ICON_PATH)))

    app_icon = QIcon(str(APP_ICON_PATH)) if APP_ICON_PATH.is_file() else None
    if app_icon is not None and not app_icon.isNull():
        app.setWindowIcon(app_icon)

    app.setStyle("Fusion")
    _apply_palette(app)
    app.setStyleSheet(STYLE_SHEET)

    store = SettingsStore()
    window = MainWindow(store)
    if app_icon is not None and not app_icon.isNull():
        window.setWindowIcon(app_icon)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
