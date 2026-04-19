from __future__ import annotations

import subprocess
from typing import Iterable

from .engine import AudioEngine, AudioNode


class PipeWireAudioEngine(AudioEngine):
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

    def status_text(self) -> str:
        sinks = len(self.list_sinks())
        sources = len(self.list_sources())
        return f"PipeWire backend available • sinks: {sinks} • sources: {sources}"
