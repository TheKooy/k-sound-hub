from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import AppSettings


@dataclass
class AudioNode:
    name: str
    kind: str
    state: str = "unknown"


@dataclass
class AppStream:
    stream_id: int
    display_name: str
    sink_name: str = ""
    app_name: str = ""
    binary_name: str = ""
    media_name: str = ""
    node_name: str = ""


class AudioEngine(ABC):
    @abstractmethod
    def list_sinks(self) -> list[AudioNode]:
        raise NotImplementedError

    @abstractmethod
    def list_sources(self) -> list[AudioNode]:
        raise NotImplementedError

    @abstractmethod
    def list_sink_inputs(self) -> list[AppStream]:
        raise NotImplementedError

    @abstractmethod
    def move_sink_input_to_channel(self, stream_id: int, channel_key: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def meter_levels(self, channel_key: str) -> tuple[float, float]:
        raise NotImplementedError

    @abstractmethod
    def apply_channel(self, settings: AppSettings, channel_key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def apply_settings(self, settings: AppSettings) -> None:
        raise NotImplementedError

    @abstractmethod
    def shutdown(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def status_text(self) -> str:
        raise NotImplementedError
