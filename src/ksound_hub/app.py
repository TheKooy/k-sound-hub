from __future__ import annotations

import sys

from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QApplication

from .config import APP_NAME, ORG_DOMAIN, ORG_NAME
from .settings_store import SettingsStore
from .ui.main_window import MainWindow

STYLE_SHEET = """
QWidget {
    background: #12151b;
    color: #e7edf5;
    font-size: 13px;
}
QMainWindow, QDialog {
    background: #12151b;
}
QLabel#pageTitle {
    font-size: 22px;
    font-weight: 800;
}
QLabel#mutedLabel {
    color: #aeb8c8;
    font-size: 11px;
}
QFrame#channelCard {
    background: rgba(20, 26, 36, 220);
    border: 1px solid #2a3346;
    border-radius: 16px;
}
QFrame#sectionCard {
    background: rgba(14, 19, 27, 205);
    border: 1px solid #263248;
    border-radius: 12px;
}
QPushButton {
    background: #263248;
    border: 1px solid #31405d;
    border-radius: 10px;
    padding: 7px 10px;
}
QPushButton:hover {
    background: #30415f;
}
QPushButton:pressed {
    background: #1d2940;
}
QPushButton#tinyButton,
QPushButton#muteButton,
QPushButton#sectionToggle,
QPushButton#deviceButton,
QPushButton#titleButton {
    padding: 4px 7px;
    border-radius: 8px;
    font-size: 11px;
}
QPushButton#deviceButton {
    font-weight: 700;
}
QPushButton#muteButton:checked {
    background: rgba(130, 55, 55, 210);
    border: 1px solid #b85c5c;
}
QListWidget {
    background: rgba(12, 18, 26, 180);
    border: 1px solid #263248;
    border-radius: 10px;
    padding: 4px;
}
QComboBox, QSpinBox, QLineEdit {
    background: rgba(12, 18, 26, 180);
    border: 1px solid #31405d;
    border-radius: 8px;
    padding: 4px 6px;
}
QSlider::groove:vertical {
    background: rgba(18, 23, 32, 220);
    width: 16px;
    border: 1px solid rgba(128, 170, 255, 65);
    border-radius: 8px;
}
QSlider::handle:vertical {
    background: #d9e4ff;
    border: 1px solid #f2f6ff;
    width: 16px;
    height: 12px;
    margin: 0px;
    border-radius: 6px;
}
QSlider::sub-page:vertical {
    background: rgba(18, 23, 32, 220);
    border-radius: 7px;
}
QSlider::add-page:vertical {
    background: rgba(128, 170, 255, 205);
    border-radius: 7px;
}
QSlider::groove:horizontal {
    background: rgba(18, 23, 32, 220);
    height: 10px;
    border: 1px solid rgba(128, 170, 255, 65);
    border-radius: 5px;
}
QSlider::handle:horizontal {
    background: #d9e4ff;
    border: 1px solid #f2f6ff;
    width: 12px;
    margin: -4px 0px;
    border-radius: 6px;
}
QSlider::sub-page:horizontal {
    background: rgba(128, 170, 255, 205);
    border-radius: 4px;
}
QCheckBox {
    spacing: 8px;
}
QToolBar {
    border: none;
    spacing: 6px;
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
    background: rgba(128, 170, 255, 145);
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
    background: rgba(128, 170, 255, 145);
    min-width: 24px;
    border-radius: 4px;
}
"""


def _apply_palette(app: QApplication) -> None:
    palette = app.palette()
    palette.setColor(QPalette.Window, QColor("#12151b"))
    palette.setColor(QPalette.WindowText, QColor("#e7edf5"))
    palette.setColor(QPalette.Base, QColor("#0f141d"))
    palette.setColor(QPalette.AlternateBase, QColor("#141821"))
    palette.setColor(QPalette.ToolTipBase, QColor("#0f141d"))
    palette.setColor(QPalette.ToolTipText, QColor("#e7edf5"))
    palette.setColor(QPalette.Text, QColor("#e7edf5"))
    palette.setColor(QPalette.Button, QColor("#263248"))
    palette.setColor(QPalette.ButtonText, QColor("#e7edf5"))
    palette.setColor(QPalette.Highlight, QColor("#4d78ad"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setOrganizationDomain(ORG_DOMAIN)
    app.setStyle("Fusion")
    _apply_palette(app)
    app.setStyleSheet(STYLE_SHEET)

    store = SettingsStore()
    window = MainWindow(store)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
