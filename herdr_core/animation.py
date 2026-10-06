"""Which keys animate and which frame they show at a given time.

Frames are a pure function of time, so every blinking key flashes in phase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from herdr_core.faces import AgentFace, ExitFace, Face, PagerFace
from herdr_core.models import AgentStatus

SPINNER_FRAMES: tuple[str, ...] = ("◐", "◓", "◑", "◒")


class Effect(Enum):
    NONE = "none"
    SPIN = "spin"
    BLINK = "blink"
    PULSE = "pulse"


_FRAME_COUNT = {Effect.NONE: 1, Effect.SPIN: len(SPINNER_FRAMES), Effect.BLINK: 2, Effect.PULSE: 2}


@dataclass(frozen=True, slots=True)
class AnimationConfig:
    enabled: bool = True
    blink_hz: float = 2.0
    spinner_fps: float = 4.0
    pulse_hz: float = 0.7
    attention: frozenset[AgentStatus] = field(
        default_factory=lambda: frozenset({AgentStatus.BLOCKED})
    )

    def __post_init__(self) -> None:
        for name in ("blink_hz", "spinner_fps", "pulse_hz"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")


class Animator:
    def __init__(self, config: AnimationConfig | None = None) -> None:
        self._config = config or AnimationConfig()

    @property
    def tick_interval(self) -> float:
        """Seconds between frame changes of the fastest effect."""
        c = self._config
        return 1.0 / max(c.spinner_fps, c.blink_hz * 2, c.pulse_hz * 2)

    def effect(self, face: Face) -> Effect:
        if not self._config.enabled:
            return Effect.NONE
        if isinstance(face, AgentFace):
            if face.status in self._config.attention:
                return self._attention_effect({face.status})
            return Effect.SPIN if face.status is AgentStatus.WORKING else Effect.NONE
        if isinstance(face, PagerFace):
            return self._attention_effect(set(face.offpage))
        if isinstance(face, ExitFace):
            return self._attention_effect(set(face.statuses))
        return Effect.NONE

    def frame(self, effect: Effect, now: float) -> int:
        c = self._config
        if effect is Effect.SPIN:
            return int(now * c.spinner_fps) % len(SPINNER_FRAMES)
        if effect is Effect.BLINK:
            return int(now * c.blink_hz * 2) % 2
        if effect is Effect.PULSE:
            return int(now * c.pulse_hz * 2) % 2
        return 0

    @staticmethod
    def frame_count(effect: Effect) -> int:
        return _FRAME_COUNT[effect]

    def _attention_effect(self, statuses: set[AgentStatus]) -> Effect:
        wanted = statuses & self._config.attention
        if AgentStatus.BLOCKED in wanted:
            return Effect.BLINK
        return Effect.PULSE if wanted else Effect.NONE
