from __future__ import annotations

import sys

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from .config import APP_NAME, ORG_DOMAIN, ORG_NAME
from .settings_store import SettingsStore
from .ui.main_window import MainWindow

STYLE_SHEET = """
QWidget {
    background: #0d1118;
    color: #edf4ff;
    font-size: 13px;
}
QMainWindow, QDialog {
    background: #0d1118;
}
QLabel#pageTitle {
    font-size: 20px;
    font-weight: 800;
}
QLabel#mutedLabel {
    color: #9eabc2;
    font-size: 11px;
}
QFrame#channelCard {
    background: rgba(16, 22, 34, 238);
    border: 1px solid rgba(62, 216, 255, 90);
    border-radius: 18px;
}
QFrame#channelCard:hover {
    border: 1px solid rgba(255, 92, 199, 120);
}
QFrame#sectionCard,
QFrame#footerBar,
QFrame#appRuleRow {
    background: rgba(11, 16, 26, 228);
    border: 1px solid rgba(74, 101, 138, 150);
    border-radius: 12px;
}
QFrame#appRuleRow:hover {
    background: rgba(17, 24, 38, 235);
    border: 1px solid rgba(255, 92, 199, 120);
}
QPushButton {
    background: rgba(21, 31, 48, 235);
    border: 1px solid rgba(62, 216, 255, 110);
    border-radius: 10px;
    padding: 7px 10px;
}
QPushButton:hover {
    background: rgba(28, 40, 61, 240);
    border: 1px solid rgba(255, 92, 199, 120);
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
    padding: 4px 7px;
    border-radius: 8px;
    font-size: 11px;
}
QPushButton#ghostButton {
    background: rgba(12, 18, 28, 175);
}
QPushButton#deviceButton {
    font-weight: 700;
}
QPushButton#muteButton:checked {
    background: rgba(92, 35, 61, 230);
    border: 1px solid rgba(255, 112, 164, 190);
}
QListWidget {
    background: rgba(8, 12, 19, 200);
    border: 1px solid rgba(63, 84, 114, 170);
    border-radius: 10px;
    padding: 4px;
}
QComboBox, QSpinBox, QLineEdit {
    background: rgba(8, 12, 19, 220);
    border: 1px solid rgba(62, 216, 255, 95);
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
    background: rgba(8, 12, 19, 220);
    border: 1px solid rgba(62, 216, 255, 95);
    border-radius: 10px;
}
QLabel#selectorBadge {
    background: transparent;
    border: none;
    font-size: 12px;
    font-weight: 900;
    padding: 0px;
    margin: 0px;
}
QComboBox#selectorCombo {
    background: transparent;
    border: none;
    min-height: 26px;
    padding: 0px 16px 0px 0px;
}
QComboBox#selectorCombo::drop-down {
    border: none;
    width: 16px;
}
QComboBox QAbstractItemView {
    background: rgba(8, 12, 19, 245);
    border: 1px solid rgba(62, 216, 255, 95);
    selection-background-color: rgba(255, 92, 199, 120);
    selection-color: #edf4ff;
}
QSlider::groove:vertical {
    background: rgba(11, 16, 24, 235);
    width: 14px;
    border: 1px solid rgba(63, 84, 114, 160);
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
QSlider::groove:horizontal {
    background: rgba(11, 16, 24, 235);
    height: 10px;
    border: 1px solid rgba(63, 84, 114, 160);
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
