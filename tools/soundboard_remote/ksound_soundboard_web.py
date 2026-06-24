#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import mimetypes
import hashlib
import os
import secrets
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

CONFIG_DIR = Path(os.environ.get("KSH_CONFIG_DIR", str(Path.home() / ".config" / "k-sounds-hub"))).expanduser()
CONFIG_PATH = CONFIG_DIR / "soundboard.json"
TOKEN_PATH = CONFIG_DIR / "soundboard_web_token"
PAIRING_PATH = CONFIG_DIR / "soundboard_pairing.json"

HOST = "0.0.0.0"
HTTP_PORT = int(os.environ.get("KSOUND_SOUNDBOARD_WEB_PORT", "8765"))
DISCOVERY_PORT = int(os.environ.get("KSOUND_SOUNDBOARD_DISCOVERY_PORT", "8766"))
REMOTE_IDLE_TIMEOUT_SECONDS = max(0, int(os.environ.get("KSOUND_SOUNDBOARD_IDLE_TIMEOUT_SECONDS", "0")))
REMOTE_IDLE_CHECK_SECONDS = max(5, int(os.environ.get("KSOUND_SOUNDBOARD_IDLE_CHECK_SECONDS", "30")))

_REMOTE_LAST_ACTIVITY = time.monotonic()
_REMOTE_ACTIVITY_LOCK = threading.Lock()


def mark_remote_activity(reason: str = "") -> None:
    global _REMOTE_LAST_ACTIVITY
    with _REMOTE_ACTIVITY_LOCK:
        _REMOTE_LAST_ACTIVITY = time.monotonic()



SERVICE_NAME = "K-Sounds Remote"
DISCOVERY_REQUEST = b"KSH_DISCOVER_V2"
DISCOVERY_REQUESTS = {b"KSH_DISCOVER_V1", b"KSH_DISCOVER_V2"}
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


def clean_folder_label(value) -> str:
    label = " ".join(str(value or "").strip().split())
    if not label:
        return ""
    if label.casefold() == "main":
        return "Main"
    return label[:48]


def slot_folder_label(slot: dict) -> str:
    if not isinstance(slot, dict):
        return ""
    return clean_folder_label(slot.get("folder"))


def available_soundboard_folders(data: dict) -> list[str]:
    folders: list[str] = []

    def add_folder(value) -> None:
        label = clean_folder_label(value)
        if not label:
            return
        if all(existing.casefold() != label.casefold() for existing in folders):
            folders.append(label)

    add_folder("Main")

    raw_folders = data.get("folders", []) if isinstance(data, dict) else []
    if isinstance(raw_folders, list):
        for folder in raw_folders:
            add_folder(folder)

    raw_slots = data.get("slots", []) if isinstance(data, dict) else []
    if isinstance(raw_slots, list):
        for slot in raw_slots:
            if isinstance(slot, dict):
                add_folder(slot.get("folder"))

    return folders


def background_file_version(path_text: str) -> str:
    path_text = str(path_text or "").strip()
    if not path_text:
        return ""

    try:
        image_path = Path(path_text).expanduser()
        stat = image_path.stat()
        if not image_path.is_file():
            return ""
        return f"{stat.st_mtime_ns}:{stat.st_size}"
    except Exception:
        return ""


def read_soundboard_settings() -> dict:
    defaults = {
        "global_volume": 100,
        "auto_level_enabled": False,
        "pad_scale": 100,
        "remote_columns": 0,
        "remote_contrast": "normal",
        "remote_background": "glass",
        "remote_folder_size": "large",
        "remote_folder_style": "pills",
    }

    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return defaults

    if not isinstance(data, dict):
        return defaults

    try:
        defaults["global_volume"] = max(0, min(100, int(data.get("global_volume", 100))))
    except Exception:
        defaults["global_volume"] = 100

    defaults["auto_level_enabled"] = bool(data.get("auto_level_enabled", False))

    try:
        defaults["pad_scale"] = max(35, min(130, int(data.get("pad_scale", 100))))
    except Exception:
        defaults["pad_scale"] = 100

    try:
        raw_columns = int(data.get("remote_columns", 0))
        defaults["remote_columns"] = max(1, min(8, raw_columns)) if raw_columns else 0
    except Exception:
        defaults["remote_columns"] = 0

    contrast = str(data.get("remote_contrast") or defaults["remote_contrast"]).strip().lower()
    defaults["remote_contrast"] = contrast if contrast in {"normal", "high", "soft"} else "normal"

    background = str(data.get("remote_background") or defaults["remote_background"]).strip().lower()
    defaults["remote_background"] = background if background in {"glass", "clean", "grid", "dark"} else "glass"

    folder_size = str(data.get("remote_folder_size") or defaults["remote_folder_size"]).strip().lower()
    defaults["remote_folder_size"] = folder_size if folder_size in {"normal", "large", "xl"} else "large"

    folder_style = str(data.get("remote_folder_style") or defaults["remote_folder_style"]).strip().lower()
    defaults["remote_folder_style"] = folder_style if folder_style in {"pills", "tabs"} else "pills"

    return defaults


def soundboard_revision() -> str:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return "missing"

    slots = data.get("slots", []) if isinstance(data, dict) else []
    folders = data.get("folders", []) if isinstance(data, dict) else []
    payload = json.dumps(
        {
            "slots": slots,
            "folders": folders,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def read_soundboard_state() -> dict:
    data = {}

    if CONFIG_PATH.is_file():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}

    raw_slots = data.get("slots", [])
    if not isinstance(raw_slots, list):
        raw_slots = []

    slots = []
    for index, raw_slot in enumerate(raw_slots):
        if not isinstance(raw_slot, dict):
            continue

        slot_id = str(raw_slot.get("id") or f"sb{index + 1}").strip() or f"sb{index + 1}"
        label = str(raw_slot.get("label") or f"SOUND {index + 1:02d}").strip() or f"SOUND {index + 1:02d}"
        path = str(raw_slot.get("path") or "").strip()
        background_path = str(raw_slot.get("background_path") or "").strip()
        background_version = background_file_version(background_path)
        folder_label = slot_folder_label(raw_slot)

        try:
            volume = max(0, min(100, int(raw_slot.get("volume", 80))))
        except Exception:
            volume = 80

        output_channel = str(raw_slot.get("output_channel") or "media").strip().lower() or "media"

        slots.append(
            {
                "id": slot_id,
                "index": index,
                "number": index + 1,
                "label": label,
                "path": path,
                "background_path": background_path,
                "background_version": background_version,
                "has_sound": bool(path),
                "has_background": bool(background_version),
                "volume": volume,
                "shortcut": str(raw_slot.get("shortcut") or "").strip(),
                "output_channel": output_channel,
                "folder": folder_label,
            }
        )

    folders = available_soundboard_folders(data)
    revision_payload = {
        "slots": slots,
        "folders": folders,
        "slot_count": len(slots),
    }
    revision = hashlib.sha1(
        json.dumps(
            revision_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    return {
        "revision": revision,
        "global_volume": int(data.get("global_volume", 100)),
        "auto_level_enabled": bool(data.get("auto_level_enabled", False)),
        "pad_scale": int(data.get("pad_scale", 100)),
        "remote_columns": read_soundboard_settings().get("remote_columns", 0),
        "folders": folders,
        "slot_count": len(slots),
        "slots": slots,
    }


def update_soundboard_setting(key: str, value) -> None:
    try:
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        loaded = {"slots": []}

    if isinstance(loaded, list):
        data = {"slots": loaded}
    elif isinstance(loaded, dict):
        data = loaded
    else:
        data = {"slots": []}

    if not isinstance(data.get("slots"), list):
        data["slots"] = []

    if key == "global_volume":
        try:
            data[key] = max(0, min(100, int(value)))
        except Exception:
            data[key] = 100
    elif key == "auto_level_enabled":
        data[key] = bool(value)
    elif key == "pad_scale":
        try:
            data[key] = max(35, min(130, int(value)))
        except Exception:
            data[key] = 100
    elif key == "remote_columns":
        try:
            raw_columns = int(value)
            data[key] = max(1, min(8, raw_columns)) if raw_columns else 0
        except Exception:
            data[key] = 0
    elif key == "remote_contrast":
        cleaned = str(value or "").strip().lower()
        data[key] = cleaned if cleaned in {"normal", "high", "soft"} else "normal"
    elif key == "remote_background":
        cleaned = str(value or "").strip().lower()
        data[key] = cleaned if cleaned in {"glass", "clean", "grid", "dark"} else "glass"
    elif key == "remote_folder_size":
        cleaned = str(value or "").strip().lower()
        data[key] = cleaned if cleaned in {"normal", "large", "xl"} else "large"
    elif key == "remote_folder_style":
        cleaned = str(value or "").strip().lower()
        data[key] = cleaned if cleaned in {"pills", "tabs"} else "pills"
    else:
        return

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def send_ipc(payload: dict) -> tuple[bool, str]:
    # Bridge remote web actions to the running Glass IPC server.
    # Keep compatibility with current and historical socket names.
    candidates = [
        os.environ.get("KSH_IPC_SOCKET_PATH", ""),
        os.environ.get("KSOUND_HUB_IPC_SOCKET", ""),
        f"/tmp/ksounds_hub_audio_{os.getuid()}.sock",
        f"/tmp/ksound_hub_audio_v2_{os.getuid()}.sock",
        f"/tmp/ksound_hub_audio_{os.getuid()}.sock",
    ]

    seen: set[str] = set()
    last_error = ""
    for socket_path in [candidate for candidate in candidates if candidate]:
        if socket_path in seen:
            continue
        seen.add(socket_path)

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.45)
                sock.connect(socket_path)
                sock.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
            return True, "OK"
        except Exception as exc:
            last_error = f"{socket_path}: {exc}"

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
    state = read_soundboard_state()
    slots = state.get("slots", [])
    folders = state.get("folders", ["Main"])
    settings = read_soundboard_settings()
    config_revision = html.escape(str(state.get("revision", "")), quote=True)
    global_volume = int(settings.get("global_volume", 100))
    auto_level_text = "ON" if settings.get("auto_level_enabled") else "OFF"

    pad_scale = max(35, min(130, int(settings.get("pad_scale", 100))))
    remote_columns = max(0, min(8, int(settings.get("remote_columns", 0))))
    remote_contrast = str(settings.get("remote_contrast", "normal")).strip().lower()
    remote_background = str(settings.get("remote_background", "glass")).strip().lower()
    remote_folder_size = str(settings.get("remote_folder_size", "large")).strip().lower()
    remote_folder_style = str(settings.get("remote_folder_style", "pills")).strip().lower()

    if remote_contrast not in {"normal", "high", "soft"}:
        remote_contrast = "normal"
    if remote_background not in {"glass", "clean", "grid", "dark"}:
        remote_background = "glass"
    if remote_folder_size not in {"normal", "large", "xl"}:
        remote_folder_size = "large"
    if remote_folder_style not in {"pills", "tabs"}:
        remote_folder_style = "pills"

    body_classes = " ".join(
        [
            f"contrast-{remote_contrast}",
            f"remote-bg-{remote_background}",
            f"folder-size-{remote_folder_size}",
            f"folder-style-{remote_folder_style}",
        ]
    )

    def option_selected(current: str, wanted: str) -> str:
        return " selected" if str(current).lower() == wanted else ""

    pad_factor = pad_scale / 100.0
    pad_min_width = max(92, int(126 * pad_factor))
    pad_min_height = max(86, int(108 * pad_factor))
    pad_padding = max(8, int(14 * pad_factor))
    pad_radius = max(14, int(20 * pad_factor))
    pad_wrap_radius = max(16, int(22 * pad_factor))
    pad_gap = max(5, int(9 * pad_factor))
    pad_title_font = max(13, int(17 * pad_factor))
    pad_subtitle_font = max(10, int(12 * pad_factor))
    pad_title_margin = max(4, int(8 * pad_factor))

    escaped_token = html.escape(TOKEN, quote=True)

    folder_buttons = [
        '<button type="button" class="folder-pill active" data-folder="__all__">All</button>'
    ]
    for folder in folders:
        folder_label = clean_folder_label(folder)
        if not folder_label:
            continue
        escaped_folder = html.escape(folder_label, quote=True)
        folder_filter = "" if folder_label.casefold() == "main" else folder_label
        escaped_filter = html.escape(folder_filter, quote=True)
        folder_buttons.append(
            f'<button type="button" class="folder-pill" data-folder="{escaped_filter}">{escaped_folder}</button>'
        )

    folder_bar_html = (
        '<section class="folder-bar" aria-label="Sound folders">'
        + "".join(folder_buttons)
        + "</section>"
    )

    buttons = []

    for index, slot in enumerate(slots):
        slot_id = str(slot.get("id") or f"sb{index + 1}")
        label = str(slot.get("label") or slot_id)
        folder_label = clean_folder_label(slot.get("folder"))
        path_text = str(slot.get("path") or "")
        background_path = str(slot.get("background_path") or "").strip()
        background_version = background_file_version(background_path)
        background_exists = bool(background_version)
        disabled = "" if path_text else "disabled"
        subtitle = Path(path_text).name if path_text else "No sound"
        pad_class = "pad has-bg" if background_exists else "pad"
        style_attr = ""
        if background_exists:
            background_url = (
                "/background?token="
                + quote(TOKEN, safe="")
                + "&slot="
                + quote(slot_id, safe="")
                + "&rev="
                + quote(background_version, safe="")
            )
            style_attr = f' style="--pad-bg: url({html.escape(background_url, quote=True)})"'

        buttons.append(
            f"""
            <div
              class="pad-wrap"
              data-slot="{html.escape(slot_id, quote=True)}"
              data-folder="{html.escape(folder_label, quote=True)}"
              data-label="{html.escape(label, quote=True)}"
              data-index="{index}"
            >
              <button
                class="{pad_class}"
                type="button"
                data-slot="{html.escape(slot_id, quote=True)}"
                data-label="{html.escape(label, quote=True)}"
                onclick="playSlotFromButton(this)"
                {style_attr}
                {disabled}
              >
                <strong>{html.escape(label)}</strong>
              </button>
            </div>
            """
        )

    if not buttons:
        buttons.append("<p class='empty'>No pads found. Configure the soundboard in K-Sounds Hub first.</p>")

    initial_status = html.escape(status or "Ready")

    body = f"""
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>K-Sounds Remote</title>
      <meta name="theme-color" content="#070a12">
      <meta name="mobile-web-app-capable" content="yes">
      <style>
        :root {{
          color-scheme: dark;
          --bg: #05070d;
          --panel: rgba(7, 11, 20, .72);
          --panel-strong: rgba(10, 16, 29, .88);
          --card: rgba(13, 20, 34, .78);
          --card-hover: rgba(18, 30, 48, .86);
          --bar: rgba(5, 8, 15, .86);
          --cyan: #3ed8ff;
          --cyan-soft: rgba(62, 216, 255, .18);
          --pink: #ff5cc7;
          --pink-soft: rgba(255, 92, 199, .16);
          --text: #ecf7ff;
          --muted: #93a4b8;
          --line: rgba(142, 225, 255, .20);
          --shadow: rgba(0, 0, 0, .48);
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
            radial-gradient(circle at 16% -8%, rgba(62,216,255,.30), transparent 34%),
            radial-gradient(circle at 92% 8%, rgba(255,92,199,.22), transparent 30%),
            radial-gradient(circle at 50% 110%, rgba(62,216,255,.10), transparent 38%),
            linear-gradient(135deg, #02040a, #07101d 48%, #05070d);
          color: var(--text);
          padding: 14px 14px 112px;
        }}
        body::before {{
          content: "";
          position: fixed;
          inset: 0;
          pointer-events: none;
          background:
            linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255,255,255,.018) 1px, transparent 1px);
          background-size: 42px 42px;
          mask-image: linear-gradient(to bottom, rgba(0,0,0,.65), transparent 72%);
        }}
        body.edit-mode header {{
          border-color: rgba(255,92,199,.65);
        }}
        header {{
          position: sticky;
          top: 10px;
          z-index: 20;
          border: 1px solid var(--line);
          border-radius: 24px;
          background:
            linear-gradient(135deg, rgba(10,16,29,.86), rgba(7,11,20,.68)),
            linear-gradient(135deg, rgba(62,216,255,.10), rgba(255,92,199,.08));
          padding: 14px;
          margin-bottom: 14px;
          box-shadow: 0 18px 48px var(--shadow);
          backdrop-filter: blur(18px) saturate(1.35);
        }}
        .brand-row {{
          display: grid;
          grid-template-columns: 54px minmax(0, 1fr) auto;
          gap: 12px;
          align-items: center;
        }}
        .brand-mark {{
          width: 54px;
          height: 54px;
          display: grid;
          place-items: center;
          border: 1px solid rgba(62,216,255,.42);
          border-radius: 18px;
          color: var(--cyan);
          background: rgba(2,4,10,.72);
          font-size: 24px;
          font-weight: 900;
          box-shadow: inset 0 0 18px rgba(62,216,255,.10), 0 12px 28px rgba(0,0,0,.35);
        }}
        .brand-title {{
          min-width: 0;
        }}
        h1 {{
          margin: 0;
          letter-spacing: .11em;
          font-size: 22px;
          line-height: 1.05;
        }}
        .hint, .status {{
          color: var(--muted);
          font-size: 13px;
        }}
        .hint {{
          margin-top: 10px;
        }}
        .status {{
          margin-top: 10px;
          color: var(--cyan);
          min-height: 18px;
          padding: 8px 10px;
          border: 1px solid rgba(62,216,255,.18);
          border-radius: 14px;
          background: rgba(2,4,10,.34);
        }}
        .grid {{
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax({pad_min_width}px, 1fr));
          gap: var(--ksh-pad-gap, {pad_gap}px);
          position: relative;
          z-index: 1;
        }}
        body.visible-few .grid {{
          grid-template-columns: repeat(auto-fill, minmax(min(142px, 100%), 170px));
          justify-content: start;
        }}
        body.visible-one .grid {{
          grid-template-columns: minmax(min(142px, 100%), 170px);
          justify-content: start;
        }}
        .pad-wrap {{
          position: relative;
          min-width: 0;
          border-radius: var(--ksh-wrap-radius, 22px);
        }}
        body.edit-mode .grid,
        body.edit-mode .pad-wrap,
        body.edit-mode .pad {{
          touch-action: none;
        }}
        .pad {{
          position: relative;
          overflow: hidden;
          width: 100%;
          min-height: var(--ksh-pad-height, {pad_min_height}px);
          aspect-ratio: 1 / 0.84;
          border: 1px solid rgba(62,216,255,.28);
          border-radius: var(--ksh-pad-radius, {pad_radius}px);
          background:
            linear-gradient(135deg, rgba(62,216,255,.08), rgba(255,92,199,.05)),
            var(--card);
          background-size: cover;
          background-position: center;
          background-repeat: no-repeat;
          color: var(--text);
          padding: var(--ksh-pad-padding, {pad_padding}px);
          text-align: left;
          box-shadow: inset 0 1px 0 rgba(255,255,255,.05), 0 14px 34px rgba(0,0,0,.30);
          touch-action: manipulation;
          backdrop-filter: blur(10px) saturate(1.25);
        }}
        .pad::before {{
          content: "";
          position: absolute;
          inset: 0;
          pointer-events: none;
          background: linear-gradient(135deg, rgba(255,255,255,.08), transparent 34%, rgba(62,216,255,.05));
          opacity: .70;
        }}
        .pad > * {{
          position: relative;
          z-index: 1;
        }}
        .pad.has-bg {{
          background-image:
            linear-gradient(135deg, rgba(5, 8, 15, .30), rgba(5, 8, 15, .76)),
            var(--pad-bg);
        }}
        .pad.has-bg span {{
          color: rgba(236, 247, 255, .82);
          text-shadow: 0 2px 8px rgba(0,0,0,.85);
        }}
        .pad.has-bg strong {{
          text-shadow: 0 2px 10px rgba(0,0,0,.92);
        }}
        .pad:active, .pad.sending {{
          transform: scale(.98);
          border-color: rgba(255,92,199,.88);
          background-color: var(--card-hover);
          box-shadow: inset 0 0 0 1px rgba(255,92,199,.22), 0 10px 28px rgba(255,92,199,.12);
        }}
        body.edit-mode .pad {{
          border-color: rgba(255,92,199,.58);
          cursor: grab;
        }}
        .pad:disabled {{
          opacity: .38;
        }}
        .pad strong {{
          display: block;
          font-size: var(--ksh-title-font, {pad_title_font}px);
          margin-bottom: var(--ksh-title-margin, {pad_title_margin}px);
        }}
        .pad span {{
          display: block;
          color: var(--muted);
          font-size: var(--ksh-subtitle-font, {pad_subtitle_font}px);
          word-break: break-word;
        }}
        .pad-wrap.drag-source .pad {{
          opacity: .58;
          border-color: rgba(255,92,199,1);
          box-shadow: 0 0 0 2px rgba(255,92,199,.20), 0 14px 34px rgba(0,0,0,.28);
          transform: scale(.98);
        }}
        .pad-wrap.click-source .pad {{
          border-color: rgba(255,92,199,1);
          box-shadow: 0 0 0 2px rgba(255,92,199,.24), 0 14px 34px rgba(0,0,0,.28);
          transform: scale(.99);
        }}
        .pad-wrap.drop-target .pad {{
          border-color: rgba(62,216,255,1);
          box-shadow: 0 0 0 2px rgba(62,216,255,.24), 0 14px 34px rgba(0,0,0,.28);
          transform: scale(1.01);
        }}
        .pad-wrap.drag-source::after,
        .pad-wrap.drop-target::after {{
          position: absolute;
          top: 8px;
          right: 8px;
          z-index: 4;
          min-width: 52px;
          padding: 4px 8px;
          border-radius: 999px;
          font-size: 10px;
          font-weight: 900;
          letter-spacing: .08em;
          text-align: center;
          box-shadow: 0 10px 20px rgba(0,0,0,.30);
        }}
        .pad-wrap.drag-source::after {{
          content: "SOURCE";
          color: #071018;
          background: rgba(255,92,199,.96);
        }}
        .pad-wrap.drop-target::after {{
          content: "TARGET";
          color: #071018;
          background: rgba(62,216,255,.96);
        }}
        .empty {{
          color: var(--muted);
        }}
        .bottom-bar {{
          position: fixed;
          left: 10px;
          right: 10px;
          bottom: 10px;
          z-index: 50;
          display: grid;
          grid-template-columns: 54px 54px minmax(0, 1fr) 54px;
          gap: 10px;
          align-items: center;
          padding: 10px 12px calc(10px + env(safe-area-inset-bottom));
          border: 1px solid rgba(62,216,255,.20);
          border-radius: 24px;
          background: var(--bar);
          backdrop-filter: blur(20px) saturate(1.35);
          box-shadow: 0 -10px 42px rgba(0,0,0,.44);
        }}
        .bottom-volume {{
          min-width: 0;
        }}
        .volume-line {{
          display: grid;
          grid-template-columns: auto 1fr auto;
          gap: 10px;
          align-items: center;
        }}
        .vol-icon {{
          font-size: 18px;
          line-height: 1;
        }}
        input[type="range"] {{
          width: 100%;
          accent-color: var(--cyan);
        }}
        #globalVolValue {{
          min-width: 42px;
          text-align: right;
          color: var(--cyan);
          font-weight: 800;
          font-size: 13px;
        }}
        .tiny {{
          color: var(--muted);
          font-size: 11px;
          margin-top: 4px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }}
        .edit-mini, .options-mini, .stop-mini {{
          width: 54px;
          height: 54px;
          border-radius: 18px;
          color: var(--text);
          font-size: 22px;
          line-height: 1;
          font-weight: 900;
          box-shadow: 0 12px 28px rgba(0,0,0,.32);
          touch-action: manipulation;
        }}
        .edit-mini {{
          border: 1px solid rgba(62,216,255,.62);
          background: rgba(9, 26, 35, .92);
        }}
        body.edit-mode .edit-mini {{
          border-color: rgba(255,92,199,.95);
          background: rgba(35, 9, 28, .92);
        }}
        .stop-mini {{
          border: 1px solid rgba(255,92,199,.62);
          background: rgba(35, 9, 28, .92);
          font-size: 24px;
        }}
        .edit-mini:active, .options-mini:active, .stop-mini:active {{
          transform: scale(.96);
        }}

        .disconnect-link {{
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-height: 42px;
          padding: 0 14px;
          border: 1px solid rgba(255, 92, 199, 0.58);
          border-radius: 999px;
          color: #ffe1f0;
          background: rgba(36, 14, 32, 0.72);
          text-decoration: none;
          font-weight: 800;
          letter-spacing: 0.02em;
          box-shadow: 0 10px 22px rgba(0,0,0,.28);
        }}
        .disconnect-link:active {{
          transform: scale(0.98);
        }}
        .remote-subtitle {{
          margin: 4px 0 0;
          color: rgba(236, 247, 255, 0.70);
          font-size: 0.76rem;
          letter-spacing: 0.12em;
          text-transform: uppercase;
        }}

        .folder-bar {{
          display: flex;
          gap: 9px;
          overflow-x: auto;
          padding: 2px 4px 12px;
          margin: 2px 0 12px;
          scrollbar-width: thin;
          position: relative;
          z-index: 2;
        }}
        .folder-pill {{
          min-height: 40px;
          border: 1px solid rgba(142,225,255,0.22);
          background:
            linear-gradient(135deg, rgba(255,255,255,.075), rgba(255,255,255,.035)),
            rgba(5, 10, 18, .58);
          color: rgba(236,247,255,0.90);
          border-radius: 999px;
          padding: 9px 15px;
          font-size: 13px;
          font-weight: 850;
          letter-spacing: .015em;
          white-space: nowrap;
          box-shadow: inset 0 1px 0 rgba(255,255,255,.09), 0 10px 24px rgba(0,0,0,.18);
          backdrop-filter: blur(12px) saturate(1.2);
        }}
        .folder-pill.active {{
          border-color: rgba(106,214,255,0.78);
          background:
            linear-gradient(135deg, rgba(62,216,255,.34), rgba(184,92,255,.22)),
            rgba(5, 12, 22, .74);
          color: #ffffff;
          box-shadow: inset 0 1px 0 rgba(255,255,255,.14), 0 12px 30px rgba(62,216,255,.12);
        }}
        .pad-wrap[hidden] {{
          display: none !important;
        }}

        body.contrast-high {{
          --text: #ffffff;
          --muted: rgba(225, 238, 255, .86);
          --line: rgba(142, 225, 255, .38);
          --card: rgba(8, 14, 26, .90);
          --card-hover: rgba(16, 32, 54, .94);
        }}
        body.contrast-soft {{
          --muted: rgba(204, 218, 235, .62);
          --line: rgba(142, 225, 255, .14);
          --card: rgba(13, 20, 34, .62);
          --card-hover: rgba(18, 30, 48, .70);
        }}
        body.remote-bg-clean {{
          background: linear-gradient(135deg, #040711, #07101d 52%, #040711);
        }}
        body.remote-bg-clean::before {{
          display: none;
        }}
        body.remote-bg-grid {{
          background:
            radial-gradient(circle at 16% -8%, rgba(62,216,255,.24), transparent 34%),
            radial-gradient(circle at 92% 8%, rgba(255,92,199,.18), transparent 30%),
            linear-gradient(135deg, #02040a, #07101d 48%, #05070d);
        }}
        body.remote-bg-dark {{
          background: #02040a;
        }}
        body.remote-bg-dark::before {{
          display: none;
        }}

        .options-panel {{
          position: relative;
          z-index: 12;
          border: 1px solid rgba(142, 225, 255, .18);
          border-radius: 24px;
          padding: 13px;
          margin: 0 0 14px;
          background:
            linear-gradient(135deg, rgba(10,16,29,.84), rgba(7,11,20,.68)),
            radial-gradient(circle at top left, rgba(62,216,255,.13), transparent 38%),
            radial-gradient(circle at top right, rgba(255,92,199,.10), transparent 34%);
          box-shadow: 0 18px 48px rgba(0,0,0,.30);
          backdrop-filter: blur(18px) saturate(1.25);
        }}
        .options-title {{
          font-size: 12px;
          font-weight: 900;
          letter-spacing: .14em;
          text-transform: uppercase;
          color: var(--cyan);
          margin-bottom: 10px;
        }}
        .options-grid {{
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(138px, 1fr));
          gap: 10px;
        }}
        .options-grid label {{
          display: grid;
          gap: 5px;
          color: var(--muted);
          font-size: 11px;
          font-weight: 800;
          letter-spacing: .06em;
          text-transform: uppercase;
        }}
        .options-grid select {{
          width: 100%;
          min-height: 42px;
          border: 1px solid rgba(142, 225, 255, .22);
          border-radius: 14px;
          color: var(--text);
          background: rgba(2, 6, 12, .86);
          padding: 0 10px;
          font-weight: 800;
          outline: none;
        }}
        .options-grid select:focus {{
          border-color: rgba(62,216,255,.70);
          box-shadow: 0 0 0 2px rgba(62,216,255,.12);
        }}

        .options-mini {{
          border: 1px solid rgba(142,225,255,.42);
          background: rgba(9, 26, 35, .78);
        }}
        body.options-open .options-mini {{
          border-color: rgba(62,216,255,.95);
          background: rgba(14, 42, 62, .92);
        }}

        body.folder-size-large .folder-pill {{
          min-height: 48px;
          padding: 11px 18px;
          font-size: 15px;
        }}
        body.folder-size-xl .folder-pill {{
          min-height: 54px;
          padding: 12px 22px;
          font-size: 16px;
          letter-spacing: .025em;
        }}
        body.folder-style-tabs .folder-bar {{
          gap: 8px;
          padding: 3px 4px 13px;
          border-bottom: 1px solid rgba(142,225,255,.10);
        }}
        body.folder-style-tabs .folder-pill {{
          border-radius: 15px;
          background:
            linear-gradient(180deg, rgba(255,255,255,.075), rgba(255,255,255,.025)),
            rgba(5, 10, 18, .60);
        }}
        body.folder-style-tabs .folder-pill.active {{
          border-color: rgba(62,216,255,.82);
          box-shadow: inset 0 -2px 0 rgba(62,216,255,.72), 0 12px 30px rgba(62,216,255,.10);
        }}

</style>
    </head>
    <body class="{html.escape(body_classes, quote=True)}">
      <header>
        <div class="brand-row">
          <div class="brand-mark">K</div>
          <div class="brand-title">
            <h1>K-SOUNDS</h1>
            <p class="remote-subtitle">Soundboard Remote</p>
          </div>
          <a class="disconnect-link" href="ksounds://disconnect">Disconnect</a>
        </div>
        <div class="hint">Local Android remote. Secure LAN pairing.</div>
        <div id="remoteStatus" class="status">{initial_status}</div>
      </header>

      <section id="remoteOptionsPanel" class="options-panel" hidden>
        <div class="options-title">Remote Options</div>
        <div class="options-grid">
          <label>
            <span>Contrast</span>
            <select onchange="saveRemoteOption('remote_contrast', this.value)">
              <option value="normal"{option_selected(remote_contrast, "normal")}>Normal</option>
              <option value="high"{option_selected(remote_contrast, "high")}>High</option>
              <option value="soft"{option_selected(remote_contrast, "soft")}>Soft</option>
            </select>
          </label>
          <label>
            <span>Background</span>
            <select onchange="saveRemoteOption('remote_background', this.value)">
              <option value="glass"{option_selected(remote_background, "glass")}>Glass</option>
              <option value="clean"{option_selected(remote_background, "clean")}>Clean</option>
              <option value="grid"{option_selected(remote_background, "grid")}>Grid</option>
              <option value="dark"{option_selected(remote_background, "dark")}>Dark</option>
            </select>
          </label>
          <label>
            <span>Folders</span>
            <select onchange="saveRemoteOption('remote_folder_size', this.value)">
              <option value="normal"{option_selected(remote_folder_size, "normal")}>Normal</option>
              <option value="large"{option_selected(remote_folder_size, "large")}>Large</option>
              <option value="xl"{option_selected(remote_folder_size, "xl")}>XL</option>
            </select>
          </label>
          <label>
            <span>Folder style</span>
            <select onchange="saveRemoteOption('remote_folder_style', this.value)">
              <option value="pills"{option_selected(remote_folder_style, "pills")}>Pills</option>
              <option value="tabs"{option_selected(remote_folder_style, "tabs")}>Tabs</option>
            </select>
          </label>
        </div>
      </section>

      {folder_bar_html}

      <main id="padsGrid" class="grid">
        {''.join(buttons)}
      </main>

      <section class="bottom-bar" aria-label="Soundboard controls">
        <button id="editButton" class="edit-mini" type="button" onclick="toggleEditMode()" title="Edit" aria-label="Edit">✎</button>
        <button id="optionsButton" class="options-mini" type="button" onclick="toggleOptionsPanel()" title="Options" aria-label="Options">⚙</button>
        <div class="bottom-volume">
          <div class="volume-line">
            <span class="vol-icon">🔊</span>
            <input
              id="globalVolumeSlider"
              type="range"
              min="0"
              max="100"
              name="volume"
              value="{global_volume}"
              oninput="scheduleVolumeUpdate(this.value)"
              onchange="sendVolumeNow(this.value)"
            >
            <span id="globalVolValue">{global_volume}%</span>
          </div>
          <span id="volumeSendState" style="display:none">Ready</span>
        </div>
        <button class="stop-mini" type="button" onclick="stopAllSounds()" title="Stop all" aria-label="Stop all">■</button>
      </section>

      <script>
        let volumeTimer = null;
        let lastSentVolume = "{global_volume}";
        let volumeDragging = false;
        let editMode = window.sessionStorage.getItem("ksoundSoundboardEditMode") === "1";
        let lastEditToggleAt = 0;
        let dragState = null;
        let clickDropSourceWrap = null;
        let activePointers = new Map();
        let pinchState = null;
        let pinchRaf = 0;
        let pendingPreviewColumns = null;
        let gestureCooldownUntil = 0;
        let layoutSaveTimer = null;
        let serverColumns = Number("{remote_columns}");
        let storedColumns = Number(window.localStorage.getItem("ksoundSoundboardColumns") || "0");
        let currentColumns = storedColumns || serverColumns || 0;
        let soundboardRevision = "{config_revision}";
        let refreshInFlight = false;

        function setRemoteStatus(text) {{
          const node = document.getElementById("remoteStatus");
          if (node) node.textContent = text;
        }}

        function setVolumeState(text) {{
          const node = document.getElementById("volumeSendState");
          if (node) node.textContent = text;
        }}

        function saveScrollPositionForReload() {{
          try {{
            const y = Math.max(
              0,
              Number(window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0)
            );
            window.sessionStorage.setItem("ksoundSoundboardScrollY", String(y));
          }} catch (_error) {{}}
        }}

        function restoreScrollPositionAfterReload() {{
          let y = null;

          try {{
            if ("scrollRestoration" in history) {{
              history.scrollRestoration = "manual";
            }}

            const raw = window.sessionStorage.getItem("ksoundSoundboardScrollY");
            if (raw !== null) {{
              window.sessionStorage.removeItem("ksoundSoundboardScrollY");
              y = Math.max(0, Number(raw) || 0);
            }}
          }} catch (_error) {{
            y = null;
          }}

          if (y === null) return;

          const restore = () => window.scrollTo(0, y);
          requestAnimationFrame(restore);
          window.setTimeout(restore, 80);
          window.setTimeout(restore, 260);
        }}

        function padWraps() {{
          return Array.from(document.querySelectorAll(".pad-wrap"));
        }}

        function refreshPadIndexes() {{
          padWraps().forEach((node, index) => {{
            node.dataset.index = String(index);
          }});
        }}

        function orderPayload() {{
          return JSON.stringify(
            padWraps()
              .map(node => node.dataset.slot || "")
              .filter(Boolean)
          );
        }}

        function clearDropTargets() {{
          padWraps().forEach(node => node.classList.remove("drop-target"));
        }}

        function clearDragStateClasses() {{
          padWraps().forEach(node => node.classList.remove("drag-source", "drop-target"));
        }}

        function labelOfWrap(wrap) {{
          if (!wrap) return "";
          return wrap.dataset.label || wrap.dataset.slot || "";
        }}

        function clampColumns(value) {{
          const n = Math.round(Number(value) || 4);
          return Math.max(1, Math.min(8, n));
        }}

        function clampColumnsFloat(value) {{
          const n = Number(value) || 4;
          return Math.max(1, Math.min(8, n));
        }}

        function estimateColumns() {{
          const wraps = padWraps();
          if (!wraps.length) return clampColumns(currentColumns || 4);

          const firstTop = wraps[0].offsetTop;
          let count = 0;
          for (const wrap of wraps) {{
            if (Math.abs(wrap.offsetTop - firstTop) <= 4) count += 1;
            else break;
          }}
          return clampColumns(count || currentColumns || 4);
        }}

        function visualScaleForColumns(columns) {{
          const safeColumns = clampColumnsFloat(columns);

          const points = [
            [1, 2.00],
            [2, 1.62],
            [3, 1.28],
            [4, 1.00],
            [5, 0.88],
            [6, 0.78],
            [7, 0.70],
            [8, 0.64]
          ];

          if (safeColumns <= points[0][0]) return points[0][1];
          if (safeColumns >= points[points.length - 1][0]) return points[points.length - 1][1];

          for (let i = 0; i < points.length - 1; i++) {{
            const left = points[i];
            const right = points[i + 1];

            if (safeColumns >= left[0] && safeColumns <= right[0]) {{
              const t = (safeColumns - left[0]) / (right[0] - left[0]);
              return left[1] + ((right[1] - left[1]) * t);
            }}
          }}

          return 1.0;
        }}

        function applyPadVisualScale(columns) {{
          const factor = visualScaleForColumns(columns);

          const rootStyle = document.documentElement.style;
          rootStyle.setProperty("--ksh-pad-gap", Math.round(9 * factor) + "px");
          rootStyle.setProperty("--ksh-pad-height", Math.round(108 * factor) + "px");
          rootStyle.setProperty("--ksh-pad-padding", Math.round(14 * factor) + "px");
          rootStyle.setProperty("--ksh-pad-radius", Math.round(20 * factor) + "px");
          rootStyle.setProperty("--ksh-wrap-radius", Math.round(22 * factor) + "px");
          rootStyle.setProperty("--ksh-title-font", Math.max(12, Math.round(17 * factor)) + "px");
          rootStyle.setProperty("--ksh-subtitle-font", Math.max(10, Math.round(12 * factor)) + "px");
          rootStyle.setProperty("--ksh-title-margin", Math.max(4, Math.round(8 * factor)) + "px");
        }}

        function setGridColumns(columns) {{
          currentColumns = clampColumns(columns);
          const grid = document.getElementById("padsGrid");
          if (grid) {{
            grid.style.gridTemplateColumns = "repeat(" + currentColumns + ", minmax(0, 1fr))";
          }}
        }}

        function saveColumnsToServer(columns) {{
          const safeColumns = clampColumns(columns);

          if (layoutSaveTimer) {{
            clearTimeout(layoutSaveTimer);
          }}

          layoutSaveTimer = window.setTimeout(() => {{
            fetch("/layout?token={escaped_token}", {{
              method: "POST",
              headers: {{
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "fetch"
              }},
              body: "columns=" + encodeURIComponent(String(safeColumns))
            }}).catch(() => {{}});
          }}, 120);
        }}

        function applyColumns(columns, persist = true, visualColumns = null) {{
          setGridColumns(columns);
          applyPadVisualScale(visualColumns === null ? currentColumns : visualColumns);

          if (persist) {{
            window.localStorage.setItem("ksoundSoundboardColumns", String(currentColumns));
            saveColumnsToServer(currentColumns);
          }}
        }}

        function pointerDistance(a, b) {{
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          return Math.hypot(dx, dy);
        }}

        function updatePointer(event) {{
          if (activePointers.has(event.pointerId)) {{
            activePointers.set(event.pointerId, {{ x: event.clientX, y: event.clientY }});
          }}
        }}

        function clearPinchPreview() {{
          if (pinchRaf) {{
            cancelAnimationFrame(pinchRaf);
            pinchRaf = 0;
          }}

          pendingPreviewColumns = null;

          const grid = document.getElementById("padsGrid");
          if (grid) {{
            grid.style.transform = "";
            grid.style.transformOrigin = "top center";
          }}
        }}

        function schedulePinchPreview(_rawColumns) {{
          // Discrete mode: no continuous GPU transform preview.
          // The grid only switches when the rounded column state changes.
          return;
        }}

        function releaseDragCapture() {{
          if (!dragState || !dragState.wrap) return;

          try {{
            dragState.wrap.releasePointerCapture?.(dragState.pointerId);
          }} catch (_error) {{}}
        }}

        function finishPinch(commit = true) {{
          if (!pinchState) {{
            activePointers.clear();
            clearPinchPreview();
            return false;
          }}

          const commitColumns = clampColumns(pinchState.commitColumns || currentColumns || estimateColumns());

          pinchState = null;
          activePointers.clear();
          releaseDragCapture();
          dragState = null;
          clearDragStateClasses();
          clearPinchPreview();

          if (commit) {{
            applyColumns(commitColumns, true);
            setRemoteStatus("Grid: " + commitColumns + " per row");
          }}

          gestureCooldownUntil = Date.now() + 260;
          return true;
        }}

        function hardResetGesture(message = "") {{
          if (pinchState) {{
            finishPinch(true);
          }} else {{
            activePointers.clear();
            releaseDragCapture();
            dragState = null;
            clearDragStateClasses();
            clearClickDropSelection();
            clearPinchPreview();
          }}

          if (message) setRemoteStatus(message);
        }}

        function startPinchIfReady() {{
          if (!editMode || activePointers.size < 2) return false;

          const points = Array.from(activePointers.values()).slice(0, 2);
          const distance = pointerDistance(points[0], points[1]);
          if (distance <= 0) return false;

          const startColumns = currentColumns ? clampColumns(currentColumns) : estimateColumns();

          releaseDragCapture();

          pinchState = {{
            startDistance: distance,
            startColumns: startColumns,
            startScale: visualScaleForColumns(startColumns),
            commitColumns: startColumns
          }};

          dragState = null;
          clearDragStateClasses();
          setRemoteStatus("Edit mode: pinch to resize grid");
          return true;
        }}

        function updatePinchColumns() {{
          if (!pinchState || activePointers.size < 2) return false;

          const points = Array.from(activePointers.values()).slice(0, 2);
          const distance = pointerDistance(points[0], points[1]);
          if (distance <= 0 || pinchState.startDistance <= 0) return true;

          const ratio = distance / pinchState.startDistance;
          const rawColumns = clampColumnsFloat(pinchState.startColumns / ratio);
          const nextColumns = clampColumns(rawColumns);

          // Important: only change layout when the discrete 8..1 state changes.
          // No transform scale, no frame-by-frame CSS spam, no localStorage writes here.
          if (nextColumns !== pinchState.commitColumns) {{
            pinchState.commitColumns = nextColumns;
            applyColumns(nextColumns, false);
            setRemoteStatus("Grid target: " + nextColumns + " per row");
          }}

          return true;
        }}

        function swapNodes(firstIndex, secondIndex) {{
          const wraps = padWraps();
          const a = wraps[firstIndex];
          const b = wraps[secondIndex];
          if (!a || !b || a === b) return false;

          const parent = a.parentNode;
          if (a.nextSibling === b) {{
            parent.insertBefore(b, a);
          }} else if (b.nextSibling === a) {{
            parent.insertBefore(a, b);
          }} else {{
            const aNext = a.nextSibling;
            parent.insertBefore(a, b);
            parent.insertBefore(b, aNext);
          }}
          refreshPadIndexes();
          return true;
        }}

        async function saveCurrentOrder() {{
          return postAction(
            "/reorder",
            "order=" + encodeURIComponent(orderPayload()),
            "Order saved"
          );
        }}

        function applyEditModeVisuals() {{
          document.body.classList.toggle("edit-mode", editMode);

          const editButton = document.getElementById("editButton");
          if (editButton) {{
            editButton.textContent = editMode ? "✓" : "✎";
            editButton.setAttribute("aria-pressed", editMode ? "true" : "false");
          }}
        }}

        function setEditMode(enabled, announce = true) {{
          editMode = Boolean(enabled);

          try {{
            window.sessionStorage.setItem("ksoundSoundboardEditMode", editMode ? "1" : "0");
          }} catch (_error) {{}}

          hardResetGesture();
          applyEditModeVisuals();

          if (announce) {{
            setRemoteStatus(editMode ? "Edit mode: drag, tap source then target, or pinch to resize" : "Ready");
          }}

          if (!editMode) {{
            window.setTimeout(refreshSettingsFromServer, 80);
          }}
        }}

        function toggleEditMode() {{
          const now = Date.now();

          // Some Android WebViews can emit duplicate click/tap events.
          // Edit must behave as a manual toggle, not flicker ON then OFF.
          if (now - lastEditToggleAt < 350) {{
            return;
          }}

          lastEditToggleAt = now;
          setEditMode(!editMode, true);
        }}

        async function postAction(path, body, okText) {{
          try {{
            const response = await fetch(path + "?token={escaped_token}", {{
              method: "POST",
              headers: {{
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "fetch"
              }},
              body: body || ""
            }});
            if (!response.ok) throw new Error("HTTP " + response.status);
            setRemoteStatus(okText);
            return true;
          }} catch (error) {{
            setRemoteStatus("Send error");
            return false;
          }}
        }}

        function playSlotFromButton(button) {{
          if (editMode) {{
            return;
          }}

          if (pinchState || activePointers.size > 0 || Date.now() < gestureCooldownUntil) {{
            setRemoteStatus("Gesture active");
            return;
          }}

          const slot = button.dataset.slot || "";
          if (!slot || button.disabled) return;
          button.classList.add("sending");
          window.setTimeout(() => button.classList.remove("sending"), 140);
          postAction("/play", "slot=" + encodeURIComponent(slot), "Play " + slot + " sent");
        }}

        function dragTargetFromPoint(clientX, clientY) {{
          const element = document.elementFromPoint(clientX, clientY);
          if (!element) return null;
          return element.closest(".pad-wrap");
        }}

        function pointerIsInsidePadsGrid(event) {{
          const target = event.target;
          return Boolean(target && target.closest && target.closest("#padsGrid"));
        }}

        function cancelPointerEvent(event) {{
          event.preventDefault();
          event.stopPropagation();
          event.stopImmediatePropagation?.();
        }}

        function forcePinchPriority(event) {{
          activePointers.set(event.pointerId, {{ x: event.clientX, y: event.clientY }});

          if (activePointers.size < 2) {{
            return false;
          }}

          releaseDragCapture();
          dragState = null;
          clearDragStateClasses();

          if (!pinchState) {{
            startPinchIfReady();
          }}

          updatePinchColumns();
          cancelPointerEvent(event);
          return true;
        }}

        function onGlobalPointerDown(event) {{
          if (!editMode) return;
          if (event.button !== undefined && event.button !== 0) return;

          // First finger must start on the pads grid.
          // Once one finger is already active, any second finger immediately becomes pinch.
          if (!pointerIsInsidePadsGrid(event) && activePointers.size === 0) {{
            return;
          }}

          if (Date.now() < gestureCooldownUntil) {{
            cancelPointerEvent(event);
            return;
          }}

          forcePinchPriority(event);
        }}

        function syncActivePointersFromTouches(touches) {{
          activePointers.clear();

          for (let i = 0; i < touches.length; i++) {{
            const touch = touches[i];
            activePointers.set("touch-" + i, {{ x: touch.clientX, y: touch.clientY }});
          }}
        }}

        function forceTouchPinchPriority(event) {{
          if (!editMode) return false;
          if (!event.touches || event.touches.length < 2) return false;

          syncActivePointersFromTouches(event.touches);

          releaseDragCapture();
          dragState = null;
          clearDragStateClasses();

          if (!pinchState) {{
            startPinchIfReady();
          }}

          updatePinchColumns();
          cancelPointerEvent(event);
          return true;
        }}

        function onGlobalTouchStart(event) {{
          if (!editMode) return;

          // Android/WebView fallback:
          // as soon as two fingers exist, pinch wins over pad press/drag/click.
          forceTouchPinchPriority(event);
        }}

        function onGlobalTouchMove(event) {{
          if (!editMode) return;

          if (event.touches && event.touches.length >= 2) {{
            forceTouchPinchPriority(event);
            return;
          }}

          if (pinchState) {{
            finishPinch(true);
            cancelPointerEvent(event);
          }}
        }}

        function onGlobalTouchEnd(event) {{
          if (!editMode) return;

          if (event.touches && event.touches.length >= 2) {{
            forceTouchPinchPriority(event);
            return;
          }}

          if (pinchState) {{
            finishPinch(true);
            cancelPointerEvent(event);
            return;
          }}

          if (!event.touches || event.touches.length === 0) {{
            activePointers.clear();
          }}
        }}

        function onGlobalClick(event) {{
          if (!editMode) return;

          // Prevent delayed synthetic clicks after a pinch/gesture.
          if (pinchState || activePointers.size >= 2 || Date.now() < gestureCooldownUntil) {{
            cancelPointerEvent(event);
          }}
        }}

        function clearClickDropSelection() {{
          padWraps().forEach(node => node.classList.remove("click-source"));
          clickDropSourceWrap = null;
        }}

        function setClickDropSelection(wrap) {{
          clearClickDropSelection();

          if (!wrap) return;

          clickDropSourceWrap = wrap;
          wrap.classList.add("click-source");
          setRemoteStatus("Selected: " + labelOfWrap(wrap) + " → tap destination");
        }}

        async function handleClickDropTap(wrap) {{
          if (!editMode || !wrap) return false;

          // Pinch always wins over tap/drop.
          if (pinchState || activePointers.size >= 2 || Date.now() < gestureCooldownUntil) {{
            return false;
          }}

          if (!clickDropSourceWrap) {{
            setClickDropSelection(wrap);
            return true;
          }}

          if (clickDropSourceWrap === wrap) {{
            clearClickDropSelection();
            setRemoteStatus("Selection cleared");
            return true;
          }}

          const wraps = padWraps();
          const sourceIndex = wraps.indexOf(clickDropSourceWrap);
          const targetIndex = wraps.indexOf(wrap);
          const sourceLabel = labelOfWrap(clickDropSourceWrap);
          const targetLabel = labelOfWrap(wrap);

          clearClickDropSelection();

          if (sourceIndex < 0 || targetIndex < 0 || sourceIndex === targetIndex) {{
            setRemoteStatus("Drop unavailable");
            return true;
          }}

          if (swapNodes(sourceIndex, targetIndex)) {{
            setRemoteStatus("Drop: " + sourceLabel + " → " + targetLabel);
            const ok = await saveCurrentOrder();
            if (!ok) location.reload();
          }}

          return true;
        }}

        function onPadPointerDown(event) {{
          if (!editMode) return;
          if (event.button !== undefined && event.button !== 0) return;

          if (Date.now() < gestureCooldownUntil) {{
            cancelPointerEvent(event);
            return;
          }}

          activePointers.set(event.pointerId, {{ x: event.clientX, y: event.clientY }});

          if (activePointers.size >= 2) {{
            forcePinchPriority(event);
            return;
          }}

          const wrap = event.currentTarget;
          dragState = {{
            wrap,
            pointerId: event.pointerId,
            startX: event.clientX,
            startY: event.clientY,
            active: false,
            target: null
          }};

          try {{
            wrap.setPointerCapture?.(event.pointerId);
          }} catch (_error) {{}}

          event.preventDefault();
        }}

        function onPadPointerMove(event) {{
          if (!editMode) return;

          updatePointer(event);

          if (pinchState || activePointers.size >= 2) {{
            releaseDragCapture();
            dragState = null;
            clearDragStateClasses();

            if (!pinchState) startPinchIfReady();
            updatePinchColumns();

            cancelPointerEvent(event);
            return;
          }}

          if (!dragState || dragState.pointerId !== event.pointerId) return;

          const dx = event.clientX - dragState.startX;
          const dy = event.clientY - dragState.startY;
          if (!dragState.active && Math.hypot(dx, dy) < 10) return;

          dragState.active = true;
          clearClickDropSelection();
          clearDragStateClasses();

          dragState.wrap.classList.add("drag-source");

          const target = dragTargetFromPoint(event.clientX, event.clientY);
          if (target && target !== dragState.wrap) {{
            target.classList.add("drop-target");
            dragState.target = target;
            setRemoteStatus("Move: " + labelOfWrap(dragState.wrap) + " → " + labelOfWrap(target));
          }} else {{
            dragState.target = null;
            setRemoteStatus("Moving: " + labelOfWrap(dragState.wrap));
          }}

          event.preventDefault();
        }}

        async function onPadPointerUp(event) {{
          activePointers.delete(event.pointerId);

          if (pinchState) {{
            if (activePointers.size < 2) {{
              finishPinch(true);
            }} else {{
              updatePinchColumns();
            }}

            cancelPointerEvent(event);
            return;
          }}

          if (!dragState || dragState.pointerId !== event.pointerId) return;

          const state = dragState;
          dragState = null;

          try {{
            state.wrap.releasePointerCapture?.(event.pointerId);
          }} catch (_error) {{}}

          clearDragStateClasses();

          if (!editMode) {{
            setRemoteStatus("Ready");
            event.preventDefault();
            return;
          }}

          if (!state.active) {{
            await handleClickDropTap(state.wrap);
            event.preventDefault();
            return;
          }}

          if (!state.target || state.target === state.wrap) {{
            setRemoteStatus("Edit mode: drag, tap source then target, or pinch to resize");
            event.preventDefault();
            return;
          }}

          const wraps = padWraps();
          const sourceIndex = wraps.indexOf(state.wrap);
          const targetIndex = wraps.indexOf(state.target);

          if (sourceIndex >= 0 && targetIndex >= 0 && swapNodes(sourceIndex, targetIndex)) {{
            const ok = await saveCurrentOrder();
            if (!ok) location.reload();
          }}

          event.preventDefault();
        }}

        function onPadPointerCancel(event) {{
          activePointers.delete(event.pointerId);

          if (pinchState) {{
            finishPinch(true);
            cancelPointerEvent(event);
            return;
          }}

          if (dragState && dragState.pointerId === event.pointerId) {{
            releaseDragCapture();
            dragState = null;
            clearDragStateClasses();
            setRemoteStatus(editMode ? "Edit mode: drag, tap source then target, or pinch to resize" : "Ready");
          }}

          event.preventDefault();
        }}

        function initDragReorder() {{
          window.addEventListener("pointerdown", onGlobalPointerDown, {{ passive: false, capture: true }});
          window.addEventListener("touchstart", onGlobalTouchStart, {{ passive: false, capture: true }});
          window.addEventListener("touchmove", onGlobalTouchMove, {{ passive: false, capture: true }});
          window.addEventListener("touchend", onGlobalTouchEnd, {{ passive: false, capture: true }});
          window.addEventListener("touchcancel", onGlobalTouchEnd, {{ passive: false, capture: true }});
          window.addEventListener("click", onGlobalClick, {{ passive: false, capture: true }});

          padWraps().forEach(wrap => {{
            wrap.addEventListener("pointerdown", onPadPointerDown, {{ passive: false }});
            wrap.addEventListener("lostpointercapture", onPadPointerCancel, {{ passive: false }});
          }});

          window.addEventListener("pointermove", onPadPointerMove, {{ passive: false }});
          window.addEventListener("pointerup", onPadPointerUp, {{ passive: false }});
          window.addEventListener("pointercancel", onPadPointerCancel, {{ passive: false }});
          window.addEventListener("blur", () => hardResetGesture("Ready"));

          document.addEventListener("visibilitychange", () => {{
            if (document.hidden) {{
              hardResetGesture("Ready");
            }} else {{
              refreshSettingsFromServer();
            }}
          }});
        }}


        async function refreshSettingsFromServer() {{
          if (refreshInFlight) return;
          if (editMode) return;
          if (pinchState || activePointers.size > 0) return;

          refreshInFlight = true;

          try {{
            const response = await fetch("/state?token={escaped_token}&v=" + Date.now(), {{
              method: "GET",
              cache: "no-store",
              headers: {{ "X-Requested-With": "fetch" }}
            }});
            if (!response.ok) return;

            const data = await response.json();
            const revision = String((data && data.revision) || "");

            if (revision && soundboardRevision && revision !== soundboardRevision) {{
              setRemoteStatus("Refreshing...");
              saveScrollPositionForReload();
              window.location.replace("/?token={escaped_token}&v=" + Date.now());
              return;
            }}

            if (revision) {{
              soundboardRevision = revision;
            }}

            if (!volumeDragging && !volumeTimer && data && Number.isFinite(Number(data.global_volume))) {{
              const volume = String(Math.max(0, Math.min(100, Number(data.global_volume))));
              const slider = document.getElementById("globalVolumeSlider");
              const valueNode = document.getElementById("globalVolValue");

              if (slider && String(slider.value) !== volume) {{
                slider.value = volume;
              }}
              if (valueNode) {{
                valueNode.textContent = volume + "%";
              }}
              lastSentVolume = volume;
            }}
          }} catch (_error) {{
            // Keep the remote usable even if polling fails.
          }} finally {{
            refreshInFlight = false;
          }}
        }}
        function toggleOptionsPanel() {{
          const panel = document.getElementById("remoteOptionsPanel");
          if (!panel) return;
          const open = panel.hasAttribute("hidden");
          if (open) {{
            panel.removeAttribute("hidden");
          }} else {{
            panel.setAttribute("hidden", "");
          }}
          document.body.classList.toggle("options-open", open);
          window.sessionStorage.setItem("ksoundRemoteOptionsOpen", open ? "1" : "0");
        }}

        function restoreOptionsPanelState() {{
          const panel = document.getElementById("remoteOptionsPanel");
          if (!panel) return;
          const open = window.sessionStorage.getItem("ksoundRemoteOptionsOpen") === "1";
          if (open) {{
            panel.removeAttribute("hidden");
            document.body.classList.add("options-open");
          }}
        }}

        function saveRemoteOption(key, value) {{
          setRemoteStatus("Saving option...");
          fetch("/settings?token={escaped_token}", {{
            method: "POST",
            headers: {{
              "Content-Type": "application/x-www-form-urlencoded",
              "X-Requested-With": "fetch"
            }},
            body: "key=" + encodeURIComponent(key) + "&value=" + encodeURIComponent(value)
          }})
          .then(response => {{
            if (!response.ok) throw new Error("HTTP " + response.status);
            return response.json();
          }})
          .then(() => {{
            setRemoteStatus("Option saved");
            window.location.replace("/?token={escaped_token}&v=" + Date.now());
          }})
          .catch(() => {{
            setRemoteStatus("Option save error");
          }});
        }}

        function stopAllSounds() {{
          postAction("/stop", "", "Stop all sent");
        }}

        function scheduleVolumeUpdate(value) {{
          document.getElementById("globalVolValue").textContent = value + "%";
          setVolumeState("Pending...");
          if (volumeTimer) clearTimeout(volumeTimer);
          volumeTimer = setTimeout(() => sendVolumeNow(value), 180);
        }}

        function sendVolumeNow(value) {{
          document.getElementById("globalVolValue").textContent = value + "%";
          if (volumeTimer) {{
            clearTimeout(volumeTimer);
            volumeTimer = null;
          }}
          if (String(value) === String(lastSentVolume)) {{
            setVolumeState("Ready");
            return;
          }}
          lastSentVolume = String(value);
          setVolumeState("Sending...");

          fetch("/volume?token={escaped_token}", {{
            method: "POST",
            headers: {{
              "Content-Type": "application/x-www-form-urlencoded",
              "X-Requested-With": "fetch"
            }},
            body: "volume=" + encodeURIComponent(value)
          }})
          .then(response => {{
            if (!response.ok) throw new Error("HTTP " + response.status);
            setVolumeState("Saved");
          }})
          .catch(() => {{
            setVolumeState("Send error");
          }});
        }}

        const volumeSlider = document.getElementById("globalVolumeSlider");
        if (volumeSlider) {{
          volumeSlider.addEventListener("pointerdown", () => {{ volumeDragging = true; }});
          volumeSlider.addEventListener("pointerup", () => {{
            volumeDragging = false;
            refreshSettingsFromServer();
          }});
          volumeSlider.addEventListener("touchend", () => {{
            volumeDragging = false;
            refreshSettingsFromServer();
          }});
        }}

        let storedFolder = window.sessionStorage.getItem("ksoundSoundboardFolderV2");
        let activeFolder = storedFolder === null ? "__all__" : storedFolder;

        function normalizeFolderValue(value) {{
          return String(value || "").trim().toLowerCase();
        }}

        function currentVisiblePadCount() {{
          return padWraps().filter(node => !node.hidden).length;
        }}

        function updateVisiblePadDensity() {{
          const count = currentVisiblePadCount();
          document.body.classList.toggle("visible-one", count === 1);
          document.body.classList.toggle("visible-few", count > 0 && count <= 2);
        }}

        function applyFolderFilter() {{
          const active = normalizeFolderValue(activeFolder);
          const showAll = active === "__all__";

          document.querySelectorAll(".folder-pill").forEach(button => {{
            const rawValue = button.dataset.folder || "";
            const value = normalizeFolderValue(rawValue);
            const isAllButton = value === "__all__";

            button.classList.toggle("active", showAll ? isAllButton : value === active);
          }});

          padWraps().forEach(wrap => {{
            const folder = normalizeFolderValue(wrap.dataset.folder || "");
            wrap.hidden = !showAll && folder !== active;
          }});

          updateVisiblePadDensity();

          const count = currentVisiblePadCount();
          if (count === 0) {{
            setRemoteStatus("No sounds in this folder");
          }} else if (editMode) {{
            setRemoteStatus("Edit mode: drag, tap source then target, or pinch to resize");
          }} else {{
            setRemoteStatus("Ready");
          }}
        }}

        function selectFolder(value) {{
          activeFolder = String(value || "").trim();
          window.sessionStorage.setItem("ksoundSoundboardFolderV2", activeFolder);
          applyFolderFilter();

          const label = activeFolder === "__all__" ? "All" : (activeFolder || "Main");
          setRemoteStatus("Folder: " + label);
        }}

        function initFolderButtons() {{
          document.querySelectorAll(".folder-pill").forEach(button => {{
            button.addEventListener("click", () => selectFolder(button.dataset.folder || ""));
          }});
        }}

        refreshPadIndexes();
        initFolderButtons();
        applyFolderFilter();
        restoreOptionsPanelState();
        if (currentColumns) {{
          applyColumns(currentColumns);
        }} else {{
          applyPadVisualScale(estimateColumns());
        }}
        initDragReorder();
        setEditMode(editMode, false);
        restoreScrollPositionAfterReload();
        window.setInterval(refreshSettingsFromServer, 750);
        window.setTimeout(refreshSettingsFromServer, 250);
      </script>
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
        mark_remote_activity(parsed.path)

        # Pairing must be reachable without the normal web token.
        # Always answer JSON so the Android app never tries to parse plain
        # "Forbidden" as a JSONObject.
        if parsed.path == "/api/pair":
            query = parse_qs(parsed.query)
            pin = query.get("pin", [""])[0].strip()

            if not pin:
                json_response(self, 400, {"ok": False, "error": "Missing pairing code"})
                return

            if consume_pairing_if_pin_matches(pin):
                json_response(self, 200, {"ok": True, "token": TOKEN})
                return

            json_response(self, 403, {"ok": False, "error": "Invalid or expired pairing code"})
            return

        if not self._token_ok():
            json_response(self, 403, {"ok": False, "error": "Forbidden"})
            return

        if parsed.path == "/background":
            query = parse_qs(parsed.query)
            slot_id = query.get("slot", [""])[0].strip()
            slot = next((item for item in read_slots() if str(item.get("id", "")) == slot_id), None)

            if slot is None:
                json_response(self, 404, {"ok": False, "error": "Background slot not found"})
                return

            image_path = Path(str(slot.get("background_path") or "")).expanduser()
            if not image_path.is_file():
                json_response(self, 404, {"ok": False, "error": "Background not found"})
                return

            mime_type = mimetypes.guess_type(str(image_path))[0] or "application/octet-stream"
            if not mime_type.startswith("image/"):
                json_response(self, 415, {"ok": False, "error": "Unsupported background type"})
                return

            try:
                data = image_path.read_bytes()
            except Exception as exc:
                json_response(self, 500, {"ok": False, "error": str(exc)})
                return

            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if parsed.path == "/state":
            json_response(self, 200, read_soundboard_state())
            return

        if parsed.path == "/settings":
            json_response(self, 200, read_soundboard_settings())
            return

        self._send_page()


    def do_POST(self) -> None:
        mark_remote_activity("POST")
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
            self._send_page(f"Play {slot}: {msg if not ok else 'sent'}")
            return

        if parsed.path == "/stop":
            ok, msg = send_ipc({"command": "soundboard-stop-all"})
            self._send_page(f"Stop all: {msg if not ok else 'sent'}")
            return

        if parsed.path == "/reorder":
            raw_order = form.get("order", ["[]"])[0]
            try:
                order = json.loads(raw_order)
            except Exception:
                order = []
            ok, msg = send_ipc({
                "command": "soundboard-reorder-slots",
                "order": order,
            })
            self._send_page(f"Reorder: {msg if not ok else 'sent'}")
            return

        if parsed.path == "/move":
            slot = form.get("slot", [""])[0]
            direction = form.get("direction", [""])[0]
            ok, msg = send_ipc({
                "command": "soundboard-move-slot",
                "slot": slot,
                "direction": direction,
            })
            self._send_page(f"Move {slot}: {msg if not ok else 'sent'}")
            return

        if parsed.path == "/settings":
            key = form.get("key", [""])[0]
            value = form.get("value", [""])[0]
            update_soundboard_setting(key, value)
            settings = read_soundboard_settings()
            json_response(self, 200, {"ok": True, **settings})
            return

        if parsed.path == "/volume":
            raw_volume = form.get("volume", ["100"])[0]
            try:
                volume = max(0, min(100, int(raw_volume)))
            except Exception:
                volume = 100

            update_soundboard_setting("global_volume", volume)

            ok, msg = send_ipc({"command": "soundboard-set-global-volume", "volume": volume})
            self._send_page(f"Volume global {volume}%: {msg if not ok else 'sent'}")
            return

        if parsed.path == "/layout":
            raw_columns = form.get("columns", ["0"])[0]
            try:
                columns = max(1, min(8, int(raw_columns)))
            except Exception:
                json_response(self, 400, {"ok": False, "error": "Invalid columns"})
                return

            update_soundboard_setting("remote_columns", columns)
            json_response(self, 200, {"ok": True, "remote_columns": columns})
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

            if data.strip() not in DISCOVERY_REQUESTS:
                continue

            payload = {
                "service": DISCOVERY_SERVICE,
                "version": 2,
                "name": SERVICE_NAME,
                "http_port": HTTP_PORT,
                "pairing_available": read_valid_pairing() is not None,
            }
            try:
                sock.sendto(json.dumps(payload).encode("utf-8"), addr)
            except OSError:
                pass


def start_idle_shutdown_watch(server: ThreadingHTTPServer) -> None:
    if REMOTE_IDLE_TIMEOUT_SECONDS <= 0:
        print("Remote idle auto-stop disabled", flush=True)
        return

    def run() -> None:
        while True:
            time.sleep(REMOTE_IDLE_CHECK_SECONDS)
            with _REMOTE_ACTIVITY_LOCK:
                idle_for = time.monotonic() - _REMOTE_LAST_ACTIVITY

            if idle_for >= REMOTE_IDLE_TIMEOUT_SECONDS:
                print(
                    f"Remote idle for {int(idle_for)}s; stopping HTTP/discovery server",
                    flush=True,
                )
                server.shutdown()
                return

    thread = threading.Thread(target=run, name="soundboard-remote-idle-stop", daemon=True)
    thread.start()


def main() -> int:
    ip = local_ip()
    stop_event = threading.Event()
    thread = threading.Thread(target=discovery_loop, args=(stop_event,), daemon=True)
    thread.start()

    print()
    print("K-Sounds Remote Web")
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
    start_idle_shutdown_watch(server)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.")
    finally:
        stop_event.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
