from __future__ import annotations

import sys

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from .config import APP_NAME, ORG_DOMAIN, ORG_NAME
from .settings_store import SettingsStore
from .ui.main_window import MainWindow

STYLE_SHEET = """
QWidget {
    background: #16131b;
    color: #efeaf7;
    font-size: 13px;
}
QMainWindow, QDialog {
    background: #16131b;
}
QLabel#pageTitle {
    font-size: 20px;
    font-weight: 800;
}
QLabel#mutedLabel {
    color: #b9b0c8;
    font-size: 11px;
}
QFrame#channelCard {
    background: rgba(32, 23, 39, 228);
    border: 1px solid rgba(122, 96, 150, 160);
    border-radius: 18px;
}
QFrame#sectionCard,
QFrame#footerBar,
QFrame#appRuleRow {
    background: rgba(22, 18, 30, 220);
    border: 1px solid rgba(96, 78, 120, 165);
    border-radius: 12px;
}
QFrame#appRuleRow:hover {
    background: rgba(33, 27, 43, 228);
    border: 1px solid rgba(158, 126, 194, 180);
}
QPushButton {
    background: rgba(88, 70, 112, 210);
    border: 1px solid rgba(141, 110, 180, 185);
    border-radius: 10px;
    padding: 7px 10px;
}
QPushButton:hover {
    background: rgba(104, 82, 132, 220);
}
QPushButton:pressed {
    background: rgba(70, 56, 92, 220);
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
    background: rgba(28, 23, 36, 150);
}
QPushButton#deviceButton {
    font-weight: 700;
}
QPushButton#muteButton:checked {
    background: rgba(155, 78, 95, 220);
    border: 1px solid rgba(232, 140, 160, 210);
}
QListWidget {
    background: rgba(16, 13, 22, 170);
    border: 1px solid rgba(92, 75, 118, 170);
    border-radius: 10px;
    padding: 4px;
}
QComboBox, QSpinBox, QLineEdit {
    background: rgba(16, 13, 22, 180);
    border: 1px solid rgba(118, 96, 145, 185);
    border-radius: 8px;
    padding: 4px 6px;
}
QSlider::groove:vertical {
    background: rgba(24, 18, 32, 230);
    width: 16px;
    border: 1px solid rgba(158, 126, 194, 88);
    border-radius: 8px;
}
QSlider::handle:vertical {
    background: #f4eaff;
    border: 1px solid #fff7ff;
    width: 16px;
    height: 12px;
    margin: 0px;
    border-radius: 6px;
}
QSlider::sub-page:vertical {
    background: rgba(24, 18, 32, 230);
    border-radius: 7px;
}
QSlider::add-page:vertical {
    background: rgba(196, 132, 255, 200);
    border-radius: 7px;
}
QSlider::groove:horizontal {
    background: rgba(24, 18, 32, 230);
    height: 10px;
    border: 1px solid rgba(158, 126, 194, 88);
    border-radius: 5px;
}
QSlider::handle:horizontal {
    background: #f4eaff;
    border: 1px solid #fff7ff;
    width: 12px;
    margin: -4px 0px;
    border-radius: 6px;
}
QSlider::sub-page:horizontal {
    background: rgba(196, 132, 255, 200);
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
    background: rgba(196, 132, 255, 150);
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
    background: rgba(196, 132, 255, 150);
    min-width: 24px;
    border-radius: 4px;
}
"""


def _apply_palette(app: QApplication) -> None:
    palette = app.palette()
    palette.setColor(QPalette.Window, QColor("#16131b"))
    palette.setColor(QPalette.WindowText, QColor("#efeaf7"))
    palette.setColor(QPalette.Base, QColor("#140f1b"))
    palette.setColor(QPalette.AlternateBase, QColor("#191320"))
    palette.setColor(QPalette.ToolTipBase, QColor("#140f1b"))
    palette.setColor(QPalette.ToolTipText, QColor("#efeaf7"))
    palette.setColor(QPalette.Text, QColor("#efeaf7"))
    palette.setColor(QPalette.Button, QColor("#584670"))
    palette.setColor(QPalette.ButtonText, QColor("#efeaf7"))
    palette.setColor(QPalette.Highlight, QColor("#c484ff"))
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
