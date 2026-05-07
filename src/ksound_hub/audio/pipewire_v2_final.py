from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from ..models import AppSettings, ChannelConfig, EqProfile
from .engine import AudioNode
from .pipewire import (
    CONTROL_NODE_BY_CHANNEL,
    PLAYBACK_EQ_CHANNELS,
    STATUS_LABELS,
    STATUS_ORDER,
    PipeWireAudioEngine as PipeWireAudioEngineBase,
)

PLAYBACK_KEYS = tuple(PLAYBACK_EQ_CHANNELS.keys())

MIC_PHYSICAL_SOURCE_BY_LABEL: dict[str, str] = {}
MIC_EASYEFFECTS_TARGET_BY_LABEL: dict[str, str] = {}
RETURN_MIC_EASYEFFECTS_TARGET_BY_KEY: dict[str, str] = {}

RETURN_MIC_MONITOR_SOURCE_PREFIX = "source:"
RETURN_MIC_MONITOR_STATIC_SOURCE_BY_KEY = {
    "soundboard": "soundboard.monitor",
    "micro-final": "micro",
}
RETURN_MIC_MONITOR_MEDIA_PREFIX = "K-Sounds Hub Mic Output Monitor Monitor "


class PipeWireAudioEngine(PipeWireAudioEngineBase):
    """
    V2 native final-render playback engine.

    Playback keeps the visible Pulse/PipeWire channel sinks, but the actual
    final mix/render is delegated to the native C++ engine. Python only writes
    the channel state file and reads the levels file back for meters.

    Micro / return-mic intentionally stay on the inherited implementation.
    """

    def _native_playback_enabled(self) -> bool:
        # Emergency safe default: native final-render playback is disabled.
        # It can be re-enabled explicitly with KSH_NATIVE_PLAYBACK=1 after the
        # pacat/native playback instability is fixed.
        return str(os.environ.get("KSH_NATIVE_PLAYBACK", "0")).strip().lower() not in {"0", "false", "no", "off"}

    def __init__(self) -> None:
        super().__init__()
        self._native_runtime_dir = self.runtime_dir / "native-engine"
        self._native_runtime_dir.mkdir(parents=True, exist_ok=True)
        self._v2_state_path = self._native_runtime_dir / "render_state.txt"
        self._v2_volume_state_path = self._native_runtime_dir / "volume_state.txt"
        self._v2_levels_path = self._native_runtime_dir / "levels.json"
        self._v2_engine_log = self._native_runtime_dir / "native-engine.log"
        self._v2_engine_proc: subprocess.Popen | None = None
        self._native_micro_state_path = self._native_runtime_dir / "micro_state.txt"
        self._native_micro_log = self._native_runtime_dir / "native-micro-engine.log"
        self._native_micro_levels_path = self._native_runtime_dir / "micro_levels.json"
        self._native_micro_proc: subprocess.Popen | None = None
        self._last_micro_state_signature = ""
        self._return_mic_legacy_cleanup_done = False
        self._native_micro_levels_cache_mtime_ns = 0
        self._native_micro_levels_cache_payload: dict[str, Any] = {}
        self._last_state_signature = ""
        self._last_volume_state_signature = ""
        self._v2_levels_cache_mtime_ns = 0
        self._v2_levels_cache_payload: dict[str, Any] = {}
        if self._native_playback_enabled():
            self._disable_legacy_playback_slots()
        else:
            for slot in self.eq_slots.values():
                slot.status = "legacy playback safe mode"

    def _disable_legacy_playback_slots(self) -> None:
        for slot in self.eq_slots.values():
            self._stop_slot(slot)
            slot.status = "v2 native final-render"
        self._kill_legacy_filter_chains()
        self._kill_legacy_python_render()

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
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass

    def _kill_legacy_python_render(self) -> None:
        for pattern in ("pacat --playback", "pw-cat --playback"):
            try:
                proc = self._run(["pgrep", "-af", pattern])
            except Exception:
                continue
            if proc.returncode != 0:
                continue
            for line in proc.stdout.splitlines():
                parts = line.split(None, 1)
                if not parts or not parts[0].isdigit():
                    continue
                pid = int(parts[0])
                if pid == os.getpid():
                    continue
                try:
                    os.kill(pid, signal.SIGTERM)
                except Exception:
                    pass

    def shutdown(self) -> None:
        if not self._native_playback_enabled():
            self._stop_v2_engine()
            self._stop_native_micro_engine()
            PipeWireAudioEngineBase.shutdown(self)
            return

        self._stop_v2_engine()
        self._stop_native_micro_engine()
        for probe in self._meter_probes.values():
            probe.stop()
        self._meter_probes.clear()
        for key in list(self._micro_links):
            self._unload_micro_link(key)
        self._disable_return_mic()

    def status_text(self) -> str:
        if not self._native_playback_enabled():
            return PipeWireAudioEngineBase.status_text(self) + " • playback-v2: disabled safe legacy"

        parts = [self._status_base(), "playback-v2: native final-render"]
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

    def _bands_spec(self, profile: EqProfile) -> str:
        bands = []
        for band in profile.bands:
            bands.append(f"{float(band.frequency):.3f}:{float(band.gain_db):.3f}:{float(band.q):.3f}")
        return ",".join(bands)

    def _native_render_key_for_channel(self, key: str) -> str:
        # UI/settings key is return-mic, but the real PipeWire sink/source is retour.
        # The native playback engine derives capture source as "<key>.monitor",
        # so return-mic must be rendered as "retour".
        return "retour" if key == "return-mic" else key

    def _render_channel_line(self, channel: ChannelConfig) -> str:
        render_key = self._native_render_key_for_channel(channel.key)
        # Fast path: channel.primary_target is already the real PipeWire sink
        # name selected by the UI. Do not call _resolve_playback_target() here
        # on every slider tick, because that can run pactl repeatedly.
        target_sink = (channel.primary_target or "").strip()
        if target_sink:
            target_label = target_sink
        else:
            target = self._resolve_playback_target(channel)
            target_label = target.label if target is not None else "system default"
            target_sink = target.sink_name if target is not None else ""

        profile = self._current_profile(channel)
        fields = [
            "channel",
            render_key,
            "1" if channel.enabled else "0",
            "1" if channel.muted else "0",
            str(int(channel.volume)),
            target_label,
            target_sink,
            self._bands_spec(profile),
        ]
        return "\t".join(fields)

    def _render_state_text(self, settings: AppSettings) -> str:
        lines = ["version\t1"]
        for key in PLAYBACK_KEYS:
            channel = self._find_channel(settings, key)
            if channel is None:
                continue
            lines.append(self._render_channel_line(channel))
        return "\n".join(lines) + "\n"

    def _write_v2_state(self, settings: AppSettings) -> None:
        text = self._render_state_text(settings)
        signature = text
        if signature == self._last_state_signature and self._v2_state_path.exists():
            return
        self._last_state_signature = signature
        tmp = self._v2_state_path.with_suffix(".txt.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(self._v2_state_path)

    def _render_volume_state_text(self, settings: AppSettings) -> str:
        lines = ["version\t1"]
        for key in PLAYBACK_KEYS:
            channel = self._find_channel(settings, key)
            if channel is None:
                continue
            render_key = self._native_render_key_for_channel(channel.key)
            lines.append(
                f"volume\t{render_key}\t{'1' if channel.muted else '0'}\t{int(channel.volume)}"
            )
        return "\n".join(lines) + "\n"


    def _write_v2_volume_state(self, settings: AppSettings) -> None:
        text = self._render_volume_state_text(settings)
        if text == self._last_volume_state_signature and self._v2_volume_state_path.exists():
            return

        self._last_volume_state_signature = text
        self._v2_volume_state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._v2_volume_state_path.with_suffix(".txt.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(self._v2_volume_state_path)

    def _native_micro_enabled(self) -> bool:
        return str(os.environ.get("KSH_NATIVE_MIC", "1")).strip().lower() not in {"0", "false", "no", "off"}

    def _native_micro_engine_binary(self) -> Path:
        return Path(__file__).resolve().parents[3] / "native_engine" / "build" / "ksound_native_micro_engine"

    def _audio_source_names(self) -> list[str]:
        proc = self._run(["pactl", "list", "short", "sources"])
        if proc.returncode != 0:
            return []
        names: list[str] = []
        for line in proc.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                names.append(parts[1])
        return names

    def _preferred_easyeffects_source(self) -> str:
        names = self._audio_source_names()

        for wanted in ("easyeffects_source", "EasyEffects Source"):
            if wanted in names:
                return wanted

        for name in names:
            low = name.lower()
            if "easyeffects" in low and "monitor" not in low:
                return name

        return ""

    def _micro_physical_source_for_label(self, label: str) -> str:
        wanted = (label or "").strip()
        if wanted and self._source_exists(wanted):
            return wanted
        return self._default_micro_source_name()

    def _native_micro_source_for_channel(self, channel: ChannelConfig) -> str:
        wanted = (channel.primary_target or "").strip()
        if wanted and self._source_exists(wanted):
            return wanted

        names = self._resolved_micro_source_names(channel)
        if names:
            return names[0]

        return self._resolved_micro_source_name(channel)



    def _ensure_micro_endpoint(self) -> None:
        if not self._sink_exists("micro_bus"):
            self._run_no_fail([
                "pactl",
                "load-module",
                "module-null-sink",
                "sink_name=micro_bus",
                "sink_properties=device.description=🎤MICRO-BUS",
            ])

        if not self._source_exists("micro"):
            self._run_no_fail([
                "pactl",
                "load-module",
                "module-remap-source",
                "master=micro_bus.monitor",
                "source_name=micro",
                "source_properties=device.description=🎤MICRO",
            ])

        self._run_no_fail(["pactl", "set-sink-mute", "micro_bus", "0"])
        self._run_no_fail(["pactl", "set-sink-volume", "micro_bus", "100%"])
        self._run_no_fail(["pactl", "set-source-mute", "micro", "0"])
        self._run_no_fail(["pactl", "set-source-volume", "micro", "100%"])
        self._run_no_fail(["pactl", "set-default-source", "micro"])

    def _cleanup_legacy_micro_loopbacks_for_native(self) -> None:
        proc = self._run(["pactl", "list", "short", "modules"])
        if proc.returncode != 0:
            return

        needles = (
            "K-Sound Hub Mic Physical",
            "K-Sound Hub Mic Send",
            "K-Sound-Hub-Soundboard-To-Micro",
        )

        for line in proc.stdout.splitlines():
            parts = line.split(None, 2)
            if len(parts) < 3:
                continue

            module_id, module_name, args = parts
            if module_name != "module-loopback":
                continue

            if any(needle in args for needle in needles):
                self._run_no_fail(["pactl", "unload-module", module_id])

    def _ensure_easyeffects_running(self) -> None:
        if self._preferred_easyeffects_source():
            return

        try:
            proc = self._run(["pgrep", "-u", str(os.getuid()), "-f", r"(^|/)easyeffects($| )|com.github.wwmm.easyeffects"])
            if proc.returncode == 0:
                return
        except Exception:
            pass

        if not shutil.which("easyeffects"):
            return

        try:
            subprocess.Popen(
                ["easyeffects", "--service-mode", "--hide-window"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=os.environ.copy(),
            )
        except Exception:
            return

    def _source_output_blocks(self) -> list[dict[str, str]]:
        proc = self._run(["pactl", "list", "source-outputs"])
        if proc.returncode != 0:
            return []

        blocks: list[dict[str, str]] = []
        current: dict[str, str] | None = None

        def flush() -> None:
            nonlocal current
            if current is not None and current.get("id"):
                blocks.append(current)
            current = None

        for raw in proc.stdout.splitlines():
            line = raw.rstrip()
            if line.startswith("Source Output #"):
                flush()
                current = {"id": line.split("#", 1)[1].strip(), "text": line + "\n"}
                continue

            if current is None:
                continue

            current["text"] = current.get("text", "") + line + "\n"
            stripped = line.strip()

            if stripped.startswith("Source: "):
                current["source"] = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("application.name = "):
                current["app"] = stripped.split("=", 1)[1].strip().strip('"')
            elif stripped.startswith("application.process.binary = "):
                current["binary"] = stripped.split("=", 1)[1].strip().strip('"')
            elif stripped.startswith("node.name = "):
                current["node"] = stripped.split("=", 1)[1].strip().strip('"')
            elif stripped.startswith("media.name = "):
                current["media"] = stripped.split("=", 1)[1].strip().strip('"')

        flush()
        return blocks

    def _move_easyeffects_input_to(self, target_source: str) -> None:
        if not target_source or not self._source_exists(target_source):
            return

        for block in self._source_output_blocks():
            text = block.get("text", "").lower()
            if "easyeffects" not in text and "easy effects" not in text:
                continue

            source_output_id = block.get("id", "")
            if source_output_id:
                self._run_no_fail(["pactl", "move-source-output", source_output_id, target_source])

    def _easyeffects_target_from_settings(self, settings: AppSettings) -> str:
        micro_channel = self._find_channel(settings, "micro")
        if micro_channel is not None:
            label = (micro_channel.primary_target or "").strip()
            target = MIC_EASYEFFECTS_TARGET_BY_LABEL.get(label, "")
            if target:
                return target

        return_channel = self._find_channel(settings, "return-mic")
        if return_channel is not None:
            linked = [str(key).lower() for key in getattr(return_channel, "linked_channels", []) or []]
            for key in linked:
                target = RETURN_MIC_EASYEFFECTS_TARGET_BY_KEY.get(key, "")
                if target:
                    return target

        return ""

    def _configure_easyeffects_for_settings(self, settings: AppSettings) -> None:
        target = self._easyeffects_target_from_settings(settings)
        if not target:
            return

        self._ensure_easyeffects_running()

        # EasyEffects creates/uses one processed source only. We try a few short
        # passes because its source-output may appear just after K-Sound starts
        # capturing easyeffects_source.
        for _ in range(6):
            self._move_easyeffects_input_to(target)
            time.sleep(0.04)

    def _channel_send_gain_for_micro(self, settings: AppSettings, channel_key: str) -> float:
        channel = self._find_channel(settings, channel_key)
        if channel is None or not channel.enabled or channel.muted:
            return 0.0

        try:
            volume = int(channel.volume)
        except Exception:
            volume = 100

        volume = max(0, min(150, volume))
        return max(0.0, min(1.5, float(volume) / 100.0))

    def _apply_micro_link_send_volumes(self, settings: AppSettings) -> None:
        micro_channel = self._find_channel(settings, "micro")
        if micro_channel is None:
            linked: set[str] = set()
            micro_muted = True
        else:
            linked = {str(key).lower() for key in getattr(micro_channel, "linked_channels", []) or []}
            micro_muted = bool(micro_channel.muted) or not bool(micro_channel.enabled)

        for key in ("all", "game", "chat", "media", "more"):
            media_name = self._micro_send_media_name(key)
            gain = self._channel_send_gain_for_micro(settings, key) if key in linked else 0.0
            volume = max(0, min(150, int(round(gain * 100.0))))
            muted = "1" if micro_muted or key not in linked or gain <= 0.0 else "0"

            for sink_input_id in self._find_sink_input_ids_by_media_name(media_name):
                self._run_no_fail(["pactl", "set-sink-input-volume", sink_input_id, f"{volume}%"])
                self._run_no_fail(["pactl", "set-sink-input-mute", sink_input_id, muted])

    def _render_native_micro_state_text(self, settings: AppSettings) -> str:
        channel = self._find_channel(settings, "micro")
        if channel is None:
            return "version\t2\nenabled\t0\nmuted\t1\nvolume\t0\nsource\t\n"

        source_name = self._native_micro_source_for_channel(channel)
        linked = {str(key).lower() for key in getattr(channel, "linked_channels", []) or []}

        lines = [
            "version\t2",
            f"enabled\t{'1' if channel.enabled else '0'}",
            f"muted\t{'1' if channel.muted else '0'}",
            f"volume\t{int(channel.volume)}",
            f"source\t{source_name}",
        ]

        for key in ("all", "game", "chat", "media", "more"):
            if key in linked:
                gain = self._channel_send_gain_for_micro(settings, key)
                enabled = "1" if gain > 0.0 else "0"
                lines.append(f"send\t{key}\t{enabled}\t{key}.monitor\t{gain:.4f}")

        if "soundboard" in linked:
            lines.append("send\tsoundboard\t1\tsoundboard.monitor\t1.0")

        return "\n".join(lines) + "\n"

    def _write_native_micro_state(self, settings: AppSettings) -> None:
        text = self._render_native_micro_state_text(settings)
        if text == self._last_micro_state_signature and self._native_micro_state_path.exists():
            return

        self._last_micro_state_signature = text
        self._native_micro_state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._native_micro_state_path.with_suffix(".txt.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(self._native_micro_state_path)

    def _ensure_native_micro_engine(self) -> bool:
        engine_bin = self._native_micro_engine_binary()
        if not engine_bin.is_file():
            return False

        if self._native_micro_proc is not None and self._native_micro_proc.poll() is None:
            return True

        self._stop_native_micro_engine()

        env = os.environ.copy()
        env["KSH_RUNTIME_ROLE"] = "native_micro_engine"
        self._native_micro_log.parent.mkdir(parents=True, exist_ok=True)

        with self._native_micro_log.open("ab", buffering=0) as log_file:
            self._native_micro_proc = subprocess.Popen(
                [
                    str(engine_bin),
                    "--state",
                    str(self._native_micro_state_path),
                    "--log",
                    str(self._native_micro_log),
                    "--levels",
                    str(self._native_micro_levels_path),
                    "--period-ms",
                    "10",
                ],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env,
            )

        return self._native_micro_proc is not None and self._native_micro_proc.poll() is None

    def _stop_native_micro_engine(self) -> None:
        proc = self._native_micro_proc
        self._native_micro_proc = None

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

    def _apply_micro_transport(self, settings: AppSettings) -> None:
        if self._native_micro_enabled():
            try:
                self._ensure_micro_endpoint()
                self._write_native_micro_state(settings)

                if self._ensure_native_micro_engine():
                    self._cleanup_legacy_micro_loopbacks_for_native()
                    self._run_no_fail(["pactl", "set-default-source", "micro"])
                    try:
                        self._configure_easyeffects_for_settings(settings)
                    except Exception:
                        pass
                    return
            except Exception:
                self._stop_native_micro_engine()

        # Fallback legacy path.
        # Important: when KSH_NATIVE_MIC=0, the legacy path still needs the
        # final virtual microphone endpoint. Without this, the fallback can
        # disable the native micro engine but leave no working "micro" source.
        self._ensure_micro_endpoint()

        channel = self._find_channel(settings, "micro")
        if channel is not None:
            self._ensure_physical_micro_loopbacks(channel)
            self._run_no_fail(["pactl", "set-default-source", "micro"])

        self._apply_micro_links(settings)
        self._apply_micro_link_send_volumes(settings)


    def _return_monitor_media_name(self, key: str) -> str:
        return RETURN_MIC_MONITOR_MEDIA_PREFIX + str(key)

    def _return_monitor_existing_module_ids(self) -> dict[str, list[str]]:
        proc = self._run(["pactl", "list", "short", "modules"])
        if proc.returncode != 0:
            return {}

        found: dict[str, list[str]] = {}
        for line in proc.stdout.splitlines():
            parts = line.split(None, 2)
            if len(parts) < 3:
                continue

            module_id, module_name, args = parts
            if module_name != "module-loopback":
                continue

            if RETURN_MIC_MONITOR_MEDIA_PREFIX not in args:
                continue

            suffix = args.split(RETURN_MIC_MONITOR_MEDIA_PREFIX, 1)[1]
            key = suffix.split()[0].strip()
            if key:
                found.setdefault(key, []).append(module_id)

        return found

    def _cleanup_return_monitor_sources(self, keep_keys: set[str] | None = None) -> None:
        keep_keys = keep_keys or set()
        for key, module_ids in self._return_monitor_existing_module_ids().items():
            if key in keep_keys:
                continue
            for module_id in module_ids:
                self._run_no_fail(["pactl", "unload-module", module_id])

    def _desired_return_monitor_sources(self, channel: ChannelConfig) -> dict[str, str]:
        linked = [str(key) for key in getattr(channel, "linked_channels", []) or []]
        desired: dict[str, str] = {}

        for raw_key in linked:
            key_lower = raw_key.lower()
            source = RETURN_MIC_MONITOR_STATIC_SOURCE_BY_KEY.get(key_lower, "")

            if not source and key_lower.startswith(RETURN_MIC_MONITOR_SOURCE_PREFIX):
                source = raw_key.split(":", 1)[1]

            if not source and self._source_exists(raw_key):
                source = raw_key

            if source and self._source_exists(source):
                desired[raw_key] = source

        return desired



    def _ensure_return_monitor_loopback(self, *, key: str, source_name: str) -> bool:
        media_name = self._return_monitor_media_name(key)
        existing = self._return_monitor_existing_module_ids().get(key, [])
        if existing:
            return True

        is_monitor_source = source_name.endswith(".monitor") or source_name == "micro"
        source_is_mono = False if is_monitor_source else self._source_is_mono_1ch(source_name)

        args = [
            "pactl",
            "load-module",
            "module-loopback",
            f"source={source_name}",
            "sink=retour",
            "latency_msec=60" if source_is_mono else "latency_msec=20",
            "source_dont_move=true",
            "sink_dont_move=true",
        ]

        # Monitor sources are stereo. Physical microphone sources may be mono;
        # forcing channels=2 on those can cause robotic/doubled monitoring.
        if is_monitor_source:
            args.append("channels=2")
        elif source_is_mono:
            args.extend(["channels=1", "channel_map=mono"])

        args.append(f"sink_input_properties=media.name={media_name}")

        proc = self._run(args)
        if proc.returncode != 0:
            return False
        return bool(proc.stdout.strip())

    def _apply_return_mic(self, settings: AppSettings) -> None:
        channel = self._find_channel(settings, "return-mic")

        # MIC OUT standard:
        # sources micro/soundboard -> sink virtuel retour -> moteur playback normal.
        # Aucun rendu spécial par ksound_native_micro_engine.
        if not self._return_mic_legacy_cleanup_done:
            self._disconnect_return_playback_links()
            self._cleanup_legacy_return_playback_modules()

            for module_id in self._find_loopback_module_ids_by_media_name("K-Sounds Hub Mic Output Monitor Capture"):
                self._run_no_fail(["pactl", "unload-module", module_id])

            self._return_mic_legacy_cleanup_done = True

        if channel is None or not channel.enabled or int(channel.volume) <= 0:
            self._cleanup_return_monitor_sources()
            self._return_mic_runtime.capture_module_id = ""
            self._return_mic_runtime.applied_signature = ""
            return

        if not self._sink_exists("retour"):
            self._run_no_fail([
                "pactl",
                "load-module",
                "module-null-sink",
                "sink_name=retour",
                "sink_properties=device.description=🎧MIC OUT",
            ])

        if not self._sink_exists("retour"):
            self._cleanup_return_monitor_sources()
            self._return_mic_runtime.capture_module_id = ""
            self._return_mic_runtime.applied_signature = ""
            return

        desired = self._desired_return_monitor_sources(channel)
        current_keys = set(self._return_monitor_existing_module_ids())
        desired_keys = set(desired)
        will_change = current_keys != desired_keys

        original_muted = bool(channel.muted)

        if will_change:
            # Muting only the Pulse sink is not enough because the V2 engine
            # captures retour.monitor. Temporarily mute the rendered MIC OUT
            # channel in native state before changing PipeWire loopbacks.
            channel.muted = True
            self._write_v2_state(settings)
            self._write_v2_volume_state(settings)
            self._ensure_v2_engine()
            self._run_no_fail(["pactl", "set-sink-mute", "retour", "1"])
            time.sleep(0.12)

        self._cleanup_return_monitor_sources(keep_keys=desired_keys)

        for key, source_name in desired.items():
            self._ensure_return_monitor_loopback(key=key, source_name=source_name)

        if will_change:
            time.sleep(0.12)

        # Like other V2 playback channels, the logical sink stays at 100%.
        # User volume is handled by the final playback engine.
        self._run_no_fail(["pactl", "set-sink-volume", "retour", "100%"])
        self._run_no_fail(["pactl", "set-sink-mute", "retour", "0"])

        if will_change:
            channel.muted = original_muted
            self._write_v2_state(settings)
            self._write_v2_volume_state(settings)

        signature = json.dumps(
            {
                "return_standard_channel": True,
                "sources": sorted(desired.items()),
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        self._return_mic_runtime.capture_module_id = ""
        self._return_mic_runtime.applied_signature = signature

    def _native_engine_binary(self) -> Path:
        return Path(__file__).resolve().parents[3] / "native_engine" / "build" / "ksound_native_engine"

    def _ensure_v2_engine(self) -> None:
        if not self._native_playback_enabled():
            self._stop_v2_engine()
            return

        if self._v2_engine_proc is not None and self._v2_engine_proc.poll() is None:
            return
        self._stop_v2_engine()
        engine_bin = self._native_engine_binary()
        if not engine_bin.is_file():
            return
        env = os.environ.copy()
        env["KSH_RUNTIME_ROLE"] = "native_engine_real"
        self._v2_engine_log.parent.mkdir(parents=True, exist_ok=True)
        with self._v2_engine_log.open("ab", buffering=0) as log_file:
            self._v2_engine_proc = subprocess.Popen(
                [
                    str(engine_bin),
                    "--state",
                    str(self._v2_state_path),
                    "--volume-state",
                    str(self._v2_volume_state_path),
                    "--levels",
                    str(self._v2_levels_path),
                    "--log",
                    str(self._v2_engine_log),
                    "--period-ms",
                    "20",
                ],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env,
            )

    def _stop_v2_engine(self) -> None:
        proc = self._v2_engine_proc
        self._v2_engine_proc = None
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

    def _logical_sink_for_playback_key(self, key: str) -> str:
        return PLAYBACK_EQ_CHANNELS.get(key, key)

    def _apply_playback_controls_to_visible_sink(self, channel: ChannelConfig) -> None:
        sink_name = self._logical_sink_for_playback_key(channel.key)
        if channel.key in PLAYBACK_KEYS and sink_name and self._sink_exists(sink_name):
            self._set_node_volume_smooth(node_type="sink", node_name=sink_name, target_volume=100)
            self._run_no_fail(["pactl", "set-sink-mute", sink_name, "0"])

    def _apply_playback_channel(self, settings: AppSettings, channel_key: str) -> None:
        if not self._native_playback_enabled():
            PipeWireAudioEngineBase._apply_playback_channel(self, settings, channel_key)
            return

        channel = self._find_channel(settings, channel_key)
        if channel is not None:
            self._apply_playback_controls_to_visible_sink(channel)
        if channel_key == "return-mic":
            self._apply_return_mic(settings)
        self._write_v2_state(settings)
        self._write_v2_volume_state(settings)
        self._ensure_v2_engine()
        slot = self.eq_slots[channel_key]
        slot.status = "v2 native final-render active"

    def apply_channel_volume_fast(self, settings: AppSettings, channel_key: str) -> None:
        if not self._native_playback_enabled():
            self.apply_channel(settings, channel_key)
            return

        if channel_key == "micro":
            channel = self._find_channel(settings, "micro")
            if channel is None:
                return

            # MICRO currently uses the fallback PipeWire loopback path:
            # physical mic source -> KSH_MIC_PHYSICAL sink-input -> micro_bus -> micro source.
            # For volume changes, avoid reapplying the whole micro transport.
            # Updating the KSH_MIC_PHYSICAL sink-input is the lightest live path.
            volume = max(0, min(150, int(channel.volume)))
            muted = "1" if channel.muted else "0"

            sink_input_ids = self._find_sink_input_ids_by_media_name("KSH_MIC_PHYSICAL")
            if sink_input_ids:
                for sink_input_id in sink_input_ids:
                    self._run_no_fail(["pactl", "set-sink-input-volume", sink_input_id, f"{volume}%"])
                    self._run_no_fail(["pactl", "set-sink-input-mute", sink_input_id, muted])
                return

            # Rare fallback: if the loopback is missing, fall back to the normal
            # micro apply path so the transport can be recreated.
            self.apply_channel(settings, channel_key)
            return

        if channel_key not in PLAYBACK_KEYS:
            self.apply_channel(settings, channel_key)
            return

        if channel_key in self.eq_slots:
            self.eq_slots[channel_key].status = "v2 native final-render active"

        self._write_v2_volume_state(settings)

        if channel_key in {"all", "game", "chat", "media", "more"}:
            # If this playback channel is shared into MICRO, update that send too.
            self._write_native_micro_state(settings)
            self._apply_micro_link_send_volumes(settings)

        self._ensure_v2_engine()

    def apply_channel(self, settings: AppSettings, channel_key: str) -> None:
        if not self._native_playback_enabled():
            PipeWireAudioEngineBase.apply_channel(self, settings, channel_key)
            return

        if channel_key == "return-mic":
            # MIC OUT is also rendered by the V2 playback engine, but its
            # monitored sources are managed by _apply_return_mic(). It must be
            # applied before the generic PLAYBACK_KEYS fast path, otherwise
            # source add/remove changes only take effect after restart.
            self._apply_return_mic(settings)
            if channel_key in self.eq_slots:
                self.eq_slots[channel_key].status = "v2 native final-render active"
            self._write_v2_state(settings)
            self._write_v2_volume_state(settings)
            self._ensure_v2_engine()
            return

        if channel_key in PLAYBACK_KEYS:
            # V2 playback volume/mute/EQ/target are handled by the native
            # final-render engine. Do not call the legacy playback path here:
            # it performs synchronous pactl work and makes sliders lag.
            if channel_key in self.eq_slots:
                self.eq_slots[channel_key].status = "v2 native final-render active"
            self._write_v2_state(settings)
            self._write_v2_volume_state(settings)
            self._ensure_v2_engine()
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
            if not self._native_micro_enabled():
                self._ensure_physical_micro_loopbacks(channel)
            self._run_no_fail(["pactl", "set-default-source", "micro"])
            self._apply_micro_transport(settings)
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
        if not self._native_playback_enabled():
            self._stop_v2_engine()
            self._stop_native_micro_engine()
            PipeWireAudioEngineBase.apply_settings(self, settings)
            return

        for key in PLAYBACK_KEYS:
            channel = self._find_channel(settings, key)
            if channel is not None:
                self._apply_playback_controls_to_visible_sink(channel)
                self.eq_slots[key].status = "v2 native final-render active"
        self._apply_return_mic(settings)
        self._write_v2_state(settings)
        self._write_v2_volume_state(settings)
        self._ensure_v2_engine()

        channel = self._find_channel(settings, "micro")
        if channel is not None:
            node_names = self._resolved_micro_source_names(channel)
            if not node_names:
                node_names = [self._resolved_micro_source_name(channel)]
            for node_name in node_names:
                self._apply_node_controls(channel, node_type="source", node_name=node_name)
            if not self._native_micro_enabled():
                self._ensure_physical_micro_loopbacks(channel)
            self._run_no_fail(["pactl", "set-default-source", "micro"])
        self._apply_micro_transport(settings)
        self._apply_return_mic(settings)

    def _read_v2_levels_payload(self) -> dict[str, Any]:
        try:
            stat = self._v2_levels_path.stat()
            mtime_ns = int(stat.st_mtime_ns)
            if mtime_ns == self._v2_levels_cache_mtime_ns:
                return self._v2_levels_cache_payload

            payload = json.loads(self._v2_levels_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                payload = {}

            self._v2_levels_cache_mtime_ns = mtime_ns
            self._v2_levels_cache_payload = payload
            return payload
        except Exception:
            return self._v2_levels_cache_payload

    def _read_native_micro_levels_payload(self) -> dict[str, Any]:
        try:
            stat = self._native_micro_levels_path.stat()
            mtime_ns = int(stat.st_mtime_ns)
            if mtime_ns == self._native_micro_levels_cache_mtime_ns:
                return self._native_micro_levels_cache_payload

            payload = json.loads(self._native_micro_levels_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                payload = {}

            self._native_micro_levels_cache_mtime_ns = mtime_ns
            self._native_micro_levels_cache_payload = payload
            return payload
        except Exception:
            return self._native_micro_levels_cache_payload

    def meter_levels(self, channel_key: str) -> tuple[float, float]:
        def boost_micro_meter(pair: tuple[float, float]) -> tuple[float, float]:
            if channel_key != "micro":
                return pair

            try:
                scale = float(os.environ.get("KSH_MIC_METER_BOOST", "4.0"))
            except Exception:
                scale = 4.0

            try:
                floor = float(os.environ.get("KSH_MIC_METER_FLOOR", "0.0015"))
            except Exception:
                floor = 0.0015

            def one(value: float) -> float:
                raw = max(0.0, min(1.0, float(value)))
                if raw < floor:
                    return 0.0
                return max(0.0, min(1.0, raw * scale))

            return one(pair[0]), one(pair[1])

        if not self._native_playback_enabled():
            return boost_micro_meter(super().meter_levels(channel_key))

        if channel_key in PLAYBACK_KEYS:
            payload = self._read_v2_levels_payload()
            levels = payload.get("channels", {}).get(channel_key)
            if levels is None and channel_key == "return-mic":
                levels = payload.get("channels", {}).get("retour")
            if isinstance(levels, list) and len(levels) >= 2:
                try:
                    return float(levels[0]), float(levels[1])
                except Exception:
                    return (0.0, 0.0)
            return (0.0, 0.0)

        if channel_key in {"micro", "return-mic"}:
            if not self._native_micro_enabled():
                return boost_micro_meter(super().meter_levels(channel_key))

            payload = self._read_native_micro_levels_payload()
            levels = payload.get("channels", {}).get(channel_key)
            if isinstance(levels, list) and len(levels) >= 2:
                try:
                    return boost_micro_meter((float(levels[0]), float(levels[1])))
                except Exception:
                    return (0.0, 0.0)

            return boost_micro_meter(super().meter_levels(channel_key))

        return super().meter_levels(channel_key)
