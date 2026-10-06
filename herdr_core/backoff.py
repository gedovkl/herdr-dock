"""Reconnect delays."""

from __future__ import annotations


class Backoff:
    """Exponential backoff: initial, initial*factor, ... capped at maximum."""

    def __init__(self, initial: float = 0.5, factor: float = 2.0, maximum: float = 10.0) -> None:
        if initial <= 0 or factor < 1 or maximum < initial:
            raise ValueError("invalid backoff parameters")
        self._initial = initial
        self._factor = factor
        self._maximum = maximum
        self._next = initial

    def next_delay(self) -> float:
        delay = self._next
        self._next = min(self._next * self._factor, self._maximum)
        return delay

    def reset(self) -> None:
        self._next = self._initial
