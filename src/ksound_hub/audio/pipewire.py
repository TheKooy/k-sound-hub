from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from ..config import CONFIG_DIR
from ..models import AppSettings, ChannelConfig, EqProfile
from .engine import AppStream, AudioEngine, AudioNode


TARGET_OBJECT_BY_LABEL = {
    "ANPW": "alsa_output.usb-SteelSeries_Arctis_Nova_Pro_Wireless-00.analog-stereo",
    "S/PDIF": "alsa_output.usb-Generic_USB_Audio-00.HiFi__SPDIF__sink",
}

PLAYBACK_EQ_CHANNELS = {
    "all": "all",
    "game": "game",
    "chat": "chat",
    "media": "media",
    "more": "more",
}

CONTROL_NODE_BY_CHANNEL: dict[str, tuple[str, str]] = {
    "all": ("sink", "all"),
    "game": ("sink", "game"),
    "chat": ("sink", "chat"),
    "media": ("sink", "media"),
    "more": ("sink", "more"),
    "return-mic": ("sink", "retour"),
    "micro": ("source", "micro"),
}

STATUS_ORDER = ["all", "game", "chat", "media", "more"]
STATUS_LABELS = {
    "all": "all-eq",
    "game": "game-eq",
    "chat": "chat-eq",
    "media": "media-eq",
    "more": "more-eq",
}

METER_SOURCE_BY_CHANNEL = {
    "all": "all.monitor",
    "game": "game.monitor",
    "chat": "chat.monitor",
    "media": "media.monitor",
    "more": "more.monitor",
    "return-mic": "retour.monitor",
    "micro": "micro",
}


@dataclass
class EqRuntimeSlot:
    key: str
    logical_sink: str
    proc: subprocess.Popen | None = None
    signature: str = ""
    status: str = "idle"


class SourceMeterProbe:
    def __init__(self, source_name: str) -> None:
        self.source_name = source_name
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._levels = (0.0, 0.0)
        self._proc: subprocess.Popen | None = None
        self._thread = threading.Thread(
            target=self._run,
            name=f"ksh-meter-{source_name}",
            daemon=True,
        )

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._terminate_proc()
        if self._thread.is_alive():
            self._thread.join(timeout=1.2)
        self._set_levels(0.0, 0.0)

    def levels(self) -> tuple[float, float]:
        with self._lock:
            return self._levels

    def _set_levels(self, left: float, right: float) -> None:
        left = max(0.0, min(1.0, float(left)))
        right = max(0.0, min(1.0, float(right)))
        with self._lock:
            self._levels = (left, right)

    def _terminate_proc(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=0.8)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception:
            pass

    def _run(self) -> None:
        chunk_frames = 960
        chunk_bytes = chunk_frames * 2 * 4

        while not self._stop_event.is_set():
            current_left = 0.0
            current_right = 0.0
            buffer = bytearray()

            try:
                proc = subprocess.Popen(
                    [
                        "parec",
                        f"--device={self.source_name}",
                        "--raw",
                        "--format=float32le",
                        "--rate=48000",
                        "--channels=2",
                        "--latency-msec=40",
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                self._proc = proc

                if proc.stdout is None:
                    self._set_levels(0.0, 0.0)
                    time.sleep(0.2)
                    continue

                fd = proc.stdout.fileno()
                os.set_blocking(fd, False)

                while not self._stop_event.is_set():
                    if proc.poll() is not None:
                        break

                    try:
                        data = os.read(fd, 65536)
                    except BlockingIOError:
                        data = b""

                    if data:
                        buffer.extend(data)

                        while len(buffer) >= chunk_bytes:
                            chunk = bytes(buffer[:chunk_bytes])
                            del buffer[:chunk_bytes]

                            samples = np.frombuffer(chunk, dtype="<f4")
                            if samples.size < 2:
                                continue
                            if samples.size % 2:
                                samples = samples[:-1]
                            if samples.size < 2:
                                continue

                            frames = samples.reshape(-1, 2)
                            peak_left = float(np.max(np.abs(frames[:, 0])))
                            peak_right = float(np.max(np.abs(frames[:, 1])))

                            current_left = max(min(1.0, peak_left), current_left * 0.74)
                            current_right = max(min(1.0, peak_right), current_right * 0.74)
                            self._set_levels(current_left, current_right)
                    else:
                        current_left *= 0.84
                        current_right *= 0.84
                        if current_left < 0.002:
                            current_left = 0.0
                        if current_right < 0.002:
                            current_right = 0.0
                        self._set_levels(current_left, current_right)
                        time.sleep(0.03)

            except Exception:
                self._set_levels(0.0, 0.0)
                time.sleep(0.25)
            finally:
                self._terminate_proc()

            if not self._stop_event.is_set():
                time.sleep(0.15)

        self._set_levels(0.0, 0.0)


class PipeWireAudioEngine(AudioEngine):
    def __init__(self) -> None:
        self.runtime_dir = CONFIG_DIR / "runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

        self.eq_slots: dict[str, EqRuntimeSlot] = {
            key: EqRuntimeSlot(key=key, logical_sink=logical_sink)
            for key, logical_sink in PLAYBACK_EQ_CHANNELS.items()
        }
        self._meter_probes: dict[str, SourceMeterProbe] = {}
        self._meter_source_name_cache: set[str] = set()
        self._meter_source_cache_at = 0.0

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["LC_ALL"] = "C"
        return subprocess.run(args, capture_output=True, text=True, timeout=3, env=env)

    def _run_no_fail(self, args: list[str]) -> None:
        try:
            self._run(args)
        except Exception:
            pass

    def _parse_short(self, lines: Iterable[str], kind: str) -> list[AudioNode]:
        nodes: list[AudioNode] = []
        for line in lines:
            parts = line.split()
            if len(parts) >= 5:
                nodes.append(AudioNode(name=parts[1], kind=kind, state=parts[-1]))
        return nodes

    def list_sinks(self) -> list[AudioNode]:
        proc = self._run(["pactl", "list", "short", "sinks"])
        if proc.returncode != 0:
            return []
        return self._parse_short(proc.stdout.splitlines(), "sink")

    def list_sources(self) -> list[AudioNode]:
        proc = self._run(["pactl", "list", "short", "sources"])
        if proc.returncode != 0:
            return []
        return self._parse_short(proc.stdout.splitlines(), "source")

    def _cached_source_names(self, *, force: bool = False) -> set[str]:
        now = time.monotonic()
        if force or (now - self._meter_source_cache_at) >= 1.0:
            self._meter_source_name_cache = {node.name for node in self.list_sources()}
            self._meter_source_cache_at = now
        return self._meter_source_name_cache

    def _status_base(self) -> str:
        sinks = len(self.list_sinks())
        sources = len(self.list_sources())
        return f"PipeWire backend available • sinks: {sinks} • sources: {sources}"

    def status_text(self) -> str:
        parts = [self._status_base()]
        for key in STATUS_ORDER:
            slot = self.eq_slots[key]
            parts.append(f"{STATUS_LABELS[key]}: {slot.status}")
        return " • ".join(parts)

    def shutdown(self) -> None:
        for slot in self.eq_slots.values():
            self._stop_slot(slot)
        for probe in self._meter_probes.values():
            probe.stop()
        self._meter_probes.clear()

    def _log_path_for(self, key: str) -> Path:
        return self.runtime_dir / f"{key}-eq.log"

    def _xdg_home_for(self, key: str) -> Path:
        return self.runtime_dir / f"{key}-eq-xdg"

    def _dropin_path_for(self, key: str) -> Path:
        return self._xdg_home_for(key) / "pipewire" / "filter-chain.conf.d" / f"ksound-{key}-eq.conf"

    def _stop_slot(self, slot: EqRuntimeSlot) -> None:
        proc = slot.proc
        slot.proc = None
        slot.signature = ""
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception:
            pass

    def _find_channel(self, settings: AppSettings, key: str) -> ChannelConfig | None:
        for channel in settings.channels:
            if channel.key == key:
                return channel
        return None

    def _current_profile(self, channel: ChannelConfig) -> EqProfile:
        wanted = channel.selected_eq_profile
        for profile in channel.eq_profiles:
            if profile.name == wanted:
                return profile
        return channel.eq_profiles[0]

    def _sink_exists(self, sink_name: str) -> bool:
        return any(node.name == sink_name for node in self.list_sinks())

    def _source_exists(self, source_name: str) -> bool:
        return any(node.name == source_name for node in self.list_sources())

    def _node_exists(self, node_type: str, node_name: str) -> bool:
        if node_type == "sink":
            return self._sink_exists(node_name)
        if node_type == "source":
            return self._source_exists(node_name)
        return False

    def _render_filters(self, profile: EqProfile) -> str:
        lines = []
        for band in profile.bands:
            lines.append(
                f'{{ type = bq_peaking freq = {band.frequency:.1f} gain = {band.gain_db:.2f} q = {band.q:.3f} }}'
            )
        return "\n          ".join(lines)

    def _render_eq_dropin(self, *, key: str, logical_sink: str, profile: EqProfile, target_sink: str) -> str:
        filters = self._render_filters(profile)
        title = key.upper()
        return f'''context.modules = [
  {{
    name = libpipewire-module-filter-chain
    args = {{
      node.description = "K-Sound Hub {title} EQ"
      media.name = "K-Sound Hub {title} EQ"
      filter.graph = {{
        nodes = [
          {{
            type = builtin
            name = eq
            label = param_eq
            config = {{
              filters = [
          {filters}
              ]
            }}
          }}
        ]
        inputs  = [ "eq:In 1"  "eq:In 2" ]
        outputs = [ "eq:Out 1" "eq:Out 2" ]
      }}
      capture.props = {{
        node.name = "ksh_{key}_eq.capture"
        target.object = "{logical_sink}"
        stream.capture.sink = true
        node.passive = true
        node.dont-reconnect = true
        audio.channels = 2
        audio.position = [ FL FR ]
      }}
      playback.props = {{
        node.name = "ksh_{key}_eq.playback"
        target.object = "{target_sink}"
        node.passive = true
        node.dont-reconnect = true
        audio.channels = 2
        audio.position = [ FL FR ]
      }}
    }}
  }}
]
'''

    def _write_slot_dropin(self, key: str, text: str) -> None:
        path = self._dropin_path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _start_slot(self, slot: EqRuntimeSlot, signature: str) -> None:
        if slot.proc is not None and slot.signature == signature and slot.proc.poll() is None:
            return

        self._stop_slot(slot)

        env = os.environ.copy()
        env["XDG_CONFIG_HOME"] = str(self._xdg_home_for(slot.key))
        env["LC_ALL"] = "C"

        with self._log_path_for(slot.key).open("ab", buffering=0) as log_file:
            slot.proc = subprocess.Popen(
                ["pipewire", "-c", "filter-chain.conf"],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env,
            )
        slot.signature = signature

    def _read_slot_log_tail(self, key: str) -> str:
        log_path = self._log_path_for(key)
        if not log_path.is_file():
            return ""
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return ""
        return lines[-1].strip() if lines else ""

    def _apply_node_controls(self, channel: ChannelConfig, *, node_type: str, node_name: str) -> None:
        if not self._node_exists(node_type, node_name):
            return

        volume = max(0, min(150, int(channel.volume)))
        if node_type == "sink":
            self._run_no_fail(["pactl", "set-sink-volume", node_name, f"{volume}%"])
            self._run_no_fail(["pactl", "set-sink-mute", node_name, "1" if channel.muted else "0"])
        elif node_type == "source":
            self._run_no_fail(["pactl", "set-source-volume", node_name, f"{volume}%"])
            self._run_no_fail(["pactl", "set-source-mute", node_name, "1" if channel.muted else "0"])

    def _apply_eq_slot(self, settings: AppSettings, key: str) -> None:
        slot = self.eq_slots[key]
        logical_sink = slot.logical_sink

        channel = self._find_channel(settings, key)
        if channel is None:
            self._stop_slot(slot)
            slot.status = f"{key.upper()} channel missing"
            return

        self._apply_node_controls(channel, node_type="sink", node_name=logical_sink)

        if not channel.enabled:
            self._stop_slot(slot)
            slot.status = "disabled"
            return

        if not self._sink_exists(logical_sink):
            self._stop_slot(slot)
            slot.status = f"waiting for sink '{logical_sink}'"
            return

        target_label = (channel.primary_target or "ANPW").strip()
        target_sink = TARGET_OBJECT_BY_LABEL.get(target_label)
        if not target_sink:
            self._stop_slot(slot)
            slot.status = f"no target mapping for {target_label}"
            return

        if not self._sink_exists(target_sink):
            self._stop_slot(slot)
            slot.status = f"target sink missing ({target_label})"
            return

        profile = self._current_profile(channel)
        dropin_text = self._render_eq_dropin(
            key=key,
            logical_sink=logical_sink,
            profile=profile,
            target_sink=target_sink,
        )
        signature = json.dumps(
            {
                "key": key,
                "profile": profile.to_dict(),
                "target_label": target_label,
                "target_sink": target_sink,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        self._write_slot_dropin(key, dropin_text)
        self._start_slot(slot, signature)

        proc = slot.proc
        if proc is None:
            slot.status = "failed to start"
            return

        if proc.poll() is None:
            extra = []
            if channel.muted:
                extra.append("muted")
            elif channel.volume != 100:
                extra.append(f"vol {channel.volume}%")
            suffix = f" • {', '.join(extra)}" if extra else ""
            slot.status = f"active ({profile.name} → {target_label}){suffix}"
            return

        tail = self._read_slot_log_tail(key)
        slot.status = f"failed ({tail or 'see log'})"

    def meter_levels(self, channel_key: str) -> tuple[float, float]:
        source_name = METER_SOURCE_BY_CHANNEL.get(channel_key)
        if not source_name:
            return (0.0, 0.0)

        probe = self._meter_probes.get(channel_key)
        if probe is not None:
            if probe.source_name == source_name:
                return probe.levels()
            probe.stop()
            self._meter_probes.pop(channel_key, None)

        if source_name not in self._cached_source_names():
            return (0.0, 0.0)

        probe = SourceMeterProbe(source_name)
        probe.start()
        self._meter_probes[channel_key] = probe
        return probe.levels()

    def apply_channel(self, settings: AppSettings, channel_key: str) -> None:
        channel = self._find_channel(settings, channel_key)
        if channel is None:
            return

        if channel_key in PLAYBACK_EQ_CHANNELS:
            self._apply_eq_slot(settings, channel_key)
            return

        control = CONTROL_NODE_BY_CHANNEL.get(channel_key)
        if control is None:
            return

        node_type, node_name = control
        self._apply_node_controls(channel, node_type=node_type, node_name=node_name)

    def apply_settings(self, settings: AppSettings) -> None:
        for key in PLAYBACK_EQ_CHANNELS:
            self._apply_eq_slot(settings, key)
        for key in ("return-mic", "micro"):
            self.apply_channel(settings, key)

    def _sink_index_to_name(self) -> dict[int, str]:
        mapping: dict[int, str] = {}
        proc = self._run(["pactl", "list", "short", "sinks"])
        if proc.returncode != 0:
            return mapping
        for line in proc.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0].isdigit():
                mapping[int(parts[0])] = parts[1]
        return mapping

    def _sink_input_sink_indexes(self) -> dict[int, int]:
        mapping: dict[int, int] = {}
        proc = self._run(["pactl", "list", "short", "sink-inputs"])
        if proc.returncode != 0:
            return mapping
        for line in proc.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                mapping[int(parts[0])] = int(parts[1])
        return mapping

    def _sink_input_labels(self) -> dict[int, str]:
        proc = self._run(["pactl", "list", "sink-inputs"])
        if proc.returncode != 0:
            return {}

        labels: dict[int, str] = {}
        current_id: int | None = None
        app_name = ""
        media_name = ""
        binary_name = ""

        def flush() -> None:
            nonlocal current_id, app_name, media_name, binary_name
            if current_id is None:
                return
            base = app_name or binary_name or media_name or f"Stream {current_id}"
            if "K-Sound Hub" in base or "K-Sound Hub" in media_name:
                return
            if media_name and media_name.lower() not in {base.lower(), "audio stream"}:
                label = f"{base} — {media_name}"
            else:
                label = base
            labels[current_id] = label

        for raw_line in proc.stdout.splitlines():
            line = raw_line.rstrip()
            match = re.match(r"^Sink Input #(\d+)", line)
            if match:
                flush()
                current_id = int(match.group(1))
                app_name = ""
                media_name = ""
                binary_name = ""
                continue

            if current_id is None:
                continue

            stripped = line.strip()
            if stripped.startswith("application.name = "):
                app_name = stripped.split("=", 1)[1].strip().strip('"')
            elif stripped.startswith("media.name = "):
                media_name = stripped.split("=", 1)[1].strip().strip('"')
            elif stripped.startswith("application.process.binary = "):
                binary_name = stripped.split("=", 1)[1].strip().strip('"')

        flush()
        return labels

    def list_sink_inputs(self) -> list[AppStream]:
        sink_names = self._sink_index_to_name()
        sink_indexes = self._sink_input_sink_indexes()
        labels = self._sink_input_labels()

        streams: list[AppStream] = []
        for stream_id, sink_index in sink_indexes.items():
            if stream_id not in labels:
                continue
            streams.append(
                AppStream(
                    stream_id=stream_id,
                    display_name=labels[stream_id],
                    sink_name=sink_names.get(sink_index, ""),
                )
            )
        streams.sort(key=lambda item: (item.display_name.lower(), item.stream_id))
        return streams

    def move_sink_input_to_channel(self, stream_id: int, channel_key: str) -> bool:
        target = PLAYBACK_EQ_CHANNELS.get(channel_key)
        if not target:
            return False
        if not self._sink_exists(target):
            return False
        proc = self._run(["pactl", "move-sink-input", str(stream_id), target])
        return proc.returncode == 0
