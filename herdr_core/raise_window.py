"""Bring the terminal window to the front after focusing an agent."""

from __future__ import annotations

import asyncio
import logging
import shlex
import sys
from collections.abc import Awaitable, Callable

from herdr_core.config import RaiseConfig
from herdr_core.models import Agent

log = logging.getLogger(__name__)

CommandRunner = Callable[[str], Awaitable[int]]

_PLACEHOLDERS = ("pane_id", "workspace_id", "tab_id", "cwd", "kind")


async def run_shell(command: str, timeout: float = 5.0) -> int:
    """Run a shell command without output; returns its exit code (-1 on timeout)."""
    process = await asyncio.create_subprocess_shell(
        command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    try:
        return await asyncio.wait_for(process.wait(), timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        return -1


class NullRaiser:
    async def raise_window(self, agent: Agent) -> None:
        return None


class CommandRaiser:
    """Runs a configured shell command. `{pane_id}`, `{workspace_id}`, `{tab_id}`, `{cwd}` and
    `{kind}` are replaced with shell-quoted values; write literal braces as `{{` and `}}`."""

    def __init__(self, template: str, runner: CommandRunner = run_shell) -> None:
        try:
            template.format(**dict.fromkeys(_PLACEHOLDERS, ""))
        except (KeyError, IndexError, ValueError) as exc:
            raise ValueError(f"invalid raise command {template!r}: {exc}") from exc
        self._template = template
        self._runner = runner

    def command_for(self, agent: Agent) -> str:
        values = {
            "pane_id": agent.pane_id,
            "workspace_id": agent.workspace_id,
            "tab_id": agent.tab_id,
            "cwd": agent.cwd,
            "kind": agent.kind,
        }
        return self._template.format(**{key: shlex.quote(value) for key, value in values.items()})

    async def raise_window(self, agent: Agent) -> None:
        command = self.command_for(agent)
        try:
            code = await self._runner(command)
        except OSError as exc:
            log.warning("raise command failed to start: %s", exc)
            return
        if code != 0:
            log.warning("raise command exited with %s: %s", code, command)


def raiser_from_config(
    config: RaiseConfig, platform: str = sys.platform, runner: CommandRunner = run_shell
) -> CommandRaiser | NullRaiser:
    template = config.macos if platform == "darwin" else config.linux
    if not config.enabled or not template.strip():
        return NullRaiser()
    return CommandRaiser(template, runner)
