"""herdr socket API client: NDJSON over a Unix socket."""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Any

from herdr_core.errors import HerdrProtocolError, HerdrRequestError, HerdrUnavailable
from herdr_core.events import TOPOLOGY_SUBSCRIPTIONS, HerdrEvent, parse_event
from herdr_core.models import Agent

log = logging.getLogger(__name__)

# agent.list can be large with many panes; asyncio's default 64 KiB line limit is too small.
_LINE_LIMIT = 16 * 1024 * 1024


class HerdrSocketClient:
    """Implements HerdrApi and HerdrEventSource against a herdr server socket."""

    def __init__(self, socket_path: Path, *, timeout: float = 5.0) -> None:
        self._path = socket_path
        self._timeout = timeout
        self._ids = itertools.count(1)

    @property
    def socket_path(self) -> Path:
        return self._path

    async def request(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        """Send one request on a fresh connection and return its `result`."""
        reader, writer = await self._connect()
        try:
            await self._send(writer, method, params)
            return _unwrap(await self._read_message(reader))
        finally:
            await _close(writer)

    async def list_agents(self) -> list[Agent]:
        result = await self.request("agent.list", {})
        agents = result.get("agents")
        if not isinstance(agents, list):
            raise HerdrProtocolError(f"agent.list without agents: {result!r}")
        return [Agent.from_api(raw) for raw in agents if isinstance(raw, Mapping)]

    async def focus_agent(self, pane_id: str) -> None:
        await self.request("agent.focus", {"target": pane_id})

    async def focus_tab(self, tab_id: str) -> None:
        await self.request("tab.focus", {"tab_id": tab_id})

    async def subscribe(self, status_pane_ids: Collection[str]) -> SocketEventStream:
        subscriptions: list[dict[str, str]] = [
            {"type": "pane.agent_status_changed", "pane_id": pane_id}
            for pane_id in sorted(status_pane_ids)
        ]
        subscriptions += [{"type": kind} for kind in TOPOLOGY_SUBSCRIPTIONS]
        reader, writer = await self._connect()
        try:
            await self._send(writer, "events.subscribe", {"subscriptions": subscriptions})
            started = _unwrap(await self._read_message(reader))
        except BaseException:
            await _close(writer)
            raise
        if started.get("type") != "subscription_started":
            await _close(writer)
            raise HerdrProtocolError(f"unexpected subscribe reply: {started!r}")
        return SocketEventStream(reader, writer)

    async def _connect(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        try:
            return await asyncio.wait_for(
                asyncio.open_unix_connection(str(self._path), limit=_LINE_LIMIT), self._timeout
            )
        except (OSError, TimeoutError) as exc:
            raise HerdrUnavailable(f"cannot connect to {self._path}: {exc}") from exc

    async def _send(
        self, writer: asyncio.StreamWriter, method: str, params: Mapping[str, Any]
    ) -> None:
        message = {"id": f"herdr-dock-{next(self._ids)}", "method": method, "params": params}
        try:
            writer.write(json.dumps(message).encode() + b"\n")
            await writer.drain()
        except OSError as exc:
            raise HerdrUnavailable(f"write to herdr failed: {exc}") from exc

    async def _read_message(self, reader: asyncio.StreamReader) -> dict[str, Any]:
        try:
            line = await asyncio.wait_for(reader.readline(), self._timeout)
        except (OSError, TimeoutError, ValueError) as exc:
            raise HerdrUnavailable(f"read from herdr failed: {exc}") from exc
        return _decode(line)


class SocketEventStream:
    """An open events.subscribe connection."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader = reader
        self._writer = writer

    async def next_event(self) -> HerdrEvent:
        try:
            line = await self._reader.readline()
        except (OSError, ValueError) as exc:
            raise HerdrUnavailable(f"event stream failed: {exc}") from exc
        return parse_event(_decode(line))

    async def close(self) -> None:
        await _close(self._writer)


def _decode(line: bytes) -> dict[str, Any]:
    if not line:
        raise HerdrUnavailable("herdr closed the connection")
    try:
        message = json.loads(line)
    except json.JSONDecodeError as exc:
        raise HerdrProtocolError(f"invalid JSON from herdr: {line[:200]!r}") from exc
    if not isinstance(message, dict):
        raise HerdrProtocolError(f"expected a JSON object, got: {line[:200]!r}")
    return message


def _unwrap(message: Mapping[str, Any]) -> dict[str, Any]:
    error = message.get("error")
    if isinstance(error, Mapping):
        raise HerdrRequestError(str(error.get("code", "error")), str(error.get("message", "")))
    result = message.get("result")
    if not isinstance(result, dict):
        raise HerdrProtocolError(f"response without result: {message!r}")
    return result


async def _close(writer: asyncio.StreamWriter) -> None:
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        log.debug("error while closing herdr connection", exc_info=True)
