from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from ..config import CONFIG_DIR
from ..models import AppSettings, ChannelConfig, EqProfile
from .engine import AudioNode
from .pipewire import (
    CONTROL_NODE_BY_CHANNEL,
    METER_SOURCE_BY_CHANNEL,
    MICRO_SOURCE_BY_LABEL,
    PLAYBACK_EQ_CHANNELS,
    STATUS_LABELS,
    STATUS_ORDER,
    TARGET_OBJECT_BY_LABEL,
    PipeWireAudioEngine as PipeWireAudioEngineBase,
)

PLAYBACK_KEYS = tuple(PLAYBACK_EQ_CHANNELS.keys())
DEFAULT_TARGET_LABEL = "ANPW"


class PipeWireAudioEngine(PipeWireAudioEngineBase):
    """
    V2 final-render playback engine.

    Playback no longer uses one PipeWire filter-chain process per channel.
    Instead, K-Sound Hub keeps the visible channel sinks, captures their monitors,
    applies per-channel volume/mute/EQ in a dedicated mixer process, and renders
    once per physical target device.

    Micro / return-mic intentionally stay on the inherited implementation for now.
    """

    def __init__(self) -> None:
        super().__init__()
        self._v2_state_path = self.runtime_dir / "v2-final-render-state.json"
        self._v2_levels_path = self.runtime_dir / "v2-final-render-levels.json"
        self._v2_mixer_log = self.runtime_dir / "v2-final-render-mixer.log"
        self._v2_mixer_proc: subprocess.Popen | None = None
        self._last_settings: AppSettings | None = None
        self._last_state_signature = ""
        self._disable_legacy_playback_slots()

    def _disable_legacy_playback_slots(self) -> None:
        for slot in self.eq_slots.values():
            self._stop_slot(slot)
            slot.status = "v2 final-render"
        self._kill_legacy_filter_chains()

    def _kill_legacy_filter_chains(self) -> None:
        try:
            proc = self._run(["pgrep", "-af", "pipewire -c filter-chain.conf"])
        except Exception:
            return
        if proc.returncode != 0:
            return
        for line in proc.stdout.splitlines():
            parts = line.split(None, 1)
            if not parts or not parts[0].isdigit():
                continue
            pid = int(parts[0])
            if pid == os.getpid():
                continue
            try:
                os.kill(pid, 15)
            except Exception:
                pass

    def shutdown(self) -> None:
        self._stop_v2_mixer()
        for probe in self._meter_probes.values():
            probe.stop()
        self._meter_probes.clear()
        for key in list(self._micro_links):
            self._unload_micro_link(key)
        self._disable_return_mic()

    def status_text(self) -> str:
        parts = [self._status_base(), "playback-v2: final-render mixer"]
        for key in STATUS_ORDER:
            slot = self.eq_slots[key]
            parts.append(f"{STATUS_LABELS[key]}: {slot.status}")
        return " • ".join(parts)

    def _current_profile(self, channel: ChannelConfig) -> EqProfile:
        wanted = channel.selected_eq_profile
        for profile in channel.eq_profiles:
            if profile.name == wanted:
                return profile
        return channel.eq_profiles[0]

    def _playback_channel_payload(self, channel: ChannelConfig) -> dict[str, Any]:
        target_label = (channel.primary_target or DEFAULT_TARGET_LABEL).strip() or DEFAULT_TARGET_LABEL
        target_sink = TARGET_OBJECT_BY_LABEL.get(target_label) or TARGET_OBJECT_BY_LABEL[DEFAULT_TARGET_LABEL]
        profile = self._current_profile(channel)
        return {
            "enabled": bool(channel.enabled),
            "muted": bool(channel.muted),
            "volume": int(channel.volume),
            "target_label": target_label,
            "target_sink": target_sink,
            "profile_name": profile.name,
            "bands": profile.to_dict().get("bands", []),
        }

    def _state_payload(self, settings: AppSettings) -> dict[str, Any]:
        channels: dict[str, Any] = {}
        for key in PLAYBACK_KEYS:
            channel = self._find_channel(settings, key)
            if channel is None:
                channels[key] = {
                    "enabled": False,
                    "muted": True,
                    "volume": 100,
                    "target_label": DEFAULT_TARGET_LABEL,
                    "target_sink": TARGET_OBJECT_BY_LABEL[DEFAULT_TARGET_LABEL],
                    "bands": [],
                }
                continue
            channels[key] = self._playback_channel_payload(channel)
        return {"version": 1, "updated_at": time.time(), "channels": channels}

    def _write_v2_state(self, settings: AppSettings) -> None:
        payload = self._state_payload(settings)
        signature = json.dumps(payload.get("channels", {}), sort_keys=True, ensure_ascii=False)
        if signature == self._last_state_signature and self._v2_state_path.exists():
            return
        self._last_state_signature = signature
        tmp = self._v2_state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self._v2_state_path)

    def _ensure_v2_mixer(self) -> None:
        if self._v2_mixer_proc is not None and self._v2_mixer_proc.poll() is None:
            return
        self._stop_v2_mixer()
        mixer_path = Path(__file__).with_name("v2_final_mixer.py")
        python_bin = shutil.which("python3") or "python3"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
        env["KSH_RUNTIME_ROLE"] = "v2_final_mixer"
        self._v2_mixer_log.parent.mkdir(parents=True, exist_ok=True)
        with self._v2_mixer_log.open("ab", buffering=0) as log_file:
            self._v2_mixer_proc = subprocess.Popen(
                [python_bin, str(mixer_path), str(self._v2_state_path), str(self._v2_levels_path)],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env,
            )

    def _stop_v2_mixer(self) -> None:
        proc = self._v2_mixer_proc
        self._v2_mixer_proc = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=1.2)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception:
            pass

    def _apply_playback_controls_to_visible_sink(self, channel: ChannelConfig) -> None:
        # Keep the visible logical sinks stable and avoid double-volume processing.
        # The final-render mixer applies user volume/mute itself.
        if channel.key in PLAYBACK_KEYS and self._sink_exists(channel.key):
            self._set_node_volume_smooth(node_type="sink", node_name=channel.key, target_volume=100)
            self._run_no_fail(["pactl", "set-sink-mute", channel.key, "0"])

    def _apply_playback_channel(self, settings: AppSettings, channel_key: str) -> None:
        channel = self._find_channel(settings, channel_key)
        if channel is not None:
            self._apply_playback_controls_to_visible_sink(channel)
        self._write_v2_state(settings)
        self._ensure_v2_mixer()
        slot = self.eq_slots[channel_key]
        slot.status = "v2 final-render active"

    def apply_channel(self, settings: AppSettings, channel_key: str) -> None:
        self._last_settings = settings
        if channel_key in PLAYBACK_KEYS:
            self._apply_playback_channel(settings, channel_key)
            self._apply_micro_links(settings)
            return

        if channel_key == "micro":
            channel = self._find_channel(settings, "micro")
            if channel is None:
                return
            node_names = self._resolved_micro_source_names(channel)
            if not node_names:
                node_names = [self._resolved_micro_source_name(channel)]
            for node_name in node_names:
                self._apply_node_controls(channel, node_type="source", node_name=node_name)
            self._ensure_physical_micro_loopbacks(channel)
            self._run_no_fail(["pactl", "set-default-source", "micro"])
            self._apply_micro_links(settings)
            self._apply_return_mic(settings)
            return

        if channel_key == "return-mic":
            self._apply_return_mic(settings)
            return

        channel = self._find_channel(settings, channel_key)
        if channel is None:
            return
        control = CONTROL_NODE_BY_CHANNEL.get(channel_key)
        if control is None:
            return
        node_type, node_name = control
        self._apply_node_controls(channel, node_type=node_type, node_name=node_name)

    def apply_settings(self, settings: AppSettings) -> None:
        self._last_settings = settings
        for key in PLAYBACK_KEYS:
            channel = self._find_channel(settings, key)
            if channel is not None:
                self._apply_playback_controls_to_visible_sink(channel)
                self.eq_slots[key].status = "v2 final-render active"
        self._write_v2_state(settings)
        self._ensure_v2_mixer()

        # Keep non-playback behavior unchanged for now.
        channel = self._find_channel(settings, "micro")
        if channel is not None:
            node_names = self._resolved_micro_source_names(channel)
            if not node_names:
                node_names = [self._resolved_micro_source_name(channel)]
            for node_name in node_names:
                self._apply_node_controls(channel, node_type="source", node_name=node_name)
            self._ensure_physical_micro_loopbacks(channel)
            self._run_no_fail(["pactl", "set-default-source", "micro"])
        self._apply_micro_links(settings)
        self._apply_return_mic(settings)

    def meter_levels(self, channel_key: str) -> tuple[float, float]:
        if channel_key in PLAYBACK_KEYS:
            try:
                payload = json.loads(self._v2_levels_path.read_text(encoding="utf-8"))
                levels = payload.get("channels", {}).get(channel_key)
                if isinstance(levels, list) and len(levels) >= 2:
                    return float(levels[0]), float(levels[1])
            except Exception:
                return (0.0, 0.0)
            return (0.0, 0.0)
        return super().meter_levels(channel_key)
