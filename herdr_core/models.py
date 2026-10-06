"""Value objects describing herdr agents."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Literal

from herdr_core.errors import HerdrProtocolError

LabelStyle = Literal["cwd", "title", "name"]


class AgentStatus(StrEnum):
    IDLE = "idle"
    WORKING = "working"
    BLOCKED = "blocked"
    DONE = "done"
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, value: object) -> AgentStatus:
        """Map a wire value to a status; anything unrecognised is UNKNOWN."""
        try:
            return cls(str(value))
        except ValueError:
            return cls.UNKNOWN


@dataclass(frozen=True, slots=True)
class Agent:
    pane_id: str
    workspace_id: str
    tab_id: str
    kind: str
    status: AgentStatus
    cwd: str = ""
    title: str = ""
    name: str | None = None
    focused: bool = False

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> Agent:
        pane_id = raw.get("pane_id")
        if not isinstance(pane_id, str) or not pane_id:
            raise HerdrProtocolError(f"agent without pane_id: {raw!r}")
        workspace_id = _text(raw, "workspace_id") or pane_id.split(":", 1)[0]
        return cls(
            pane_id=pane_id,
            workspace_id=workspace_id,
            tab_id=_text(raw, "tab_id"),
            kind=_text(raw, "agent") or "agent",
            status=AgentStatus.parse(raw.get("agent_status")),
            cwd=_text(raw, "foreground_cwd") or _text(raw, "cwd"),
            title=_text(raw, "terminal_title_stripped") or _text(raw, "terminal_title"),
            name=_text(raw, "name") or None,
            focused=raw.get("focused") is True,
        )

    def with_status(self, status: AgentStatus) -> Agent:
        return replace(self, status=status)

    def with_focus(self, focused: bool) -> Agent:
        return replace(self, focused=focused)

    def label(self, style: LabelStyle) -> str:
        """Short human label for a key, per the configured style."""
        if style == "title" and self.title:
            return self.title
        if style == "name" and self.name:
            return self.name
        return os.path.basename(self.cwd.rstrip("/")) or self.cwd or self.pane_id


def _text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    return value if isinstance(value, str) else ""
