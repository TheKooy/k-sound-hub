#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import os
import secrets
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

CONFIG_DIR = Path.home() / ".config" / "ksound-hub-v2"
CONFIG_PATH = CONFIG_DIR / "soundboard.json"
TOKEN_PATH = CONFIG_DIR / "soundboard_web_token"
PAIRING_PATH = CONFIG_DIR / "soundboard_pairing.json"

HOST = "0.0.0.0"
HTTP_PORT = int(os.environ.get("KSOUND_SOUNDBOARD_WEB_PORT", "8765"))
DISCOVERY_PORT = int(os.environ.get("KSOUND_SOUNDBOARD_DISCOVERY_PORT", "8766"))

SERVICE_NAME = "K-Sound Hub Soundboard"
DISCOVERY_REQUEST = b"KSH_DISCOVER_V1"
DISCOVERY_SERVICE = "KSH_SOUNDBOARD"


def chmod_private(path: Path) -> None:
    try:
        path.chmod(0o600)
    except Exception:
        pass


def ensure_token() -> str:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if TOKEN_PATH.is_file():
        token = TOKEN_PATH.read_text(encoding="utf-8").strip()
        if token:
            chmod_private(TOKEN_PATH)
            return token

    token = secrets.token_urlsafe(24)
    TOKEN_PATH.write_text(token + "\n", encoding="utf-8")
    chmod_private(TOKEN_PATH)
    return token


TOKEN = ensure_token()


def local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("1.1.1.1", 80))
            return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def read_slots() -> list[dict]:
    if not CONFIG_PATH.is_file():
        return []
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    slots = data.get("slots", [])
    return [slot for slot in slots if isinstance(slot, dict)]


def send_ipc(payload: dict) -> tuple[bool, str]:
    candidates = [
        os.environ.get("KSH_IPC_SOCKET_PATH", ""),
        f"/tmp/ksound_hub_audio_v2_{os.getuid()}.sock",
        f"/tmp/ksound_hub_audio_{os.getuid()}.sock",
    ]

    last_error = ""
    for socket_path in [x for x in candidates if x]:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.45)
                sock.connect(socket_path)
                sock.sendall((json.dumps(payload) + "\n").encode())
            return True, "OK"
        except Exception as exc:
            last_error = str(exc)

    return False, last_error or "IPC unavailable"


def read_valid_pairing() -> dict | None:
    if not PAIRING_PATH.is_file():
        return None
    try:
        data = json.loads(PAIRING_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None

    try:
        expires_at = float(data.get("expires_at", 0))
    except Exception:
        return None

    if time.time() > expires_at:
        try:
            PAIRING_PATH.unlink()
        except Exception:
            pass
        return None

    pin = str(data.get("pin", "")).strip()
    if not pin:
        return None

    return data


def consume_pairing_if_pin_matches(pin: str) -> bool:
    data = read_valid_pairing()
    if not data:
        return False

    expected = str(data.get("pin", "")).strip()
    provided = str(pin or "").strip()

    if not expected or provided != expected:
        return False

    try:
        PAIRING_PATH.unlink()
    except Exception:
        pass

    return True


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def page(status: str = "") -> bytes:
    slots = read_slots()
    buttons = []

    for index, slot in enumerate(slots):
        slot_id = str(slot.get("id") or f"sb{index + 1}")
        label = str(slot.get("label") or slot_id)
        path = str(slot.get("path") or "")
        disabled = "" if path else "disabled"
        subtitle = Path(path).name if path else "Aucun son"

        buttons.append(
            f"""
            <form method="POST" action="/play?token={html.escape(TOKEN)}">
              <input type="hidden" name="slot" value="{html.escape(slot_id)}">
              <button class="pad" {disabled}>
                <strong>{html.escape(label)}</strong>
                <span>{html.escape(slot_id)} · {html.escape(subtitle)}</span>
              </button>
            </form>
            """
        )

    if not buttons:
        buttons.append("<p class='empty'>Aucun pad trouvé. Configure la soundboard dans K-Sound Hub d'abord.</p>")

    body = f"""
    <!doctype html>
    <html lang="fr">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>K-Sound Soundboard</title>
      <meta name="theme-color" content="#070a12">
      <meta name="mobile-web-app-capable" content="yes">
      <style>
        :root {{
          color-scheme: dark;
          --bg: #070a12;
          --card: rgba(16, 22, 34, .92);
          --cyan: #3ed8ff;
          --pink: #ff5cc7;
          --text: #ecf7ff;
          --muted: #93a4b8;
        }}
        * {{ box-sizing: border-box; }}
        html, body {{
          overscroll-behavior: none;
          user-select: none;
          -webkit-user-select: none;
        }}
        body {{
          margin: 0;
          min-height: 100vh;
          font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          background:
            radial-gradient(circle at 15% 10%, rgba(62,216,255,.25), transparent 28%),
            radial-gradient(circle at 85% 20%, rgba(255,92,199,.22), transparent 30%),
            linear-gradient(135deg, #05070d, #101827 55%, #080b12);
          color: var(--text);
          padding: 18px;
        }}
        header {{
          border: 1px solid rgba(62,216,255,.28);
          border-radius: 22px;
          background: rgba(8, 12, 22, .78);
          padding: 16px;
          margin-bottom: 14px;
          box-shadow: 0 18px 44px rgba(0,0,0,.28);
        }}
        h1 {{
          margin: 0 0 4px;
          letter-spacing: .08em;
          font-size: 22px;
        }}
        .hint, .status {{
          color: var(--muted);
          font-size: 14px;
        }}
        .status {{
          margin-top: 8px;
          color: var(--cyan);
        }}
        .grid {{
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(145px, 1fr));
          gap: 12px;
        }}
        form {{ margin: 0; }}
        .pad, .stop {{
          width: 100%;
          min-height: 92px;
          border: 1px solid rgba(62,216,255,.34);
          border-radius: 20px;
          background: var(--card);
          color: var(--text);
          padding: 14px;
          text-align: left;
          box-shadow: 0 14px 34px rgba(0,0,0,.28);
          touch-action: manipulation;
        }}
        .pad:active, .stop:active {{
          transform: scale(.98);
          border-color: rgba(255,92,199,.85);
        }}
        .pad:disabled {{
          opacity: .38;
        }}
        .pad strong {{
          display: block;
          font-size: 17px;
          margin-bottom: 8px;
        }}
        .pad span {{
          display: block;
          color: var(--muted);
          font-size: 12px;
          word-break: break-word;
        }}
        .stop {{
          min-height: 58px;
          margin-bottom: 14px;
          border-color: rgba(255,92,199,.55);
          text-align: center;
          font-weight: 900;
          letter-spacing: .04em;
        }}
        .empty {{
          color: var(--muted);
        }}
      </style>
    </head>
    <body>
      <header>
        <h1>K-SOUND SOUNDBOARD</h1>
        <div class="hint">Télécommande Android locale. Pairing sécurisé côté LAN.</div>
        {f'<div class="status">{html.escape(status)}</div>' if status else ''}
      </header>

      <form method="POST" action="/stop?token={html.escape(TOKEN)}">
        <button class="stop">STOP ALL</button>
      </form>

      <main class="grid">
        {''.join(buttons)}
      </main>
    </body>
    </html>
    """

    return body.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def _token_ok(self) -> bool:
        query = parse_qs(urlparse(self.path).query)
        return query.get("token", [""])[0] == TOKEN

    def _send_page(self, status: str = "") -> None:
        data = page(status)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/api/info":
            json_response(self, 200, {
                "service": DISCOVERY_SERVICE,
                "version": 1,
                "name": SERVICE_NAME,
                "http_port": HTTP_PORT,
                "discovery_port": DISCOVERY_PORT,
                "pairing_available": read_valid_pairing() is not None,
            })
            return

        if parsed.path == "/api/pair":
            query = parse_qs(parsed.query)
            pin = query.get("pin", [""])[0]
            if consume_pairing_if_pin_matches(pin):
                json_response(self, 200, {
                    "ok": True,
                    "token": TOKEN,
                    "name": SERVICE_NAME,
                    "http_port": HTTP_PORT,
                })
            else:
                json_response(self, 403, {
                    "ok": False,
                    "error": "Code pairing invalide ou expiré",
                })
            return

        if not self._token_ok():
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"Forbidden: missing or invalid token")
            return

        self._send_page()

    def do_POST(self) -> None:
        if not self._token_ok():
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"Forbidden")
            return

        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length).decode("utf-8", errors="ignore")
        form = parse_qs(raw)

        parsed = urlparse(self.path)
        if parsed.path == "/play":
            slot = form.get("slot", [""])[0]
            ok, msg = send_ipc({"command": "soundboard-play", "slot": slot})
            self._send_page(f"Play {slot}: {msg if not ok else 'envoyé'}")
            return

        if parsed.path == "/stop":
            ok, msg = send_ipc({"command": "soundboard-stop-all"})
            self._send_page(f"Stop all: {msg if not ok else 'envoyé'}")
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt: str, *args) -> None:
        return


def discovery_loop(stop_event: threading.Event) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", DISCOVERY_PORT))
        except OSError as exc:
            print(f"Discovery UDP disabled: {exc}", file=sys.stderr, flush=True)
            return

        sock.settimeout(1.0)
        print(f"Discovery UDP listening on 0.0.0.0:{DISCOVERY_PORT}", flush=True)

        while not stop_event.is_set():
            try:
                data, addr = sock.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                break

            if data.strip() != DISCOVERY_REQUEST:
                continue

            payload = {
                "service": DISCOVERY_SERVICE,
                "version": 1,
                "name": SERVICE_NAME,
                "http_port": HTTP_PORT,
                "pairing_available": read_valid_pairing() is not None,
            }
            try:
                sock.sendto(json.dumps(payload).encode("utf-8"), addr)
            except OSError:
                pass


def main() -> int:
    ip = local_ip()
    stop_event = threading.Event()
    thread = threading.Thread(target=discovery_loop, args=(stop_event,), daemon=True)
    thread.start()

    print()
    print("K-Sound Soundboard Web")
    print("======================")
    print(f"HTTP     : http://127.0.0.1:{HTTP_PORT}/")
    print(f"LAN      : http://{ip}:{HTTP_PORT}/")
    print(f"Discovery: UDP {DISCOVERY_PORT}")
    print()
    print("Pairing:")
    print("  ksound-soundboard-pair")
    print()
    print("Ctrl+C pour arrêter.")
    print()

    server = ThreadingHTTPServer((HOST, HTTP_PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.")
    finally:
        stop_event.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
