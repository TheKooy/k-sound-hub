from __future__ import annotations

import json
import time
from dataclasses import dataclass

from ..models import AppSettings
from .pipewire import (
    METER_SOURCE_BY_CHANNEL,
    PLAYBACK_EQ_CHANNELS,
    PipeWireAudioEngine as PipeWireAudioEngineBase,
    TARGET_OBJECT_BY_LABEL,
)

DEVICE_BUS_NAME_BY_TARGET_LABEL = {
    "ANPW": "ksh_v2_dev_headset",
    "Arctis Nova Pro": "ksh_v2_dev_headset",
    "S/PDIF": "ksh_v2_dev_spdif",
}

DEVICE_BUS_DESCRIPTION_BY_NAME = {
    "ksh_v2_dev_headset": "K-Sound Hub V2 Headset Bus",
    "ksh_v2_dev_spdif": "K-Sound Hub V2 SPDIF Bus",
}

ACTIVITY_POLL_INTERVAL_S = 0.35


@dataclass
class DeviceBusRuntime:
    target_label: str
    bus_name: str
    physical_sink: str
    sink_module_id: str = ""
    loopback_module_id: str = ""
    signature: str = ""


class PipeWireAudioEngine(PipeWireAudioEngineBase):
    """
    Playback V2 tranche 3.

    Différence principale vs T2:
    - ALL devient lui aussi on-demand.
    - la réconciliation playback se fait automatiquement depuis le backend
      en observant l'activité réelle des flux externes.
    - aucun canal playback n'est maintenu vivant artificiellement.
    """

    def __init__(self) -> None:
        super().__init__()
        self._device_buses: dict[str, DeviceBusRuntime] = {}
        self._last_settings: AppSettings | None = None
        self._last_activity_signature = ""
        self._last_activity_check_monotonic = 0.0

    def shutdown(self) -> None:
        super().shutdown()
        self._cleanup_all_device_buses()

    def _load_module(self, args: list[str]) -> str:
        proc = self._run(["pactl", "load-module", *args])
        if proc.returncode != 0:
            return ""
        module_id = proc.stdout.strip()
        return module_id if module_id.isdigit() else ""

    def _unload_module(self, module_id: str) -> None:
        if not module_id:
            return
        self._run_no_fail(["pactl", "unload-module", module_id])

    def _find_null_sink_module_id(self, sink_name: str) -> str:
        proc = self._run(["pactl", "list", "short", "modules"])
        if proc.returncode != 0:
            return ""

        needle = f"sink_name={sink_name}"
        for line in proc.stdout.splitlines():
            parts = line.split(None, 2)
            if len(parts) < 3:
                continue
            module_id, module_name, args = parts
            if module_name != "module-null-sink":
                continue
            if needle in args:
                return module_id
        return ""

    def _device_bus_media_name(self, bus_name: str) -> str:
        return f"K-Sound Hub V2 Device Bus {bus_name} Playback"

    def _device_bus_signature(self, *, bus_name: str, target_label: str, physical_sink: str) -> str:
        return json.dumps(
            {
                "bus_name": bus_name,
                "target_label": target_label,
                "physical_sink": physical_sink,
            },
            sort_keys=True,
            ensure_ascii=False,
        )

    def _ensure_device_bus_sink(self, bus_name: str) -> str:
        if self._sink_exists(bus_name):
            module_id = self._find_null_sink_module_id(bus_name)
            return module_id

        description = DEVICE_BUS_DESCRIPTION_BY_NAME.get(bus_name, bus_name)
        module_id = self._load_module(
            [
                "module-null-sink",
                f"sink_name={bus_name}",
                f"sink_properties=device.description={description}",
            ]
        )

        for _ in range(10):
            if self._sink_exists(bus_name):
                break
            time.sleep(0.1)

        return module_id or self._find_null_sink_module_id(bus_name)

    def _ensure_device_bus_loopback(self, *, bus_name: str, target_sink: str) -> str:
        media_name = self._device_bus_media_name(bus_name)
        existing_ids = self._find_loopback_module_ids_by_media_name(media_name)
        if existing_ids:
            return existing_ids[0]

        return self._load_module(
            [
                "module-loopback",
                f"source={bus_name}.monitor",
                f"sink={target_sink}",
                "latency_msec=20",
                "channels=2",
                "source_dont_move=true",
                "sink_dont_move=true",
                f"sink_input_properties=media.name={media_name}",
            ]
        )

    def _ensure_device_bus(self, *, target_label: str, target_sink: str) -> str:
        bus_name = DEVICE_BUS_NAME_BY_TARGET_LABEL.get(target_label, "")
        if not bus_name:
            return ""

        signature = self._device_bus_signature(
            bus_name=bus_name,
            target_label=target_label,
            physical_sink=target_sink,
        )
        runtime = self._device_buses.get(bus_name)

        if runtime is not None and runtime.signature == signature:
            if self._sink_exists(bus_name):
                return bus_name

        if runtime is not None and runtime.signature != signature:
            self._disable_device_bus(bus_name)

        sink_module_id = self._ensure_device_bus_sink(bus_name)
        if not self._sink_exists(bus_name):
            return ""

        loopback_module_id = self._ensure_device_bus_loopback(bus_name=bus_name, target_sink=target_sink)
        if not loopback_module_id and not self._find_loopback_module_ids_by_media_name(self._device_bus_media_name(bus_name)):
            return ""

        runtime = DeviceBusRuntime(
            target_label=target_label,
            bus_name=bus_name,
            physical_sink=target_sink,
            sink_module_id=sink_module_id,
            loopback_module_id=loopback_module_id,
            signature=signature,
        )
        self._device_buses[bus_name] = runtime
        return bus_name

    def _disable_device_bus(self, bus_name: str) -> None:
        media_name = self._device_bus_media_name(bus_name)
        for module_id in self._find_loopback_module_ids_by_media_name(media_name):
            self._unload_module(module_id)

        null_sink_module_id = self._find_null_sink_module_id(bus_name)
        if null_sink_module_id:
            self._unload_module(null_sink_module_id)

        self._device_buses.pop(bus_name, None)

    def _cleanup_all_device_buses(self) -> None:
        for bus_name in list({*DEVICE_BUS_DESCRIPTION_BY_NAME.keys(), *self._device_buses.keys()}):
            self._disable_device_bus(bus_name)

    def _logical_sink_external_stream_counts(self) -> dict[str, int]:
        sink_names = self._sink_index_to_name()
        sink_indexes = self._sink_input_sink_indexes()
        info = self._sink_input_info()

        counts: dict[str, int] = {logical_sink: 0 for logical_sink in PLAYBACK_EQ_CHANNELS.values()}
        for stream_id, sink_index in sink_indexes.items():
            if stream_id not in info:
                continue
            sink_name = sink_names.get(sink_index, "")
            if sink_name in counts:
                counts[sink_name] += 1
        return counts

    def _logical_sink_external_stream_count(self, logical_sink: str) -> int:
        return self._logical_sink_external_stream_counts().get(logical_sink, 0)

    def _playback_activity_signature(self) -> str:
        counts = self._logical_sink_external_stream_counts()
        return json.dumps(counts, sort_keys=True, ensure_ascii=False)

    def _maybe_reconcile_for_activity(self, *, force: bool = False) -> None:
        if self._last_settings is None:
            return

        now = time.monotonic()
        if not force and now - self._last_activity_check_monotonic < ACTIVITY_POLL_INTERVAL_S:
            return
        self._last_activity_check_monotonic = now

        signature = self._playback_activity_signature()
        if not force and signature == self._last_activity_signature:
            return

        self._reconcile_playback(self._last_settings)
        self._last_activity_signature = self._playback_activity_signature()

    def _playback_channel_should_run(self, settings: AppSettings, key: str, logical_sink: str) -> bool:
        channel = self._find_channel(settings, key)
        if channel is None or not channel.enabled:
            return False
        return self._logical_sink_external_stream_count(logical_sink) > 0

    def _cleanup_unused_device_buses(self, settings: AppSettings) -> None:
        desired_bus_names: set[str] = set()
        for key, logical_sink in PLAYBACK_EQ_CHANNELS.items():
            if not self._playback_channel_should_run(settings, key, logical_sink):
                continue
            channel = self._find_channel(settings, key)
            if channel is None:
                continue
            target_label = (channel.primary_target or "ANPW").strip()
            bus_name = DEVICE_BUS_NAME_BY_TARGET_LABEL.get(target_label)
            if bus_name:
                desired_bus_names.add(bus_name)

        for bus_name in list({*DEVICE_BUS_DESCRIPTION_BY_NAME.keys(), *self._device_buses.keys()}):
            if bus_name not in desired_bus_names:
                self._disable_device_bus(bus_name)

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

        if not self._playback_channel_should_run(settings, key, logical_sink):
            self._stop_slot(slot)
            slot.status = "idle (no streams)"
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

        device_bus = self._ensure_device_bus(target_label=target_label, target_sink=target_sink)
        if not device_bus:
            self._stop_slot(slot)
            slot.status = f"device bus unavailable ({target_label})"
            return

        profile = self._current_profile(channel)
        dropin_text = self._render_eq_dropin(
            key=key,
            logical_sink=logical_sink,
            profile=profile,
            target_sink=device_bus,
        )
        signature = json.dumps(
            {
                "key": key,
                "profile": profile.to_dict(),
                "target_label": target_label,
                "target_sink": target_sink,
                "device_bus": device_bus,
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
            extra: list[str] = []
            if channel.muted:
                extra.append("muted")
            elif channel.volume != 100:
                extra.append(f"vol {channel.volume}%")
            suffix = f" • {', '.join(extra)}" if extra else ""
            slot.status = f"active ({profile.name} → {target_label} via {device_bus}, on-demand){suffix}"
            return

        tail = self._read_slot_log_tail(key)
        slot.status = f"failed ({tail or 'see log'})"

    def _reconcile_playback(self, settings: AppSettings) -> None:
        for key in PLAYBACK_EQ_CHANNELS:
            self._apply_eq_slot(settings, key)
        self._cleanup_unused_device_buses(settings)

    def status_text(self) -> str:
        self._maybe_reconcile_for_activity()
        return super().status_text()

    def meter_levels(self, channel_key: str) -> tuple[float, float]:
        self._maybe_reconcile_for_activity()
        if channel_key in PLAYBACK_EQ_CHANNELS and self._last_settings is not None:
            logical_sink = PLAYBACK_EQ_CHANNELS[channel_key]
            keep_alive = self._playback_channel_should_run(self._last_settings, channel_key, logical_sink)
            if not keep_alive:
                probe = self._meter_probes.get(channel_key)
                if probe is not None:
                    probe.stop()
                    self._meter_probes.pop(channel_key, None)
                return (0.0, 0.0)
        return super().meter_levels(channel_key)

    def apply_channel(self, settings: AppSettings, channel_key: str) -> None:
        self._last_settings = settings
        if channel_key in PLAYBACK_EQ_CHANNELS:
            self._apply_eq_slot(settings, channel_key)
            self._apply_micro_links(settings)
            self._cleanup_unused_device_buses(settings)
            self._last_activity_signature = self._playback_activity_signature()
            self._last_activity_check_monotonic = time.monotonic()
            return

        PipeWireAudioEngineBase.apply_channel(self, settings, channel_key)

    def apply_settings(self, settings: AppSettings) -> None:
        self._last_settings = settings
        self._reconcile_playback(settings)
        PipeWireAudioEngineBase.apply_channel(self, settings, "micro")
        PipeWireAudioEngineBase.apply_channel(self, settings, "return-mic")
        self._apply_micro_links(settings)
        self._last_activity_signature = self._playback_activity_signature()
        self._last_activity_check_monotonic = time.monotonic()

    def move_sink_input_to_channel(self, stream_id: int, channel_key: str) -> bool:
        moved = super().move_sink_input_to_channel(stream_id, channel_key)
        if moved and self._last_settings is not None:
            self._reconcile_playback(self._last_settings)
            self._last_activity_signature = self._playback_activity_signature()
            self._last_activity_check_monotonic = time.monotonic()
        return moved
