from __future__ import annotations

from dataclasses import asdict, dataclass, field
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


@dataclass
class EqProfile:
    name: str
    bands: list[EqBand] = field(default_factory=list)

    @classmethod
    def default(cls, name: str = "Default") -> "EqProfile":
        return cls(name=name, bands=[EqBand.from_dict(item) for item in DEFAULT_EQ_BANDS])

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EqProfile":
        bands = data.get("bands", [])
        if not isinstance(bands, list):
            bands = []
        return cls(
            name=str(data.get("name", "Default")),
            bands=[EqBand.from_dict(item) for item in bands],
        )

    def to_dict(self) -> dict[str, Any]:
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
    close_to_tray: bool = True
    primary_target: str = ""
    secondary_target: str = ""
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
            close_to_tray=bool(data.get("close_to_tray", True)),
            primary_target=str(data.get("primary_target", "")),
            secondary_target=str(data.get("secondary_target", "")),
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
            "close_to_tray": self.close_to_tray,
            "primary_target": self.primary_target,
            "secondary_target": self.secondary_target,
            "eq_profiles": [profile.to_dict() for profile in self.eq_profiles],
            "selected_eq_profile": self.selected_eq_profile,
        }


@dataclass
class AppSettings:
    overlay_enabled: bool = False
    visualizer_enabled: bool = True
    wallpaper_enabled: bool = False
    wallpaper_path: str = ""
    wallpaper_blur: int = 0
    wallpaper_tint_strength: int = 40
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
        return cls(
            overlay_enabled=bool(data.get("overlay_enabled", False)),
            visualizer_enabled=bool(data.get("visualizer_enabled", True)),
            wallpaper_enabled=bool(data.get("wallpaper_enabled", False)),
            wallpaper_path=str(data.get("wallpaper_path", "")),
            wallpaper_blur=max(0, min(32, int(data.get("wallpaper_blur", 0)))),
            wallpaper_tint_strength=max(0, min(100, int(data.get("wallpaper_tint_strength", 40)))),
            channels=channels,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "overlay_enabled": self.overlay_enabled,
            "visualizer_enabled": self.visualizer_enabled,
            "wallpaper_enabled": self.wallpaper_enabled,
            "wallpaper_path": self.wallpaper_path,
            "wallpaper_blur": self.wallpaper_blur,
            "wallpaper_tint_strength": self.wallpaper_tint_strength,
            "channels": [channel.to_dict() for channel in self.channels],
        }
