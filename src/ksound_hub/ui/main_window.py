from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..audio import PipeWireAudioEngine
from ..config import APP_NAME, APP_VERSION
from ..settings_store import SettingsStore
from .channel_widget import ChannelWidget
from .settings_dialog import SettingsDialog


class MainWindow(QMainWindow):
    def __init__(self, settings_store: SettingsStore, parent=None):
        super().__init__(parent)
        self.settings_store = settings_store
        self.settings = settings_store.load()
        self.audio_engine = PipeWireAudioEngine()
        self.channel_widgets: dict[str, ChannelWidget] = {}

        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1420, 860)

        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self.save_btn = QPushButton("Save")
        self.settings_btn = QPushButton("Settings")
        self.refresh_btn = QPushButton("Refresh")
        self.toggle_summary_btn = QPushButton("Hide summary")
        for button in (self.save_btn, self.settings_btn, self.refresh_btn, self.toggle_summary_btn):
            toolbar.addWidget(button)

        self.save_btn.clicked.connect(self.save_settings)
        self.settings_btn.clicked.connect(self.open_settings)
        self.refresh_btn.clicked.connect(self.refresh_status)
        self.toggle_summary_btn.clicked.connect(self.toggle_summary)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        title_row = QHBoxLayout()
        title = QLabel(f"{APP_NAME} {APP_VERSION}")
        title.setObjectName("pageTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.unsaved_label = QLabel("Layout / state preview")
        self.unsaved_label.setObjectName("mutedLabel")
        title_row.addWidget(self.unsaved_label)
        root.addLayout(title_row)

        self.summary_card = QWidget()
        summary_layout = QHBoxLayout(self.summary_card)
        summary_layout.setContentsMargins(12, 10, 12, 10)
        summary_layout.setSpacing(14)
        self.summary_card.setStyleSheet("background: rgba(20, 26, 36, 200); border: 1px solid #2a3346; border-radius: 14px;")

        self.backend_status = QLabel(self.audio_engine.status_text())
        self.backend_status.setWordWrap(True)
        summary_layout.addWidget(self.backend_status, 2)

        self.overlay_status = QLabel(self._settings_summary_text())
        self.overlay_status.setObjectName("mutedLabel")
        self.overlay_status.setWordWrap(True)
        summary_layout.addWidget(self.overlay_status, 1)
        root.addWidget(self.summary_card)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(self.scroll, 1)

        self.columns_host = QWidget()
        self.columns_layout = QHBoxLayout(self.columns_host)
        self.columns_layout.setContentsMargins(0, 0, 0, 0)
        self.columns_layout.setSpacing(10)
        self.columns_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.scroll.setWidget(self.columns_host)

        self._reload_channels()

    def _settings_summary_text(self) -> str:
        enabled_channels = sum(1 for channel in self.settings.channels if channel.enabled)
        total_channels = len(self.settings.channels)
        overlay = "on" if self.settings.overlay_enabled else "off"
        visualizer = "on" if self.settings.visualizer_enabled else "off"
        return (
            f"Channels enabled: {enabled_channels}/{total_channels}\n"
            f"Overlay: {overlay}\n"
            f"Visualizer: {visualizer}"
        )

    def _clear_columns(self) -> None:
        while self.columns_layout.count():
            item = self.columns_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.channel_widgets.clear()

    def _reload_channels(self) -> None:
        self._clear_columns()

        for channel in self.settings.channels:
            if not channel.enabled:
                continue
            widget = ChannelWidget(channel, global_visualizer_enabled=self.settings.visualizer_enabled)
            widget.changed.connect(self._on_any_changed)
            self.channel_widgets[channel.key] = widget
            self.columns_layout.addWidget(widget)

        self.columns_layout.addStretch(1)
        self.overlay_status.setText(self._settings_summary_text())
        self.refresh_status()

    def _on_any_changed(self) -> None:
        self.unsaved_label.setText("State changed — save when ready")
        self.backend_status.setText(self.audio_engine.status_text())

    def refresh_status(self) -> None:
        self.backend_status.setText(self.audio_engine.status_text())
        self.overlay_status.setText(self._settings_summary_text())

    def save_settings(self) -> None:
        self.settings_store.save(self.settings)
        self.unsaved_label.setText("Saved")
        QMessageBox.information(self, APP_NAME, "Settings saved.")

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec():
            dialog.apply_changes()
            self.settings_store.save(self.settings)
            self._reload_channels()
            self.unsaved_label.setText("Settings applied")

    def toggle_summary(self) -> None:
        visible = not self.summary_card.isVisible()
        self.summary_card.setVisible(visible)
        self.toggle_summary_btn.setText("Hide summary" if visible else "Show summary")
