from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class AudioNode:
    name: str
    kind: str
    state: str = "unknown"


class AudioEngine(ABC):
    @abstractmethod
    def list_sinks(self) -> list[AudioNode]:
        raise NotImplementedError

    @abstractmethod
    def list_sources(self) -> list[AudioNode]:
        raise NotImplementedError

    @abstractmethod
    def status_text(self) -> str:
        raise NotImplementedError
