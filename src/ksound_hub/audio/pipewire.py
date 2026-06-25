from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np

from ..config import CONFIG_DIR
from ..models import AppSettings, ChannelConfig, EqProfile
from .engine import AppStream, AudioEngine, AudioNode


TARGET_OBJECT_BY_LABEL: dict[str, str] = {}
MICRO_SOURCE_BY_LABEL: dict[str, str] = {}


PLAYBACK_EQ_CHANNELS = {
    "all": "all",
    "game": "game",
    "chat": "chat",
    "media": "media",
    "more": "more",

    "return-mic": "retour",}

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

MIC_LINKABLE_CHANNELS = ("all", "game", "chat", "media", "more")

METER_SOURCE_BY_CHANNEL = {
    "all": "all.monitor",
    "game": "game.monitor",
    "chat": "chat.monitor",
    "media": "media.monitor",
    "more": "more.monitor",
    "return-mic": "retour.monitor",
    "micro": "micro_bus.monitor",
}

# 768 / 48000 is the current EQ/filter-chain latency test.
# It is used to check whether rare random playback pops improve.
EQ_PIPEWIRE_LATENCY = "1024/48000"


@dataclass
class EqRuntimeSlot:
    key: str
    logical_sink: str
    proc: subprocess.Popen | None = None
    signature: str = ""
    status: str = "idle"


@dataclass
class LoopbackLink:
    source_name: str
    sink_name: str
    module_id: str


@dataclass
class ReturnMicRuntime:
    capture_module_id: str = ""
    applied_signature: str = ""


@dataclass
class SinkInputBlock:
    sink_input_id: int | None = None
    media_name: str = ""
    app_name: str = ""
    binary_name: str = ""
    node_name: str = ""
    muted: bool | None = None


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def _parse_short_audio_nodes(lines: Iterable[str], kind: str) -> list[AudioNode]:
    nodes: list[AudioNode] = []
    for line in lines:
        parts = line.split()
        if len(parts) >= 5:
            nodes.append(AudioNode(name=parts[1], kind=kind, state=parts[-1]))
    return nodes


def _parse_loopback_module_ids_from_short_modules(
    lines: Iterable[str],
    *,
    source_name: str | None = None,
    sink_name: str | None = None,
    media_name: str | None = None,
) -> list[str]:
    matches: list[str] = []
    media_needle = f"sink_input_properties=media.name={media_name}" if media_name else None

    for line in lines:
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        module_id, module_name, args = parts
        if module_name != "module-loopback":
            continue
        if source_name is not None and f"source={source_name}" not in args:
            continue
        if sink_name is not None and f"sink={sink_name}" not in args:
            continue
        if media_needle is not None and media_needle not in args:
            continue
        matches.append(module_id)

    return matches


def _parse_sink_input_blocks(lines: Iterable[str]) -> list[SinkInputBlock]:
    blocks: list[SinkInputBlock] = []
    current: SinkInputBlock | None = None

    def flush() -> None:
        nonlocal current
        if current is not None and current.sink_input_id is not None:
            blocks.append(current)
        current = None

    for raw_line in lines:
        line = raw_line.rstrip()
        match = re.match(r"^Sink Input #(\d+)", line)
        if match:
            flush()
            current = SinkInputBlock(sink_input_id=int(match.group(1)))
            continue

        if current is None:
            continue

        stripped = line.strip()
        if stripped.startswith("media.name = "):
            current.media_name = stripped.split("=", 1)[1].strip().strip('"')
        elif stripped.startswith("application.name = "):
            current.app_name = stripped.split("=", 1)[1].strip().strip('"')
        elif stripped.startswith("application.process.binary = "):
            current.binary_name = stripped.split("=", 1)[1].strip().strip('"')
        elif stripped.startswith("node.name = "):
            current.node_name = stripped.split("=", 1)[1].strip().strip('"')
        elif stripped.startswith("Mute: "):
            current.muted = stripped.split(":", 1)[1].strip().lower() == "yes"

    flush()
    return blocks


@dataclass(frozen=True)
class PlaybackTarget:
    label: str
    sink_name: str


def _resolved_channel_node_volume(channel_volume: int, *, node_type: str, node_name: str) -> int:
    volume = _clamp_int(channel_volume, 0, 150)
    if node_type == "sink" and node_name == "retour":
        return _clamp_int(int(round(channel_volume * 1.8)), 0, 180)
    if node_type == "source" and node_name.startswith("alsa_input."):
        return _clamp_int(channel_volume, 0, 100)
    return volume


def _is_internal_ksound_stream(block: SinkInputBlock) -> bool:
    _ksh_media_name = (block.media_name or "").strip()
    _ksh_node_name = (block.node_name or "").strip()
    _ksh_app_name = (block.app_name or "").strip()
    _ksh_binary_name = (block.binary_name or "").strip()

    if _ksh_media_name.startswith("KSH_KEEPALIVE_"):
        return True

    if _ksh_media_name.startswith("KSH_MIC_PHYSICAL"):
        return True

    if _ksh_media_name in {
        "K-Sound-Hub-Soundboard-To-Micro",
        "K-Sounds Hub Mic Output Monitor",
    }:
        return True

    if "Mic Output Monitor" in _ksh_media_name:
        return True

    if "Mic Physical" in _ksh_media_name and (
        "K-Sound Hub" in _ksh_media_name or "K-Sounds Hub" in _ksh_media_name
    ):
        return True

    if (
        _ksh_media_name in {"K-Sound", "K-Sounds"}
        and _ksh_node_name.startswith("output.loopback-")
    ):
        return True

    if (
        _ksh_media_name == "pacat"
        and _ksh_app_name == "pacat"
        and _ksh_binary_name == "pacat"
        and _ksh_node_name == "pacat"
    ):
        return True

    media_name = block.media_name or ""
    internal_needles = (
        "K-Sounds Hub Mic Output Monitor",
        "K-Sound Hub Mic Physical",
        "K-Sound Hub Mic Send",
        "K-Sound Hub ALL EQ",
        "K-Sound Hub GAME EQ",
        "K-Sound Hub CHAT EQ",
        "K-Sound Hub MEDIA EQ",
        "K-Sound Hub MORE EQ",
        "K-Sound Hub V2 Device Bus",
    )
    return any(needle in media_name for needle in internal_needles)


def _looks_like_ksound_soundboard_stream(block: SinkInputBlock) -> bool:
    if "Soundboard" in block.media_name or "soundboard" in block.node_name.lower():
        return True
    app_name = block.app_name or ""
    return "K-Sound Hub" in app_name and not _is_internal_ksound_stream(block)


def _build_stream_display_name(block: SinkInputBlock) -> str | None:
    if block.sink_input_id is None:
        return None

    if _is_internal_ksound_stream(block):
        return None

    base = block.app_name or block.binary_name or block.media_name or f"Stream {block.sink_input_id}"

    if _looks_like_ksound_soundboard_stream(block):
        label = block.media_name.strip() if block.media_name.strip() else f"Stream {block.sink_input_id}"
        if label.lower() in {"audio stream", "playback stream"}:
            label = f"Stream {block.sink_input_id}"
        return f"SOUNDBOARD — {label}"

    if "K-Sound Hub" in base or "K-Sound Hub" in block.media_name:
        return None

    if block.media_name and block.media_name.lower() not in {base.lower(), "audio stream"}:
        return f"{base} — {block.media_name}"
    return base


def _build_eq_slot_signature(key: str, profile: EqProfile, target: PlaybackTarget) -> str:
    return json.dumps(
        {
            "key": key,
            "profile": profile.to_dict(),
            "target_label": target.label,
            "target_sink": target.sink_name,
        },
        sort_keys=True,
        ensure_ascii=False,
    )


def _build_eq_slot_status(*, profile_name: str, target_label: str, muted: bool, volume: int) -> str:
    extra: list[str] = []
    if muted:
        extra.append("muted")
    elif volume != 100:
        extra.append(f"vol {volume}%")
    suffix = f" • {', '.join(extra)}" if extra else ""
    return f"active ({profile_name} → {target_label}){suffix}"


class SourceMeterProbe:
    # Process-wide guard: after suspend/resume or UI rebuilds, old meter
    # threads must not keep spawning duplicate parec clients for the same source.
    _active_lock = threading.Lock()
    _active_by_source: dict[str, "SourceMeterProbe"] = {}

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
        previous: SourceMeterProbe | None = None

        with SourceMeterProbe._active_lock:
            current = SourceMeterProbe._active_by_source.get(self.source_name)
            if current is not None and current is not self:
                previous = current
                previous._stop_event.set()
                previous._terminate_proc()
            SourceMeterProbe._active_by_source[self.source_name] = self

        if previous is not None:
            previous.stop()

        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._terminate_proc()
        if self._thread.is_alive():
            self._thread.join(timeout=1.2)

        with SourceMeterProbe._active_lock:
            if SourceMeterProbe._active_by_source.get(self.source_name) is self:
                SourceMeterProbe._active_by_source.pop(self.source_name, None)

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
        # UI-only meter probe, not audio-path. Keep it deliberately cheap:
        # 2400 frames @ 48 kHz ~= 50 ms, while Glass refreshes at ~8 Hz.
        # Old buffered data is dropped so the meter stays current without
        # burning a CPU core during games.
        chunk_frames = 2400
        chunk_bytes = chunk_frames * 2 * 4
        max_buffer_bytes = chunk_bytes * 2

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
                    bufsize=0,
                )
                self._proc = proc

                if proc.stdout is None:
                    self._set_levels(0.0, 0.0)
                    time.sleep(0.08)
                    continue

                fd = proc.stdout.fileno()
                os.set_blocking(fd, False)

                while not self._stop_event.is_set():
                    if proc.poll() is not None:
                        break

                    got_data = False

                    # Drain only a small amount per pass. This prevents a hot
                    # Python loop when audio is continuously available.
                    for _ in range(4):
                        try:
                            data = os.read(fd, 65536)
                        except BlockingIOError:
                            break
                        except Exception:
                            data = b""
                            break

                        if not data:
                            break

                        got_data = True
                        buffer.extend(data)

                        if len(buffer) > max_buffer_bytes:
                            del buffer[: len(buffer) - max_buffer_bytes]

                    if got_data and len(buffer) >= chunk_bytes:
                        # Keep only the most recent complete chunk.
                        chunk = bytes(buffer[-chunk_bytes:])
                        buffer.clear()

                        samples = np.frombuffer(chunk, dtype="<f4")
                        if samples.size >= 2:
                            if samples.size % 2:
                                samples = samples[:-1]
                            frames = samples.reshape(-1, 2)

                            peak_left = float(np.max(np.abs(frames[:, 0])))
                            peak_right = float(np.max(np.abs(frames[:, 1])))

                            current_left = max(min(1.0, peak_left), current_left * 0.55)
                            current_right = max(min(1.0, peak_right), current_right * 0.55)
                            self._set_levels(current_left, current_right)

                        time.sleep(0.035)
                        continue

                    current_left *= 0.70
                    current_right *= 0.70

                    if current_left < 0.002:
                        current_left = 0.0
                    if current_right < 0.002:
                        current_right = 0.0

                    self._set_levels(current_left, current_right)
                    time.sleep(0.05)

            except Exception:
                self._set_levels(0.0, 0.0)
                time.sleep(0.12)
            finally:
                self._terminate_proc()

            if not self._stop_event.is_set():
                time.sleep(0.08)

        with SourceMeterProbe._active_lock:
            if SourceMeterProbe._active_by_source.get(self.source_name) is self:
                SourceMeterProbe._active_by_source.pop(self.source_name, None)

        self._set_levels(0.0, 0.0)


class PipeWireAudioEngine(AudioEngine):
    def __init__(self) -> None:
        self.runtime_dir = CONFIG_DIR / "runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup_stale_eq_filter_chain_processes()


        self.eq_slots: dict[str, EqRuntimeSlot] = {
            key: EqRuntimeSlot(key=key, logical_sink=logical_sink)
            for key, logical_sink in PLAYBACK_EQ_CHANNELS.items()
        }
        self._cleanup_stale_meter_parec_processes()
        self._meter_probes: dict[str, SourceMeterProbe] = {}
        self._native_meter_runtime_dir = self.runtime_dir / "native-meter-engine"
        self._native_meter_runtime_dir.mkdir(parents=True, exist_ok=True)
        self._native_meter_levels_path = self._native_meter_runtime_dir / "levels.json"
        self._native_meter_log_path = self._native_meter_runtime_dir / "native-meter-engine.log"
        self._native_meter_proc: subprocess.Popen | None = None
        self._native_meter_levels_cache_mtime_ns = 0
        self._native_meter_levels_cache_payload: dict[str, object] = {}
        self._meter_source_name_cache: set[str] = set()
        self._meter_source_cache_at = 0.0
        self._micro_links: dict[str, LoopbackLink] = {}
        self._return_mic_runtime = ReturnMicRuntime()
        self._physical_micro_selection_signature = ""
        self._last_applied_volume: dict[tuple[str, str], int] = {}

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["LC_ALL"] = "C"
        return subprocess.run(args, capture_output=True, text=True, timeout=3, env=env)

    def _run_no_fail(self, args: list[str]) -> None:
        try:
            self._run(args)
        except Exception:
            pass

    def _cleanup_stale_meter_parec_processes(self) -> None:
        # Old native meter engines can survive a killed Glass process, suspend,
        # or a session restore. Each orphan can spawn one parec per channel and
        # exhaust pipewire-pulse client slots, making real devices look missing.
        native_pattern = r"ksound_native_meter_engine --levels .*/native-meter-engine/levels\.json"
        parec_pattern = (
            r"parec --device=(all|game|chat|media|more|retour|micro|micro_bus|soundboard)\.monitor "
            r"--raw --format=float32le --rate=48000 --channels=2 --latency-msec=(40|80)"
        )
        for signal_name in ("-TERM", "-KILL"):
            for pattern in (native_pattern, parec_pattern):
                try:
                    subprocess.run(
                        ["pkill", signal_name, "-f", pattern],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception:
                    pass
            if signal_name == "-TERM":
                time.sleep(0.2)

    def _pw_link_available(self) -> bool:
        return shutil.which("pw-link") is not None

    def _pw_link_ports(self, *, direction: str) -> set[str]:
        if not self._pw_link_available():
            return set()

        if direction == "output":
            flag = "-o"
        elif direction == "input":
            flag = "-i"
        else:
            return set()

        proc = self._run(["pw-link", flag])
        if proc.returncode != 0:
            return set()

        return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


    def list_sinks(self) -> list[AudioNode]:
        proc = self._run(["pactl", "list", "short", "sinks"])
        if proc.returncode != 0:
            return []
        return _parse_short_audio_nodes(proc.stdout.splitlines(), "sink")

    def list_sources(self) -> list[AudioNode]:
        proc = self._run(["pactl", "list", "short", "sources"])
        if proc.returncode != 0:
            return []
        return _parse_short_audio_nodes(proc.stdout.splitlines(), "source")

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
        self.stop_meter_probes()
        for key in list(self._micro_links):
            self._unload_micro_link(key)
        self._disable_return_mic()

    def _native_meter_engine_binary(self) -> Path:
        return Path(__file__).resolve().parents[3] / "native_engine" / "build" / "ksound_native_meter_engine"

    def _stop_native_meter_engine(self) -> None:
        proc = self._native_meter_proc
        self._native_meter_proc = None
        if proc is None:
            return

        try:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except Exception:
                    proc.terminate()
                try:
                    proc.wait(timeout=1.5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except Exception:
                        proc.kill()
                    try:
                        proc.wait(timeout=1.0)
                    except Exception:
                        pass
        except Exception:
            pass

    def _ensure_native_meter_engine(self) -> bool:
        binary = self._native_meter_engine_binary()
        if not binary.is_file():
            return False

        if self._native_meter_proc is not None and self._native_meter_proc.poll() is None:
            return True

        self._stop_native_meter_engine()
        self._native_meter_runtime_dir.mkdir(parents=True, exist_ok=True)

        args = [
            str(binary),
            "--levels",
            str(self._native_meter_levels_path),
            "--log",
            str(self._native_meter_log_path),
            "--period-ms",
            "80",
        ]

        for key, source_name in METER_SOURCE_BY_CHANNEL.items():
            args.extend(["--source", f"{key}={source_name}"])

        env = os.environ.copy()
        env["KSH_RUNTIME_ROLE"] = "native_meter_engine"

        log_file = self._native_meter_log_path.open("ab", buffering=0)
        try:
            self._native_meter_proc = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,
            )
        except Exception:
            try:
                log_file.close()
            except Exception:
                pass
            self._native_meter_proc = None
            return False

        return self._native_meter_proc is not None and self._native_meter_proc.poll() is None

    def _read_native_meter_levels_payload(self) -> dict:
        try:
            stat = self._native_meter_levels_path.stat()
            mtime_ns = int(stat.st_mtime_ns)
            if mtime_ns == self._native_meter_levels_cache_mtime_ns:
                payload = self._native_meter_levels_cache_payload
                return payload if isinstance(payload, dict) else {}

            payload = json.loads(self._native_meter_levels_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                payload = {}

            self._native_meter_levels_cache_mtime_ns = mtime_ns
            self._native_meter_levels_cache_payload = payload
            return payload
        except Exception:
            payload = self._native_meter_levels_cache_payload
            return payload if isinstance(payload, dict) else {}

    def _native_meter_levels(self, channel_key: str) -> tuple[float, float] | None:
        if not self._ensure_native_meter_engine():
            return None

        payload = self._read_native_meter_levels_payload()
        channels = payload.get("channels") if isinstance(payload, dict) else None
        if not isinstance(channels, dict):
            return (0.0, 0.0)

        levels = channels.get(channel_key)
        if not (isinstance(levels, list) and len(levels) >= 2):
            return (0.0, 0.0)

        try:
            return (
                max(0.0, min(1.0, float(levels[0]))),
                max(0.0, min(1.0, float(levels[1]))),
            )
        except Exception:
            return (0.0, 0.0)

    def stop_meter_probes(self) -> None:
        """Stop UI-only meter capture processes."""

        self._stop_native_meter_engine()
        for probe in list(self._meter_probes.values()):
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
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except Exception:
                    proc.terminate()

                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except Exception:
                        proc.kill()
        except Exception:
            pass

    def _cleanup_stale_eq_filter_chain_processes(self) -> None:
        """Kill old K-Sounds EQ filter-chain processes from previous app runs.

        Graceful shutdown stops tracked slots, but development restarts often use
        pkill or crash paths. Those can leave pipewire -c filter-chain.conf
        processes parented to systemd --user. Only kill processes whose
        XDG_CONFIG_HOME points inside this app's EQ runtime directories.
        """

        runtime_root = self.runtime_dir.resolve()
        candidates: list[int] = []

        try:
            result = subprocess.run(
                ["pgrep", "-f", r"^pipewire -c filter-chain\.conf$"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except Exception:
            return

        for line in result.stdout.splitlines():
            try:
                pid = int(line.strip())
            except Exception:
                continue

            env_path = Path(f"/proc/{pid}/environ")
            try:
                env_text = env_path.read_bytes().replace(b"\0", b"\n").decode(errors="ignore")
            except Exception:
                continue

            marker = "XDG_CONFIG_HOME="
            xdg_values = [
                item[len(marker):].strip()
                for item in env_text.splitlines()
                if item.startswith(marker)
            ]
            if not xdg_values:
                continue

            try:
                xdg_path = Path(xdg_values[-1]).resolve()
            except Exception:
                continue

            if runtime_root not in xdg_path.parents:
                continue
            if not xdg_path.name.endswith("-eq-xdg"):
                continue

            candidates.append(pid)

        if not candidates:
            return

        for signal_value in (signal.SIGTERM, signal.SIGKILL):
            for pid in candidates:
                try:
                    os.kill(pid, signal_value)
                except ProcessLookupError:
                    pass
                except Exception:
                    pass
            if signal_value == signal.SIGTERM:
                time.sleep(0.25)

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

    def _internal_sink_names(self) -> set[str]:
        return {"all", "game", "chat", "media", "more", "retour", "micro_bus", "soundboard"}

    def _internal_source_names(self) -> set[str]:
        return {"micro"}

    def _physical_sink_names(self) -> list[str]:
        internal = self._internal_sink_names()
        names = [node.name for node in self.list_sinks()]
        physical = [name for name in names if name not in internal]
        return physical or names

    def _physical_source_names(self) -> list[str]:
        internal = self._internal_source_names()
        names = [node.name for node in self.list_sources()]
        physical = [
            name for name in names
            if name not in internal
            and ".monitor" not in name
            and not name.endswith(".monitor")
        ]
        return physical or [name for name in names if name not in internal] or names

    def _default_playback_sink_name(self) -> str:
        proc = self._run(["pactl", "get-default-sink"])
        default = proc.stdout.strip() if proc.returncode == 0 else ""
        internal = self._internal_sink_names()

        if default and default not in internal and self._sink_exists(default):
            return default

        for name in self._physical_sink_names():
            if name and name not in internal and self._sink_exists(name):
                return name

        if default and self._sink_exists(default):
            return default

        sinks = self.list_sinks()
        return sinks[0].name if sinks else ""

    def _default_micro_source_name(self) -> str:
        proc = self._run(["pactl", "get-default-source"])
        default = proc.stdout.strip() if proc.returncode == 0 else ""
        internal = self._internal_source_names()

        if (
            default
            and default not in internal
            and ".monitor" not in default
            and self._source_exists(default)
        ):
            return default

        for name in self._physical_source_names():
            if name and name not in internal and ".monitor" not in name and self._source_exists(name):
                return name

        if default and self._source_exists(default):
            return default

        sources = self.list_sources()
        return sources[0].name if sources else ""

    def _resolved_micro_source_name(self, channel: ChannelConfig) -> str:
        wanted = (channel.primary_target or "").strip()
        if wanted and self._source_exists(wanted):
            return wanted
        return self._default_micro_source_name()

    def _resolved_micro_source_names(self, channel: ChannelConfig) -> list[str]:
        source = self._resolved_micro_source_name(channel)
        return [source] if source else []

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
        env["PIPEWIRE_LATENCY"] = EQ_PIPEWIRE_LATENCY

        with self._log_path_for(slot.key).open("ab", buffering=0) as log_file:
            slot.proc = subprocess.Popen(
                ["pipewire", "-c", "filter-chain.conf"],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,
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

    def _read_node_volume_percent(self, *, node_type: str, node_name: str) -> int | None:
        cmd = ["pactl", f"get-{node_type}-volume", node_name]
        proc = self._run(cmd)
        if proc.returncode != 0:
            return None
        match = re.search(r"(\d+)%", proc.stdout)
        if not match:
            return None
        try:
            return int(match.group(1))
        except Exception:
            return None

    def _set_node_volume_raw(self, *, node_type: str, node_name: str, volume: int) -> None:
        volume_limit = 180 if node_name == "retour" else 150
        volume = _clamp_int(volume, 0, volume_limit)
        self._run_no_fail(["pactl", f"set-{node_type}-volume", node_name, f"{volume}%"])

    def _apply_node_controls(self, channel: ChannelConfig, *, node_type: str, node_name: str) -> None:
        if not self._node_exists(node_type, node_name):
            return

        volume = _resolved_channel_node_volume(channel.volume, node_type=node_type, node_name=node_name)

        if node_type == "sink":
            self._set_node_volume_smooth(node_type="sink", node_name=node_name, target_volume=volume)
            self._run_no_fail(["pactl", "set-sink-mute", node_name, "1" if channel.muted else "0"])
        elif node_type == "source":
            self._set_node_volume_smooth(node_type="source", node_name=node_name, target_volume=volume)
            self._run_no_fail(["pactl", "set-source-mute", node_name, "1" if channel.muted else "0"])

    def _micro_send_media_name(self, channel_key: str) -> str:
        return f"KSH_MIC_SEND_{str(channel_key).strip().upper()}"

    def _find_loopback_module_ids(self, *, source_name: str, sink_name: str) -> list[str]:
        proc = self._run(["pactl", "list", "short", "modules"])
        if proc.returncode != 0:
            return []
        return _parse_loopback_module_ids_from_short_modules(
            proc.stdout.splitlines(),
            source_name=source_name,
            sink_name=sink_name,
        )

    def _find_loopback_module_ids_by_media_name(self, media_name: str) -> list[str]:
        proc = self._run(["pactl", "list", "short", "modules"])
        if proc.returncode != 0:
            return []
        return _parse_loopback_module_ids_from_short_modules(
            proc.stdout.splitlines(),
            media_name=media_name,
        )

    def _find_sink_input_ids_by_media_name(self, media_name: str) -> list[str]:
        proc = self._run(["pactl", "list", "sink-inputs"])
        if proc.returncode != 0:
            return []

        blocks = _parse_sink_input_blocks(proc.stdout.splitlines())
        return [
            str(block.sink_input_id)
            for block in blocks
            if block.sink_input_id is not None and block.media_name == media_name
        ]

    def _set_sink_input_mute_by_media_name(self, media_name: str, muted: bool) -> None:
        for sink_input_id in self._find_sink_input_ids_by_media_name(media_name):
            self._run_no_fail(["pactl", "set-sink-input-mute", sink_input_id, "1" if muted else "0"])

    def _sink_input_muted_by_media_name(self, media_name: str) -> list[bool]:
        proc = self._run(["pactl", "list", "sink-inputs"])
        if proc.returncode != 0:
            return []

        blocks = _parse_sink_input_blocks(proc.stdout.splitlines())
        return [
            bool(block.muted)
            for block in blocks
            if block.media_name == media_name and block.muted is not None
        ]

    def _micro_channel_is_muted(self, channel: ChannelConfig) -> bool:
        return bool(channel.muted) or not bool(channel.enabled)

    def _apply_micro_endpoint_controls(self, channel: ChannelConfig) -> None:
        """Apply the user-facing MICRO mute to the exported virtual mic.

        The physical-mic loopback feeds micro_bus, and apps capture from the
        remapped source named "micro". Muting only the physical source is not
        reliable enough: the bus/source can remain audible to Discord. Apply
        the mute at the physical loopback sink-input, micro_bus and micro.
        """

        muted = "1" if self._micro_channel_is_muted(channel) else "0"

        if self._sink_exists("micro_bus"):
            self._run_no_fail(["pactl", "set-sink-mute", "micro_bus", muted])

        if self._source_exists("micro"):
            # Discord/Steam/etc. capture the exported virtual source named
            # "micro". Apply the user-facing MICRO volume here so the app gets
            # the same level the UI slider shows.
            exported_volume = _resolved_channel_node_volume(
                channel.volume,
                node_type="source",
                node_name="micro",
            )
            self._run_no_fail(["pactl", "set-source-volume", "micro", f"{exported_volume}%"])
            self._run_no_fail(["pactl", "set-source-mute", "micro", muted])

    def _unload_micro_link(self, channel_key: str) -> None:
        source_name = f"{channel_key}.monitor"
        sink_name = "micro_bus"

        link = self._micro_links.pop(channel_key, None)
        module_ids: list[str] = []

        if link is not None and link.module_id:
            module_ids.append(link.module_id)

        for module_id in self._find_loopback_module_ids(source_name=source_name, sink_name=sink_name):
            if module_id not in module_ids:
                module_ids.append(module_id)

        for module_id in module_ids:
            self._run_no_fail(["pactl", "unload-module", module_id])

    def _ensure_micro_link(self, channel_key: str) -> bool:
        if channel_key not in MIC_LINKABLE_CHANNELS:
            return False

        source_name = f"{channel_key}.monitor"
        sink_name = "micro_bus"

        current = self._micro_links.get(channel_key)
        if current is not None:
            if current.source_name == source_name and current.sink_name == sink_name:
                existing_ids = self._find_loopback_module_ids(source_name=source_name, sink_name=sink_name)
                if existing_ids:
                    if current.module_id not in existing_ids:
                        current.module_id = existing_ids[0]
                    return True
            self._unload_micro_link(channel_key)

        if not self._source_exists(source_name):
            return False
        if not self._sink_exists(sink_name):
            return False

        media_name = self._micro_send_media_name(channel_key)
        existing_ids = self._find_loopback_module_ids(source_name=source_name, sink_name=sink_name)
        expected_ids = [
            module_id
            for module_id in self._find_loopback_module_ids_by_media_name(media_name)
            if module_id in existing_ids
        ]

        if expected_ids:
            keep_id = expected_ids[0]
            for stale_id in existing_ids:
                if stale_id != keep_id:
                    self._run_no_fail(["pactl", "unload-module", stale_id])

            self._micro_links[channel_key] = LoopbackLink(
                source_name=source_name,
                sink_name=sink_name,
                module_id=keep_id,
            )
            return True

        # Older versions used media.name values with spaces. Pulse only kept
        # "K-Sound", so volume updates could not reliably find the sink-input.
        for stale_id in existing_ids:
            self._run_no_fail(["pactl", "unload-module", stale_id])

        proc = self._run(
            [
                "pactl",
                "load-module",
                "module-loopback",
                f"source={source_name}",
                f"sink={sink_name}",
                "latency_msec=20",
                "channels=2",
                "source_dont_move=true",
                "sink_dont_move=true",
                f"sink_input_properties=media.name={media_name}",
            ]
        )
        if proc.returncode != 0:
            return False

        module_id = proc.stdout.strip().splitlines()[-1].strip() if proc.stdout.strip() else ""
        if not module_id:
            return False

        self._micro_links[channel_key] = LoopbackLink(
            source_name=source_name,
            sink_name=sink_name,
            module_id=module_id,
        )
        return True

    def _apply_micro_links(self, settings: AppSettings) -> None:
        channel = self._find_channel(settings, "micro")
        wanted = set()
        if channel is not None and channel.enabled:
            wanted = {key for key in channel.linked_channels if key in MIC_LINKABLE_CHANNELS}

        for key in list(self._micro_links):
            if key not in wanted:
                self._unload_micro_link(key)

        for key in MIC_LINKABLE_CHANNELS:
            if key in wanted:
                self._ensure_micro_link(key)
            else:
                self._unload_micro_link(key)

    def _load_loopback_module(self, *, source_name: str, sink_name: str, media_name: str) -> str:
        proc = self._run(
            [
                "pactl",
                "load-module",
                "module-loopback",
                f"source={source_name}",
                f"sink={sink_name}",
                "latency_msec=20",
                "channels=2",
                "source_dont_move=true",
                "sink_dont_move=true",
                f"sink_input_properties=media.name={media_name}",
            ]
        )
        if proc.returncode != 0:
            return ""
        return proc.stdout.strip().splitlines()[-1].strip() if proc.stdout.strip() else ""


    def _source_is_mono_1ch(self, source_name: str) -> bool:
        proc = self._run(["pactl", "list", "short", "sources"])
        if proc.returncode != 0:
            return False

        for line in proc.stdout.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            if parts[1] != source_name:
                continue
            return "1ch" in parts

        return False

    def _ensure_physical_micro_loopbacks(self, channel: ChannelConfig) -> None:
        """Connect exactly one selected runtime-detected microphone source to micro_bus.

        This is the fallback path used when the native micro engine is disabled
        or unavailable. Keep it conservative:
        - unload legacy personal-device modules
        - keep only one KSH_MIC_PHYSICAL loopback
        - do not force channels=2, because mono microphones can sound robotic
          when Pulse/PipeWire is forced into a bad channel mapping
        - mute the exported micro source briefly while switching to avoid cracks
        """
        if not self._sink_exists("micro_bus"):
            return

        desired_sources = {
            source for source in self._resolved_micro_source_names(channel)
            if source and self._source_exists(source)
        }
        desired_signature = json.dumps(sorted(desired_sources), ensure_ascii=False)

        proc = self._run(["pactl", "list", "short", "modules"])
        existing_by_source: dict[str, list[str]] = {}
        legacy_ids: list[str] = []

        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                parts = line.split(None, 2)
                if len(parts) < 3:
                    continue

                module_id, module_name, args = parts
                if module_name != "module-loopback":
                    continue
                if "sink=micro_bus" not in args:
                    continue

                is_legacy = (
                    "K-Sound Hub Mic Physical" in args
                    or "K-Sounds Hub Mic Physical" in args
                    or "KSH_MIC_PHYSICAL_RODE" in args
                    or "KSH_MIC_PHYSICAL_ANPW" in args
                )
                if is_legacy:
                    legacy_ids.append(module_id)
                    continue

                if "sink_input_properties=media.name=KSH_MIC_PHYSICAL" not in args:
                    continue

                source_name = ""
                for item in args.split():
                    if item.startswith("source="):
                        source_name = item.split("=", 1)[1]
                        break

                if source_name:
                    if self._source_is_mono_1ch(source_name) and (
                        "channels=1" not in args or "channel_map=mono" not in args
                    ):
                        legacy_ids.append(module_id)
                        continue
                    existing_by_source.setdefault(source_name, []).append(module_id)

        existing_sources = set(existing_by_source)
        duplicate_count = sum(max(0, len(ids) - 1) for ids in existing_by_source.values())
        will_change = bool(legacy_ids) or duplicate_count > 0 or existing_sources != desired_sources

        if will_change:
            if self._source_exists("micro"):
                self._run_no_fail(["pactl", "set-source-mute", "micro", "1"])
            if self._sink_exists("micro_bus"):
                self._run_no_fail(["pactl", "set-sink-mute", "micro_bus", "1"])

        for module_id in legacy_ids:
            self._run_no_fail(["pactl", "unload-module", module_id])

        for source_name, module_ids in existing_by_source.items():
            keep_one = source_name in desired_sources
            for index, module_id in enumerate(module_ids):
                if keep_one and index == 0:
                    continue
                self._run_no_fail(["pactl", "unload-module", module_id])

        if will_change:
            time.sleep(0.12)

        kept_sources = {
            source_name
            for source_name, module_ids in existing_by_source.items()
            if source_name in desired_sources and module_ids
        }

        for source_name in sorted(desired_sources):
            if source_name in kept_sources:
                continue

            source_is_mono = self._source_is_mono_1ch(source_name)
            args = [
                "pactl",
                "load-module",
                "module-loopback",
                f"source={source_name}",
                "sink=micro_bus",
                "latency_msec=60" if source_is_mono else "latency_msec=20",
                "source_dont_move=true",
                "sink_dont_move=true",
            ]

            if source_is_mono:
                args.extend(["channels=1", "channel_map=mono"])

            args.append("sink_input_properties=media.name=KSH_MIC_PHYSICAL")
            self._run_no_fail(args)

        self._physical_micro_selection_signature = desired_signature

        if will_change:
            time.sleep(0.12)

        # Keep the physical-mic loopback at unity gain, but do not force it
        # audible. The user-facing MICRO mute must silence the complete virtual
        # microphone path used by Discord and MIC OUT.
        muted = "1" if self._micro_channel_is_muted(channel) else "0"
        for sink_input_id in self._find_sink_input_ids_by_media_name("KSH_MIC_PHYSICAL"):
            self._run_no_fail(["pactl", "set-sink-input-volume", sink_input_id, "100%"])
            self._run_no_fail(["pactl", "set-sink-input-mute", sink_input_id, muted])

        self._apply_micro_endpoint_controls(channel)


    def _find_pw_port_spec(self, *, direction: str, node_names: list[str], port_name: str) -> str:
        ports = self._pw_link_ports(direction=direction)
        if not ports:
            return ""

        for node_name in node_names:
            spec = f"{node_name}:{port_name}"
            if spec in ports:
                return spec

        for spec in sorted(ports):
            if not spec.endswith(f":{port_name}"):
                continue
            node_name = spec.rsplit(":", 1)[0]
            if node_name in node_names:
                return spec

        return ""

    def _cleanup_legacy_return_playback_modules(self) -> None:
        ids: list[str] = []
        proc = self._run(["pactl", "list", "short", "modules"])
        if proc.returncode != 0:
            return

        for line in proc.stdout.splitlines():
            parts = line.split(None, 2)
            if len(parts) < 3:
                continue

            module_id, module_name, args = parts
            if module_name != "module-loopback":
                continue

            if "source=retour.monitor" in args or ("Return " + "Mic Playback") in args:
                ids.append(module_id)

        for module_id in sorted(set(ids)):
            self._run_no_fail(["pactl", "unload-module", module_id])



    def _disconnect_return_playback_links(self) -> None:
        if not self._pw_link_available():
            return

        output_fl = self._find_pw_port_spec(
            direction="output",
            node_names=["retour", "retour.monitor"],
            port_name="monitor_FL",
        )
        output_fr = self._find_pw_port_spec(
            direction="output",
            node_names=["retour", "retour.monitor"],
            port_name="monitor_FR",
        )

        if not output_fl and not output_fr:
            return

        for sink_name in sorted(set(TARGET_OBJECT_BY_LABEL.values())):
            input_fl = self._find_pw_port_spec(
                direction="input",
                node_names=[sink_name],
                port_name="playback_FL",
            )
            input_fr = self._find_pw_port_spec(
                direction="input",
                node_names=[sink_name],
                port_name="playback_FR",
            )

            if output_fl and input_fl:
                self._run_no_fail(["pw-link", "-d", output_fl, input_fl])
            if output_fr and input_fr:
                self._run_no_fail(["pw-link", "-d", output_fr, input_fr])

    def _connect_return_playback_links(self, target_sink: str) -> bool:
        if not self._pw_link_available():
            return False

        output_fl = self._find_pw_port_spec(
            direction="output",
            node_names=["retour", "retour.monitor"],
            port_name="monitor_FL",
        )
        output_fr = self._find_pw_port_spec(
            direction="output",
            node_names=["retour", "retour.monitor"],
            port_name="monitor_FR",
        )
        input_fl = self._find_pw_port_spec(
            direction="input",
            node_names=[target_sink],
            port_name="playback_FL",
        )
        input_fr = self._find_pw_port_spec(
            direction="input",
            node_names=[target_sink],
            port_name="playback_FR",
        )

        if not output_fl or not output_fr or not input_fl or not input_fr:
            return False

        created_links: list[tuple[str, str]] = []

        for output_port, input_port in ((output_fl, input_fl), (output_fr, input_fr)):
            proc = self._run(["pw-link", output_port, input_port])
            if proc.returncode != 0:
                for created_output, created_input in created_links:
                    self._run_no_fail(["pw-link", "-d", created_output, created_input])
                return False
            created_links.append((output_port, input_port))

        return True

    def _disable_return_mic(self, *, capture: bool = True, playback: bool = True) -> None:
        ids: list[str] = []

        if capture and self._return_mic_runtime.capture_module_id:
            ids.append(self._return_mic_runtime.capture_module_id)

        if capture:
            for module_id in self._find_loopback_module_ids_by_media_name("K-Sounds Hub Mic Output Monitor Capture"):
                if module_id not in ids:
                    ids.append(module_id)

        if playback:
            self._disconnect_return_playback_links()
            self._cleanup_legacy_return_playback_modules()

        for module_id in ids:
            self._run_no_fail(["pactl", "unload-module", module_id])

        if capture:
            self._return_mic_runtime.capture_module_id = ""

        self._return_mic_runtime.applied_signature = ""

    def _apply_return_mic(self, settings: AppSettings) -> None:
        channel = self._find_channel(settings, "return-mic")
        if channel is None or not channel.enabled or int(channel.volume) <= 0:
            self._disable_return_mic(capture=True, playback=True)
            return

        if not self._pw_link_available():
            self._disable_return_mic(capture=True, playback=True)
            return

        target = self._resolve_playback_target(channel)
        if target is None or not self._sink_exists(target.sink_name):
            self._disable_return_mic(capture=True, playback=True)
            return

        target_label = target.label
        target_sink = target.sink_name

        if not self._source_exists("micro") or not self._sink_exists("retour"):
            self._disable_return_mic(capture=True, playback=True)
            return

        signature = json.dumps(
            {
                "capture_source": "micro",
                "return_enabled": bool(channel.enabled),
                "target_label": target_label,
                "target_sink": target_sink,
            },
            sort_keys=True,
            ensure_ascii=False,
        )

        capture_ids = self._find_loopback_module_ids_by_media_name("K-Sounds Hub Mic Output Monitor Capture")
        capture_id = capture_ids[0] if capture_ids else ""

        if not capture_id:
            capture_id = self._load_loopback_module(
                source_name="micro",
                sink_name="retour",
                media_name="K-Sounds Hub Mic Output Monitor Capture",
            )
            if not capture_id:
                self._disable_return_mic(capture=True, playback=True)
                return

        self._cleanup_legacy_return_playback_modules()

        if self._return_mic_runtime.applied_signature != signature:
            self._disconnect_return_playback_links()
            if not self._connect_return_playback_links(target_sink):
                self._disable_return_mic(capture=True, playback=True)
                return

        self._return_mic_runtime.capture_module_id = capture_id
        self._return_mic_runtime.applied_signature = signature

        self._apply_node_controls(channel, node_type="sink", node_name="retour")

    def _resolve_playback_target(self, channel: ChannelConfig) -> PlaybackTarget | None:
        requested = (channel.primary_target or "").strip()
        if requested and self._sink_exists(requested):
            return PlaybackTarget(label=requested, sink_name=requested)

        target_sink = self._default_playback_sink_name()
        if not target_sink:
            return None

        return PlaybackTarget(label=target_sink, sink_name=target_sink)



    def _apply_playback_channel(self, settings: AppSettings, channel_key: str) -> None:
        self._apply_eq_slot(settings, channel_key)
        self._apply_micro_links(settings)

    def _apply_micro_channel(self, settings: AppSettings) -> None:
        channel = self._find_channel(settings, "micro")
        if channel is None:
            return

        node_names = self._resolved_micro_source_names(channel)
        if not node_names:
            node_names = [self._resolved_micro_source_name(channel)]

        for node_name in node_names:
            # Keep the selected input source at unity. The MICRO slider controls
            # the exported K-Sounds virtual mic, not the physical/EasyEffects
            # input node directly.
            if self._source_exists(node_name):
                self._run_no_fail(["pactl", "set-source-volume", node_name, "100%"])
                self._run_no_fail(["pactl", "set-source-mute", node_name, "0"])

        self._ensure_physical_micro_loopbacks(channel)
        self._run_no_fail(["pactl", "set-default-source", "micro"])
        self._apply_micro_links(settings)
        self._apply_return_mic(settings)

    def _apply_return_mic_channel(self, settings: AppSettings) -> None:
        self._apply_return_mic(settings)

    def _apply_direct_control_channel(self, settings: AppSettings, channel_key: str) -> None:
        channel = self._find_channel(settings, channel_key)
        if channel is None:
            return

        control = CONTROL_NODE_BY_CHANNEL.get(channel_key)
        if control is None:
            return

        node_type, node_name = control
        self._apply_node_controls(channel, node_type=node_type, node_name=node_name)

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

        target = self._resolve_playback_target(channel)
        if target is None:
            self._stop_slot(slot)
            slot.status = f"no target mapping for {(channel.primary_target or '').strip() or 'system default'}"
            return

        if not self._sink_exists(target.sink_name):
            self._stop_slot(slot)
            slot.status = f"target sink missing ({target.label})"
            return

        profile = self._current_profile(channel)
        dropin_text = self._render_eq_dropin(
            key=key,
            logical_sink=logical_sink,
            profile=profile,
            target_sink=target.sink_name,
        )
        signature = _build_eq_slot_signature(key, profile, target)
        self._write_slot_dropin(key, dropin_text)
        self._start_slot(slot, signature)

        proc = slot.proc
        if proc is None:
            slot.status = "failed to start"
            return

        if proc.poll() is None:
            slot.status = _build_eq_slot_status(
                profile_name=profile.name,
                target_label=target.label,
                muted=channel.muted,
                volume=channel.volume,
            )
            return

        tail = self._read_slot_log_tail(key)
        slot.status = f"failed ({tail or 'see log'})"

    def meter_levels(self, channel_key: str) -> tuple[float, float]:
        source_name = METER_SOURCE_BY_CHANNEL.get(channel_key)
        if not source_name:
            return (0.0, 0.0)

        # Prefer the native meter engine. Do not fall back to legacy parec
        # probes anymore: after suspend/resume or UI rebuilds, those probes can
        # multiply until pipewire-pulse refuses new client connections, which
        # makes real sources such as easyeffects_source look "not found".
        native = self._native_meter_levels(channel_key)
        if native is not None:
            return native

        # Defensive cleanup in case an older runtime left legacy probes alive.
        if getattr(self, "_meter_probes", None):
            self.stop_meter_probes()

        return (0.0, 0.0)

    def apply_channel(self, settings: AppSettings, channel_key: str) -> None:
        if channel_key in PLAYBACK_EQ_CHANNELS:
            self._apply_playback_channel(settings, channel_key)
            return

        if channel_key == "micro":
            self._apply_micro_channel(settings)
            return

        if channel_key == "return-mic":
            self._apply_return_mic_channel(settings)
            return

        self._apply_direct_control_channel(settings, channel_key)

    def apply_settings(self, settings: AppSettings) -> None:
        for key in PLAYBACK_EQ_CHANNELS:
            self._apply_playback_channel(settings, key)
        self._apply_micro_channel(settings)
        self._apply_return_mic_channel(settings)
        self._apply_micro_links(settings)

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

    def _sink_input_info(self) -> dict[int, dict[str, str]]:
        proc = self._run(["pactl", "list", "sink-inputs"])
        if proc.returncode != 0:
            return {}

        info: dict[int, dict[str, str]] = {}
        for block in _parse_sink_input_blocks(proc.stdout.splitlines()):
            if block.sink_input_id is None:
                continue

            display_name = _build_stream_display_name(block)
            if not display_name:
                continue

            info[block.sink_input_id] = {
                "display_name": display_name,
                "app_name": block.app_name,
                "binary_name": block.binary_name,
                "media_name": block.media_name,
                "node_name": block.node_name,
            }

        return info

    def _build_app_streams(self) -> list[AppStream]:
        sink_names = self._sink_index_to_name()
        sink_indexes = self._sink_input_sink_indexes()
        info = self._sink_input_info()

        streams: list[AppStream] = []
        for stream_id, sink_index in sink_indexes.items():
            meta = info.get(stream_id)
            if meta is None:
                continue
            streams.append(
                AppStream(
                    stream_id=stream_id,
                    display_name=meta.get("display_name", f"Stream {stream_id}"),
                    sink_name=sink_names.get(sink_index, ""),
                    app_name=meta.get("app_name", ""),
                    binary_name=meta.get("binary_name", ""),
                    media_name=meta.get("media_name", ""),
                    node_name=meta.get("node_name", ""),
                )
            )
        streams.sort(key=lambda item: (item.display_name.lower(), item.stream_id))
        return streams

    def list_sink_inputs(self) -> list[AppStream]:
        return self._build_app_streams()

    def _target_sink_name_for_channel_key(self, channel_key: str) -> str:
        return PLAYBACK_EQ_CHANNELS.get(channel_key, "")

    def move_sink_input_to_channel(self, stream_id: int, channel_key: str) -> bool:
        target = self._target_sink_name_for_channel_key(channel_key)
        if not target:
            return False
        if not self._sink_exists(target):
            return False
        proc = self._run(["pactl", "move-sink-input", str(stream_id), target])
        return proc.returncode == 0

    def _set_node_volume_smooth(self, *, node_type: str, node_name: str, target_volume: int) -> None:
        cache_key = (node_type, node_name)

        current = self._last_applied_volume.get(cache_key)
        if current is None:
            current = self._read_node_volume_percent(node_type=node_type, node_name=node_name)

        if current is None:
            self._set_node_volume_raw(node_type=node_type, node_name=node_name, volume=target_volume)
            self._last_applied_volume[cache_key] = int(target_volume)
            return

        current = int(current)
        target = int(target_volume)

        if abs(target - current) > 10:
            mid = current + (target - current) // 2
            self._set_node_volume_raw(node_type=node_type, node_name=node_name, volume=mid)

        self._set_node_volume_raw(node_type=node_type, node_name=node_name, volume=target)
        self._last_applied_volume[cache_key] = target
