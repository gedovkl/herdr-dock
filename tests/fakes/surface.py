"""Fake KeySurface and clock."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FakeSurface:
    shown: dict[int, bytes] = field(default_factory=dict)
    calls: list[int] = field(default_factory=list)
    fail_keys: set[int] = field(default_factory=set)

    async def show(self, key: int, png: bytes) -> None:
        self.calls.append(key)
        if key in self.fail_keys:
            raise OSError("device gone")
        self.shown[key] = png


@dataclass
class FakeClock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now
