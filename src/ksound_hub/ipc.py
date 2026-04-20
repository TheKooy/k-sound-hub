from __future__ import annotations

import json
import os
import socket
from typing import Optional

from PySide6.QtCore import QObject, QSocketNotifier, Signal


class AudioIpcServer(QObject):
    message_received = Signal(dict)
    status_changed = Signal(str)

    def __init__(self, socket_path: str, parent=None):
        super().__init__(parent)
        self.socket_path = socket_path
        self.server_sock: Optional[socket.socket] = None
        self.notifier: Optional[QSocketNotifier] = None

    def start(self) -> None:
        self.stop()

        try:
            if os.path.exists(self.socket_path):
                os.unlink(self.socket_path)

            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.setblocking(False)
            server.bind(self.socket_path)
            os.chmod(self.socket_path, 0o600)
            server.listen(8)

            self.server_sock = server
            self.notifier = QSocketNotifier(server.fileno(), QSocketNotifier.Type.Read, self)
            self.notifier.activated.connect(self._on_ready)
            self.status_changed.emit(f"IPC shortcuts: active ({self.socket_path})")
        except Exception as exc:
            self.status_changed.emit(f"IPC shortcuts: error — {exc}")

    def stop(self) -> None:
        if self.notifier is not None:
            try:
                self.notifier.setEnabled(False)
            except Exception:
                pass
            self.notifier = None

        if self.server_sock is not None:
            try:
                self.server_sock.close()
            except Exception:
                pass
            self.server_sock = None

        try:
            if os.path.exists(self.socket_path):
                os.unlink(self.socket_path)
        except Exception:
            pass

    def _on_ready(self) -> None:
        if self.server_sock is None:
            return

        while True:
            try:
                conn, _ = self.server_sock.accept()
            except BlockingIOError:
                break
            except Exception:
                break

            try:
                conn.settimeout(0.05)
                data = b""
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                    if b"\n" in data:
                        break

                text = data.decode(errors="replace").strip()
                if text:
                    for line in text.splitlines():
                        self._handle_line(line.strip())
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    def _handle_line(self, line: str) -> None:
        try:
            payload = json.loads(line)
        except Exception:
            return
        if isinstance(payload, dict):
            self.message_received.emit(payload)
