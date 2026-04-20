from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Iterable

from ..config import (
    LOG_DIR,
    MEDIA_EQ_CAPTURE_TARGET,
    MEDIA_EQ_CONFIG_PATH,
    MEDIA_EQ_LOG_PATH,
    OUTPUT_TARGET_HINTS,
    PIPEWIRE_REMOTE_NAME,
)
from ..models import AppSettings, ChannelConfig, EqProfile
from .engine import AudioEngine, AudioNode


class MediaEqRuntime:
    def __init__(self) -> None:
        self.process: subprocess.Popen[str] | None = None
        self.status = "idle"
        self.detail = "not applied"
        self.active_profile = ""
        self.active_target = ""
        self._last_signature: tuple | None = None

    def stop(self) -> None:
        proc = self.process
        self.process = None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=1.5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def reset(self, detail: str) -> None:
        self.stop()
        self.status = "idle"
        self.detail = detail
        self.active_profile = ""
        self.active_target = ""

    def apply(self, channel: ChannelConfig, sink_names: list[str]) -> None:
        signature = self._make_signature(channel)
        if signature == self._last_signature:
            return
        self._last_signature = signature

        if not channel.enabled:
            self.reset("MEDIA channel disabled")
            return

        if MEDIA_EQ_CAPTURE_TARGET not in sink_names:
            self.reset("waiting for PipeWire sink 'media'")
            return

        if not shutil.which("pipewire"):
            self.reset("pipewire binary not found")
            self.status = "error"
            return

        target_node = self._resolve_target_node(channel.primary_target, sink_names)
        if not target_node:
            self.reset(f"output target unresolved ({channel.primary_target or 'unset'})")
            self.status = "error"
            return

        profile = self._current_profile(channel)
        self._write_config(profile, target_node)

        self.stop()
        MEDIA_EQ_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

        with open(MEDIA_EQ_LOG_PATH, "ab", buffering=0) as log_file:
            self.process = subprocess.Popen(
                ["pipewire", "-c", str(MEDIA_EQ_CONFIG_PATH)],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=False,
                env=os.environ.copy(),
            )

        time.sleep(0.45)
        if self.process.poll() is not None:
            self.status = "error"
            self.detail = self._read_log_tail() or "pipewire media-eq process exited immediately"
            self.active_profile = profile.name
            self.active_target = channel.primary_target
            return

        self.status = "running"
        self.detail = f"{profile.name} → {channel.primary_target}"
        self.active_profile = profile.name
        self.active_target = channel.primary_target

    def status_line(self) -> str:
        if self.status == "running":
            return f"media-eq: running ({self.detail})"
        if self.status == "idle":
            return f"media-eq: idle ({self.detail})"
        return f"media-eq: {self.status} ({self.detail})"

    def _make_signature(self, channel: ChannelConfig) -> tuple:
        profile = self._current_profile(channel)
        band_sig = tuple((round(b.frequency, 3), round(b.gain_db, 3), round(b.q, 3)) for b in profile.bands)
        return (
            channel.enabled,
            channel.primary_target,
            channel.selected_eq_profile,
            band_sig,
        )

    def _current_profile(self, channel: ChannelConfig) -> EqProfile:
        for profile in channel.eq_profiles:
            if profile.name == channel.selected_eq_profile:
                return profile
        return channel.eq_profiles[0]

    def _resolve_target_node(self, label: str, sink_names: list[str]) -> str | None:
        if not label:
            return None

        hints = OUTPUT_TARGET_HINTS.get(label, [])
        for hint in hints:
            if hint in sink_names:
                return hint

        lower_names = {name.lower(): name for name in sink_names}
        for hint in hints:
            hint_lower = hint.lower()
            for name_lower, original in lower_names.items():
                if hint_lower in name_lower:
                    return original

        if label in sink_names:
            return label

        return None

    def _filters_block(self, profile: EqProfile) -> str:
        lines = []
        for band in profile.bands:
            lines.append(
                f'                  {{ type = bq_peaking freq = {band.frequency:.3f} gain = {band.gain_db:.3f} q = {band.q:.3f} }}'
            )
        return "\n".join(lines)

    def _write_config(self, profile: EqProfile, target_node: str) -> None:
        MEDIA_EQ_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        config = f"""context.modules = [
  {{
    name = libpipewire-module-filter-chain
    args = {{
      node.description = "KSH MEDIA EQ"
      media.name = "KSH MEDIA EQ"
      remote.name = "{PIPEWIRE_REMOTE_NAME}"
      audio.channels = 2
      audio.position = [ FL FR ]

      filter.graph = {{
        nodes = [
          {{
            type = builtin
            name = eq
            label = param_eq
            config = {{
              filters = [
{self._filters_block(profile)}
              ]
            }}
          }}
        ]
        inputs = [ "eq:In 1" "eq:In 2" ]
        outputs = [ "eq:Out 1" "eq:Out 2" ]
      }}

      capture.props = {{
        node.name = "ksh.media.eq.capture"
        node.passive = true
        target.object = "{MEDIA_EQ_CAPTURE_TARGET}"
        stream.capture.sink = true
        audio.channels = 2
        audio.position = [ FL FR ]
      }}

      playback.props = {{
        node.name = "ksh.media.eq.playback"
        node.passive = true
        target.object = "{target_node}"
        audio.channels = 2
        audio.position = [ FL FR ]
      }}
    }}
  }}
]
"""
        MEDIA_EQ_CONFIG_PATH.write_text(config, encoding="utf-8")

    def _read_log_tail(self, max_lines: int = 12) -> str:
        try:
            lines = MEDIA_EQ_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return ""
        if not lines:
            return ""
        return " | ".join(lines[-max_lines:])


class PipeWireAudioEngine(AudioEngine):
    def __init__(self) -> None:
        self._media_eq = MediaEqRuntime()

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, capture_output=True, text=True, timeout=3)

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

    def apply_settings(self, settings: AppSettings) -> None:
        media_channel = next((channel for channel in settings.channels if channel.key == "media"), None)
        if media_channel is None:
            self._media_eq.reset("MEDIA channel missing")
            return
        sink_names = [node.name for node in self.list_sinks()]
        self._media_eq.apply(media_channel, sink_names)

    def shutdown(self) -> None:
        self._media_eq.stop()

    def status_text(self) -> str:
        sinks = len(self.list_sinks())
        sources = len(self.list_sources())
        return f"PipeWire backend available • sinks: {sinks} • sources: {sources} • {self._media_eq.status_line()}"
