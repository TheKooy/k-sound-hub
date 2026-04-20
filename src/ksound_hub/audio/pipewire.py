from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Iterable

from ..config import CONFIG_DIR
from ..models import AppSettings, ChannelConfig, EqProfile
from .engine import AudioEngine, AudioNode


TARGET_OBJECT_BY_LABEL = {
    "ANPW": "alsa_output.usb-SteelSeries_Arctis_Nova_Pro_Wireless-00.analog-stereo",
    "S/PDIF": "alsa_output.usb-Generic_USB_Audio-00.HiFi__SPDIF__sink",
}


class PipeWireAudioEngine(AudioEngine):
    def __init__(self) -> None:
        self.runtime_dir = CONFIG_DIR / "runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.media_eq_proc: subprocess.Popen | None = None
        self.media_eq_signature = ""
        self.media_eq_status = "media-eq: idle"
        self.media_eq_log_path = self.runtime_dir / "media-eq.log"
        self.media_eq_xdg_home = self.runtime_dir / "media-eq-xdg"
        self.media_eq_dropin_path = self.media_eq_xdg_home / "pipewire" / "filter-chain.conf.d" / "ksound-media-eq.conf"

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["LC_ALL"] = "C"
        return subprocess.run(args, capture_output=True, text=True, timeout=3, env=env)

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

    def _status_base(self) -> str:
        sinks = len(self.list_sinks())
        sources = len(self.list_sources())
        return f"PipeWire backend available • sinks: {sinks} • sources: {sources}"

    def status_text(self) -> str:
        return f"{self._status_base()} • {self.media_eq_status}"

    def shutdown(self) -> None:
        self._stop_media_eq()

    def _stop_media_eq(self) -> None:
        proc = self.media_eq_proc
        self.media_eq_proc = None
        self.media_eq_signature = ""
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

    def _render_filters(self, profile: EqProfile) -> str:
        lines = []
        for band in profile.bands:
            lines.append(
                f'{{ type = bq_peaking freq = {band.frequency:.1f} gain = {band.gain_db:.2f} q = {band.q:.3f} }}'
            )
        return "\n          ".join(lines)

    def _render_media_eq_dropin(self, *, profile: EqProfile, target_sink: str) -> str:
        filters = self._render_filters(profile)
        return f'''context.modules = [
  {{
    name = libpipewire-module-filter-chain
    args = {{
      node.description = "K-Sound Hub MEDIA EQ"
      media.name = "K-Sound Hub MEDIA EQ"
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
        node.name = "ksh_media_eq.capture"
        target.object = "media"
        stream.capture.sink = true
        node.passive = true
        node.dont-reconnect = true
        audio.channels = 2
        audio.position = [ FL FR ]
      }}
      playback.props = {{
        node.name = "ksh_media_eq.playback"
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

    def _write_media_eq_dropin(self, text: str) -> None:
        self.media_eq_dropin_path.parent.mkdir(parents=True, exist_ok=True)
        self.media_eq_dropin_path.write_text(text, encoding="utf-8")

    def _start_media_eq(self, signature: str) -> None:
        if self.media_eq_proc is not None and self.media_eq_signature == signature and self.media_eq_proc.poll() is None:
            return

        self._stop_media_eq()

        env = os.environ.copy()
        env["XDG_CONFIG_HOME"] = str(self.media_eq_xdg_home)
        env["LC_ALL"] = "C"

        with self.media_eq_log_path.open("ab", buffering=0) as log_file:
            self.media_eq_proc = subprocess.Popen(
                ["pipewire", "-c", "filter-chain.conf"],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env,
            )
        self.media_eq_signature = signature

    def _read_media_eq_log_tail(self) -> str:
        if not self.media_eq_log_path.is_file():
            return ""
        try:
            lines = self.media_eq_log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return ""
        return lines[-1].strip() if lines else ""

    def apply_settings(self, settings: AppSettings) -> None:
        media_channel = self._find_channel(settings, "media")
        if media_channel is None:
            self._stop_media_eq()
            self.media_eq_status = "media-eq: MEDIA channel missing"
            return

        if not media_channel.enabled:
            self._stop_media_eq()
            self.media_eq_status = "media-eq: MEDIA channel disabled"
            return

        if not self._sink_exists("media"):
            self._stop_media_eq()
            self.media_eq_status = "media-eq: waiting for sink 'media'"
            return

        target_label = (media_channel.primary_target or "ANPW").strip()
        target_sink = TARGET_OBJECT_BY_LABEL.get(target_label)
        if not target_sink:
            self._stop_media_eq()
            self.media_eq_status = f"media-eq: no target mapping for {target_label}"
            return

        if not self._sink_exists(target_sink):
            self._stop_media_eq()
            self.media_eq_status = f"media-eq: target sink missing ({target_label})"
            return

        profile = self._current_profile(media_channel)
        dropin_text = self._render_media_eq_dropin(profile=profile, target_sink=target_sink)
        signature = json.dumps(
            {
                "profile": profile.to_dict(),
                "target_label": target_label,
                "target_sink": target_sink,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        self._write_media_eq_dropin(dropin_text)
        self._start_media_eq(signature)

        proc = self.media_eq_proc
        if proc is None:
            self.media_eq_status = "media-eq: failed to start"
            return

        if proc.poll() is None:
            self.media_eq_status = f"media-eq: active ({profile.name} → {target_label})"
            return

        tail = self._read_media_eq_log_tail()
        self.media_eq_status = f"media-eq: failed ({tail or 'see log'})"
