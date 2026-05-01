from __future__ import annotations

import json
import time
from typing import Any

from PySide6.QtCore import QByteArray, QObject, QEvent, QRect, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from ..config import CONFIG_DIR

WINDOW_GEOMETRY_PATH = CONFIG_DIR / "window_geometry.json"

MIN_WIDTH = 160
MIN_HEIGHT = 120
RESTORE_PASSES_MS = (0, 120, 360)
SAVE_ENABLE_DELAY_MS = 900
SAVE_DEBOUNCE_MS = 350


def _load_data() -> dict[str, Any]:
    if not WINDOW_GEOMETRY_PATH.is_file():
        return {}

    try:
        data = json.loads(WINDOW_GEOMETRY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

    return data if isinstance(data, dict) else {}


def _save_data(data: dict[str, Any]) -> None:
    WINDOW_GEOMETRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = WINDOW_GEOMETRY_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(WINDOW_GEOMETRY_PATH)


def _visible_screen_rects() -> list[QRect]:
    app = QApplication.instance()
    if app is None:
        return []
    return [screen.availableGeometry() for screen in app.screens()]


def _is_window_visible_on_any_screen(widget: QWidget) -> bool:
    rect = widget.frameGeometry()
    if rect.isNull():
        rect = widget.geometry()

    if rect.isNull():
        return True

    for screen_rect in _visible_screen_rects():
        padded = screen_rect.adjusted(-80, -80, 80, 80)
        if padded.intersects(rect):
            return True

    return False


def _center_window(widget: QWidget, default_size: tuple[int, int] | None = None) -> None:
    app = QApplication.instance()
    screen = widget.screen() if widget.screen() is not None else (app.primaryScreen() if app else None)

    if screen is None:
        if default_size is not None:
            widget.resize(int(default_size[0]), int(default_size[1]))
        return

    available = screen.availableGeometry()

    if default_size is not None and (widget.width() < MIN_WIDTH or widget.height() < MIN_HEIGHT):
        widget.resize(int(default_size[0]), int(default_size[1]))

    width = max(MIN_WIDTH, min(widget.width(), available.width()))
    height = max(MIN_HEIGHT, min(widget.height(), available.height()))
    widget.resize(width, height)

    frame = widget.frameGeometry()
    if frame.isNull():
        frame = QRect(0, 0, width, height)

    frame.moveCenter(available.center())
    widget.move(frame.topLeft())


def restore_window_geometry(widget: QWidget, key: str, default_size: tuple[int, int] | None = None) -> bool:
    key = str(key or "").strip()
    if not key:
        return False

    data = _load_data()
    entry = data.get(key)

    restored = False
    if isinstance(entry, dict):
        encoded = str(entry.get("geometry") or "").strip()
        if encoded:
            try:
                raw = QByteArray.fromBase64(encoded.encode("ascii"))
                if not raw.isEmpty():
                    restored = bool(widget.restoreGeometry(raw))
            except Exception:
                restored = False

    if not restored:
        if default_size is not None:
            widget.resize(int(default_size[0]), int(default_size[1]))
        _center_window(widget, default_size)
        return False

    if not _is_window_visible_on_any_screen(widget):
        _center_window(widget, default_size)

    return True


def save_window_geometry(widget: QWidget, key: str) -> None:
    key = str(key or "").strip()
    if not key:
        return

    if widget.width() < MIN_WIDTH or widget.height() < MIN_HEIGHT:
        return

    try:
        encoded = bytes(widget.saveGeometry().toBase64()).decode("ascii")
    except Exception:
        return

    frame = widget.frameGeometry()
    geometry = widget.geometry()

    data = _load_data()
    data[key] = {
        "geometry": encoded,
        "saved_at": int(time.time()),
        "qt_frame": {
            "x": int(frame.x()),
            "y": int(frame.y()),
            "width": int(frame.width()),
            "height": int(frame.height()),
        },
        "qt_client": {
            "x": int(geometry.x()),
            "y": int(geometry.y()),
            "width": int(geometry.width()),
            "height": int(geometry.height()),
        },
    }
    _save_data(data)


class WindowGeometryEventFilter(QObject):
    def __init__(self, widget: QWidget, key: str, default_size: tuple[int, int] | None = None):
        super().__init__(widget)
        self.widget = widget
        self.key = str(key or "").strip()
        self.default_size = default_size

        self._restored = False
        self._restoring = False
        self._save_enabled = False

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self._save_now)

    def _enable_save(self) -> None:
        self._save_enabled = True

    def _restore_once(self) -> None:
        if not self.widget.isVisible():
            return

        self._restoring = True
        try:
            restore_window_geometry(self.widget, self.key, self.default_size)
            self._restored = True
        finally:
            self._restoring = False

    def _schedule_restore(self) -> None:
        if self._restored:
            return

        for delay in RESTORE_PASSES_MS:
            QTimer.singleShot(delay, self._restore_once)

        QTimer.singleShot(SAVE_ENABLE_DELAY_MS, self._enable_save)

    def _save_later(self) -> None:
        if self._restoring or not self._restored or not self._save_enabled:
            return
        self._save_timer.start()

    def _save_now(self) -> None:
        if self._restoring or not self._restored:
            return
        save_window_geometry(self.widget, self.key)

    def eventFilter(self, obj, event) -> bool:
        if obj is not self.widget:
            return False

        event_type = event.type()

        if event_type in (QEvent.Show, QEvent.ShowToParent):
            self._schedule_restore()
            return False

        if event_type in (QEvent.Move, QEvent.Resize, QEvent.WindowStateChange):
            self._save_later()
            return False

        if event_type in (QEvent.Hide, QEvent.HideToParent, QEvent.Close):
            if self._save_timer.isActive():
                self._save_timer.stop()
            if self._restored:
                save_window_geometry(self.widget, self.key)
            return False

        return False


def install_window_geometry(widget: QWidget, key: str, default_size: tuple[int, int] | None = None) -> None:
    attr = "_ksound_window_geometry_filter"
    if getattr(widget, attr, None) is not None:
        return

    event_filter = WindowGeometryEventFilter(widget, key, default_size)
    widget.installEventFilter(event_filter)
    setattr(widget, attr, event_filter)

    if widget.isVisible():
        event_filter._schedule_restore()
