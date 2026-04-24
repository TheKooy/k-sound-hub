from __future__ import annotations

import json
import math
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

RATE = 48000
CHANNELS = 2
CHUNK_FRAMES = 960
CHUNK_BYTES = CHUNK_FRAMES * CHANNELS * 4
POLL_SLEEP_S = CHUNK_FRAMES / RATE

PLAYBACK_KEYS = ("all", "game", "chat", "media", "more")
TARGET_OBJECT_BY_LABEL = {
    "ANPW": "alsa_output.usb-SteelSeries_Arctis_Nova_Pro_Wireless-00.analog-stereo",
    "Arctis Nova Pro": "alsa_output.usb-SteelSeries_Arctis_Nova_Pro_Wireless-00.analog-stereo",
    "S/PDIF": "alsa_output.usb-Generic_USB_Audio-00.HiFi__SPDIF__sink",
}
DEFAULT_TARGET_LABEL = "ANPW"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


@dataclass
class Biquad:
    b0: float
    b1: float
    b2: float
    a1: float
    a2: float
    z1: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=np.float64))
    z2: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=np.float64))

    def process(self, frames: np.ndarray) -> np.ndarray:
        if frames.size == 0:
            return frames
        out = np.empty_like(frames, dtype=np.float64)
        z1 = self.z1
        z2 = self.z2
        x64 = frames.astype(np.float64, copy=False)
        for idx in range(x64.shape[0]):
            x = x64[idx]
            y = self.b0 * x + z1
            z1_new = self.b1 * x - self.a1 * y + z2
            z2_new = self.b2 * x - self.a2 * y
            z1[:] = z1_new
            z2[:] = z2_new
            out[idx] = y
        return out.astype(np.float32, copy=False)


def peaking_biquad(freq: float, gain_db: float, q: float) -> Biquad:
    freq = clamp(freq, 20.0, RATE / 2 - 100.0)
    q = max(0.05, float(q))
    gain_db = clamp(gain_db, -24.0, 24.0)
    a = 10.0 ** (gain_db / 40.0)
    omega = 2.0 * math.pi * freq / RATE
    alpha = math.sin(omega) / (2.0 * q)
    cosw = math.cos(omega)

    b0 = 1.0 + alpha * a
    b1 = -2.0 * cosw
    b2 = 1.0 - alpha * a
    a0 = 1.0 + alpha / a
    a1 = -2.0 * cosw
    a2 = 1.0 - alpha / a

    return Biquad(b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)


@dataclass
class ChannelState:
    key: str
    enabled: bool = True
    muted: bool = False
    volume: float = 1.0
    target_label: str = DEFAULT_TARGET_LABEL
    target_sink: str = TARGET_OBJECT_BY_LABEL[DEFAULT_TARGET_LABEL]
    filters_signature: str = ""
    filters: list[Biquad] = field(default_factory=list)


class CaptureClient:
    def __init__(self, key: str) -> None:
        self.key = key
        self.source_name = f"{key}.monitor"
        self.proc: subprocess.Popen[bytes] | None = None
        self.buffer = bytearray()
        self.last_level = (0.0, 0.0)
        self.last_data_at = 0.0

    def ensure_started(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            return
        self.stop()
        env = os.environ.copy()
        env["KSH_RUNTIME_ROLE"] = "v2_final_capture"
        env["KSH_V2_CHANNEL"] = self.key
        self.proc = subprocess.Popen(
            [
                "parec",
                f"--device={self.source_name}",
                "--raw",
                "--format=float32le",
                "--rate=48000",
                "--channels=2",
                "--latency-msec=30",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            env=env,
        )
        if self.proc.stdout is not None:
            os.set_blocking(self.proc.stdout.fileno(), False)

    def stop(self) -> None:
        proc = self.proc
        self.proc = None
        self.buffer.clear()
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

    def read_chunk(self) -> np.ndarray:
        self.ensure_started()
        proc = self.proc
        if proc is None or proc.stdout is None or proc.poll() is not None:
            self.last_level = (0.0, 0.0)
            return np.zeros((CHUNK_FRAMES, CHANNELS), dtype=np.float32)

        fd = proc.stdout.fileno()
        for _ in range(4):
            try:
                data = os.read(fd, 65536)
            except BlockingIOError:
                break
            except Exception:
                break
            if not data:
                break
            self.buffer.extend(data)

        if len(self.buffer) < CHUNK_BYTES:
            return np.zeros((CHUNK_FRAMES, CHANNELS), dtype=np.float32)

        raw = bytes(self.buffer[:CHUNK_BYTES])
        del self.buffer[:CHUNK_BYTES]
        samples = np.frombuffer(raw, dtype="<f4")
        if samples.size < CHUNK_FRAMES * CHANNELS:
            return np.zeros((CHUNK_FRAMES, CHANNELS), dtype=np.float32)
        frames = samples[: CHUNK_FRAMES * CHANNELS].reshape(-1, CHANNELS).astype(np.float32, copy=True)
        peak_l = float(np.max(np.abs(frames[:, 0]))) if frames.size else 0.0
        peak_r = float(np.max(np.abs(frames[:, 1]))) if frames.size else 0.0
        self.last_level = (clamp(peak_l, 0.0, 1.0), clamp(peak_r, 0.0, 1.0))
        if peak_l > 0.0005 or peak_r > 0.0005:
            self.last_data_at = time.monotonic()
        return frames


class PlaybackClient:
    def __init__(self, label: str, sink_name: str) -> None:
        self.label = label
        self.sink_name = sink_name
        self.proc: subprocess.Popen[bytes] | None = None
        self.last_write_at = 0.0

    def ensure_started(self) -> bool:
        if self.proc is not None and self.proc.poll() is None:
            return True
        self.stop()
        env = os.environ.copy()
        env["KSH_RUNTIME_ROLE"] = "v2_final_render"
        env["KSH_V2_TARGET_LABEL"] = self.label
        env["KSH_V2_TARGET_SINK"] = self.sink_name
        try:
            self.proc = subprocess.Popen(
                [
                    "pacat",
                    "--playback",
                    f"--device={self.sink_name}",
                    "--raw",
                    "--format=float32le",
                    "--rate=48000",
                    "--channels=2",
                    "--latency-msec=60",
                    "--process-time-msec=20",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                bufsize=0,
                env=env,
            )
        except FileNotFoundError:
            # pactl ships pacat on most PipeWire/Pulse installs; fall back to pw-cat when available.
            self.proc = subprocess.Popen(
                [
                    "pw-cat",
                    "--playback",
                    "--target",
                    self.sink_name,
                    "--rate",
                    "48000",
                    "--channels",
                    "2",
                    "--format",
                    "f32",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                bufsize=0,
                env=env,
            )
        return self.proc is not None and self.proc.stdin is not None

    def write(self, frames: np.ndarray) -> None:
        if not self.ensure_started():
            return
        proc = self.proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            return
        safe = np.nan_to_num(frames, nan=0.0, posinf=0.0, neginf=0.0)
        safe = np.clip(safe, -0.98, 0.98).astype("<f4", copy=False)
        try:
            proc.stdin.write(safe.tobytes())
            proc.stdin.flush()
            self.last_write_at = time.monotonic()
        except BrokenPipeError:
            self.stop()
        except Exception:
            self.stop()

    def stop(self) -> None:
        proc = self.proc
        self.proc = None
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                try:
                    proc.stdin.close()
                except Exception:
                    pass
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=0.8)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception:
            pass


class V2FinalMixer:
    def __init__(self, state_path: Path, levels_path: Path) -> None:
        self.state_path = state_path
        self.levels_path = levels_path
        self.running = True
        self.channels: dict[str, ChannelState] = {key: ChannelState(key=key) for key in PLAYBACK_KEYS}
        self.captures: dict[str, CaptureClient] = {key: CaptureClient(key) for key in PLAYBACK_KEYS}
        self.playbacks: dict[str, PlaybackClient] = {}
        self.last_state_mtime = 0.0
        self.last_levels_write = 0.0
        self.active_target_labels: set[str] = set()

    def stop(self) -> None:
        self.running = False
        for capture in self.captures.values():
            capture.stop()
        for playback in self.playbacks.values():
            playback.stop()

    def load_state_if_needed(self) -> None:
        try:
            mtime = self.state_path.stat().st_mtime
        except FileNotFoundError:
            return
        if mtime <= self.last_state_mtime:
            return
        self.last_state_mtime = mtime
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return
        channels = data.get("channels", {})
        for key in PLAYBACK_KEYS:
            raw = channels.get(key, {}) if isinstance(channels, dict) else {}
            state = self.channels[key]
            state.enabled = bool(raw.get("enabled", True))
            state.muted = bool(raw.get("muted", False))
            state.volume = clamp(float(raw.get("volume", 100)) / 100.0, 0.0, 1.8)
            target_label = str(raw.get("target_label") or DEFAULT_TARGET_LABEL)
            target_sink = str(raw.get("target_sink") or TARGET_OBJECT_BY_LABEL.get(target_label, TARGET_OBJECT_BY_LABEL[DEFAULT_TARGET_LABEL]))
            state.target_label = target_label
            state.target_sink = target_sink

            bands = raw.get("bands", [])
            signature = json.dumps(bands, sort_keys=True, ensure_ascii=False)
            if signature != state.filters_signature:
                filters: list[Biquad] = []
                if isinstance(bands, list):
                    for band in bands:
                        if not isinstance(band, dict):
                            continue
                        gain = float(band.get("gain_db", 0.0))
                        if abs(gain) < 0.01:
                            continue
                        filters.append(
                            peaking_biquad(
                                float(band.get("frequency", 1000.0)),
                                gain,
                                float(band.get("q", 1.0)),
                            )
                        )
                state.filters = filters
                state.filters_signature = signature

    def _active_targets(self) -> dict[str, str]:
        targets: dict[str, str] = {}
        for state in self.channels.values():
            if state.enabled and not state.muted:
                targets[state.target_label] = state.target_sink
        return targets

    def _process_channel(self, key: str, frames: np.ndarray) -> np.ndarray:
        state = self.channels[key]
        if not state.enabled or state.muted:
            return np.zeros_like(frames)
        out = frames
        for filt in state.filters:
            out = filt.process(out)
        out = out * state.volume
        return out

    def write_levels(self) -> None:
        now = time.monotonic()
        if now - self.last_levels_write < 0.05:
            return
        self.last_levels_write = now
        payload = {
            "timestamp": time.time(),
            "channels": {key: list(capture.last_level) for key, capture in self.captures.items()},
        }
        tmp = self.levels_path.with_suffix(".json.tmp")
        self.levels_path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.levels_path)

    def run(self) -> None:
        signal.signal(signal.SIGTERM, lambda *_: self.stop())
        signal.signal(signal.SIGINT, lambda *_: self.stop())
        next_tick = time.monotonic()
        while self.running:
            self.load_state_if_needed()
            targets = self._active_targets()
            mixes = {label: np.zeros((CHUNK_FRAMES, CHANNELS), dtype=np.float32) for label in targets}

            for key in PLAYBACK_KEYS:
                frames = self.captures[key].read_chunk()
                state = self.channels[key]
                if state.target_label not in mixes:
                    continue
                processed = self._process_channel(key, frames)
                mixes[state.target_label] += processed

            for label, sink_name in targets.items():
                client = self.playbacks.get(label)
                if client is None or client.sink_name != sink_name:
                    if client is not None:
                        client.stop()
                    client = PlaybackClient(label, sink_name)
                    self.playbacks[label] = client
                # Soft limiter to avoid hard clipping if several channels stack.
                mix = np.tanh(mixes[label] * 0.95).astype(np.float32, copy=False)
                client.write(mix)

            for label in list(self.playbacks):
                if label not in targets:
                    self.playbacks[label].write(np.zeros((CHUNK_FRAMES, CHANNELS), dtype=np.float32))
                    self.playbacks[label].stop()
                    self.playbacks.pop(label, None)

            self.write_levels()
            next_tick += POLL_SLEEP_S
            sleep_for = next_tick - time.monotonic()
            if sleep_for > 0:
                time.sleep(min(sleep_for, 0.05))
            else:
                next_tick = time.monotonic()

        self.stop()


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: v2_final_mixer.py STATE_JSON LEVELS_JSON", file=sys.stderr)
        return 2
    mixer = V2FinalMixer(Path(argv[1]), Path(argv[2]))
    mixer.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
