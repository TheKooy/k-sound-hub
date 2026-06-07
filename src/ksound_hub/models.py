from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any

from .config import DEFAULT_CHANNELS, DEFAULT_EQ_BANDS


@dataclass
class EqBand:
    frequency: float
    gain_db: float
    q: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EqBand":
        return cls(
            frequency=float(data.get("frequency", 1000.0)),
            gain_db=float(data.get("gain_db", 0.0)),
            q=float(data.get("q", 1.0)),
        )


def _default_eq_band_frequencies() -> list[float]:
    return [float(item["frequency"]) for item in DEFAULT_EQ_BANDS]


def _interpolated_gain_db(source_bands: list[EqBand], target_frequency: float) -> float:
    """Map old presets to the current default EQ frequencies without losing their shape."""

    valid = sorted(
        (
            band
            for band in source_bands
            if float(band.frequency) > 0.0
        ),
        key=lambda band: float(band.frequency),
    )
    if not valid:
        return 0.0

    if len(valid) == 1:
        return round(float(valid[0].gain_db) * 2.0) / 2.0

    target_log = math.log(max(1.0, float(target_frequency)))
    points = [(math.log(max(1.0, float(band.frequency))), float(band.gain_db)) for band in valid]

    if target_log <= points[0][0]:
        return round(points[0][1] * 2.0) / 2.0
    if target_log >= points[-1][0]:
        return round(points[-1][1] * 2.0) / 2.0

    for (f1, g1), (f2, g2) in zip(points, points[1:], strict=False):
        if f1 <= target_log <= f2:
            span = max(0.000001, f2 - f1)
            ratio = (target_log - f1) / span
            gain = g1 + (g2 - g1) * ratio
            return round(gain * 2.0) / 2.0

    nearest = min(valid, key=lambda band: abs(math.log(float(band.frequency)) - target_log))
    return round(float(nearest.gain_db) * 2.0) / 2.0


def _normalized_eq_bands_for_load(source_bands: list[EqBand]) -> list[EqBand]:
    """Keep custom 10-band profiles intact; migrate old/short profiles to 10 bands."""

    if len(source_bands) == len(DEFAULT_EQ_BANDS):
        return [
            EqBand(
                frequency=max(20.0, min(20000.0, float(band.frequency))),
                gain_db=round(max(-12.0, min(12.0, float(band.gain_db))) * 2.0) / 2.0,
                q=max(0.1, min(10.0, float(band.q))),
            )
            for band in source_bands
        ]

    target_frequencies = _default_eq_band_frequencies()
    default_q = float(DEFAULT_EQ_BANDS[0].get("q", 1.0)) if DEFAULT_EQ_BANDS else 1.0
    return [
        EqBand(
            frequency=frequency,
            gain_db=_interpolated_gain_db(source_bands, frequency),
            q=default_q,
        )
        for frequency in target_frequencies
    ]


@dataclass
class EqProfile:
    name: str = "Default"
    bands: list[EqBand] = field(default_factory=list)

    @classmethod
    def default(cls, name: str = "Default") -> "EqProfile":
        return cls(name=name, bands=[EqBand.from_dict(item) for item in DEFAULT_EQ_BANDS])

    @classmethod
    def from_dict(cls, data: dict) -> "EqProfile":
        name = str(data.get("name", "Default"))
        bands = data.get("bands", [])
        if not isinstance(bands, list):
            bands = []

        parsed_bands = [EqBand.from_dict(item) for item in bands]
        if not parsed_bands:
            parsed_bands = [EqBand.from_dict(item) for item in DEFAULT_EQ_BANDS]

        return cls(
            name=name,
            bands=_normalized_eq_bands_for_load(parsed_bands),
        )

    def to_dict(self) -> dict:
        return {"name": self.name, "bands": [asdict(band) for band in self.bands]}


@dataclass
class ChannelConfig:
    key: str
    name: str
    enabled: bool = True
    kind: str = "playback"
    volume: int = 100
    muted: bool = False
    visualizer_enabled: bool = True
    primary_target: str = ""
    linked_channels: list[str] = field(default_factory=list)
    app_rules: list[str] = field(default_factory=list)
    eq_profiles: list[EqProfile] = field(default_factory=lambda: [EqProfile.default()])
    selected_eq_profile: str = "Default"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChannelConfig":
        profiles_raw = data.get("eq_profiles", [])
        profiles = [EqProfile.from_dict(item) for item in profiles_raw] if isinstance(profiles_raw, list) else []
        if not profiles:
            profiles = [EqProfile.default()]
        selected = str(data.get("selected_eq_profile", profiles[0].name))
        if selected not in {profile.name for profile in profiles}:
            selected = profiles[0].name
        return cls(
            key=str(data.get("key", "channel")),
            name=str(data.get("name", "Channel")),
            enabled=bool(data.get("enabled", True)),
            kind=str(data.get("kind", "playback")),
            volume=int(data.get("volume", 100)),
            muted=bool(data.get("muted", False)),
            visualizer_enabled=bool(data.get("visualizer_enabled", True)),
            primary_target=str(data.get("primary_target", "")),
            linked_channels=[
                str(item)
                for item in (data.get("linked_channels", []) if isinstance(data.get("linked_channels", []), list) else [])
            ],
            app_rules=[
                str(item)
                for item in (data.get("app_rules", []) if isinstance(data.get("app_rules", []), list) else [])
            ],
            eq_profiles=profiles,
            selected_eq_profile=selected,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "enabled": self.enabled,
            "kind": self.kind,
            "volume": self.volume,
            "muted": self.muted,
            "visualizer_enabled": self.visualizer_enabled,
            "primary_target": self.primary_target,
            "linked_channels": list(self.linked_channels),
            "app_rules": list(self.app_rules),
            "eq_profiles": [profile.to_dict() for profile in self.eq_profiles],
            "selected_eq_profile": self.selected_eq_profile,
        }


@dataclass
class AppSettings:
    overlay_enabled: bool = False
    visualizer_enabled: bool = True
    close_to_tray: bool = True
    wallpaper_enabled: bool = False
    wallpaper_path: str = ""
    wallpaper_blur: int = 0
    wallpaper_tint_strength: int = 40
    glass_background_blur: int = 18
    glass_background_saturation: int = 72
    glass_background_darkness: int = 55
    glass_opacity: int = 70
    channels: list[ChannelConfig] = field(default_factory=list)

    @classmethod
    def default(cls) -> "AppSettings":
        channels = [
            ChannelConfig(
                key=item["key"],
                name=item["name"],
                enabled=bool(item.get("enabled", True)),
                kind=str(item.get("kind", "playback")),
            )
            for item in DEFAULT_CHANNELS
        ]
        return cls(channels=channels)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppSettings":
        channels_raw = data.get("channels", [])
        channels = [ChannelConfig.from_dict(item) for item in channels_raw] if isinstance(channels_raw, list) else []
        if not channels:
            channels = cls.default().channels

        default_channel_names = {
            str(item["key"]): str(item["name"])
            for item in DEFAULT_CHANNELS
            if "key" in item and "name" in item
        }
        for channel in channels:
            if channel.key in default_channel_names:
                channel.name = default_channel_names[channel.key]

        close_to_tray = data.get("close_to_tray")
        if close_to_tray is None and isinstance(channels_raw, list):
            for item in channels_raw:
                if isinstance(item, dict) and "close_to_tray" in item:
                    close_to_tray = bool(item.get("close_to_tray", True))
                    break
        if close_to_tray is None:
            close_to_tray = True

        return cls(
            overlay_enabled=bool(data.get("overlay_enabled", False)),
            visualizer_enabled=bool(data.get("visualizer_enabled", True)),
            close_to_tray=bool(close_to_tray),
            wallpaper_enabled=bool(data.get("wallpaper_enabled", False)),
            wallpaper_path=str(data.get("wallpaper_path", "")),
            wallpaper_blur=max(0, min(32, int(data.get("wallpaper_blur", 0)))),
            wallpaper_tint_strength=max(0, min(100, int(data.get("wallpaper_tint_strength", 40)))),
            glass_background_blur=max(0, min(100, int(data.get("glass_background_blur", 18)))),
            glass_background_saturation=max(0, min(100, int(data.get("glass_background_saturation", 72)))),
            glass_background_darkness=max(0, min(100, int(data.get("glass_background_darkness", 55)))),
            glass_opacity=max(0, min(100, int(data.get("glass_opacity", 70)))),
            channels=channels,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "overlay_enabled": self.overlay_enabled,
            "visualizer_enabled": self.visualizer_enabled,
            "close_to_tray": self.close_to_tray,
            "wallpaper_enabled": self.wallpaper_enabled,
            "wallpaper_path": self.wallpaper_path,
            "wallpaper_blur": self.wallpaper_blur,
            "wallpaper_tint_strength": self.wallpaper_tint_strength,
            "glass_background_blur": self.glass_background_blur,
            "glass_background_saturation": self.glass_background_saturation,
            "glass_background_darkness": self.glass_background_darkness,
            "glass_opacity": self.glass_opacity,
            "channels": [channel.to_dict() for channel in self.channels],
        }
