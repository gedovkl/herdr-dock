"""A fake herdr server speaking the real NDJSON protocol over a Unix socket."""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class _Subscriber:
    writer: asyncio.StreamWriter
    subscriptions: list[dict[str, Any]]

    def wants(self, subscription_type: str, pane_id: str | None) -> bool:
        for sub in self.subscriptions:
            if sub.get("type") != subscription_type:
                continue
            if "pane_id" in sub and sub["pane_id"] != pane_id:
                continue
            return True
        return False


@dataclass
class FakeHerdrServer:
    path: Path
    agents: list[dict[str, Any]] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)
    errors: dict[str, tuple[str, str]] = field(default_factory=dict)
    """method -> (code, message) to answer with an error."""
    raw_replies: dict[str, bytes] = field(default_factory=dict)
    """method -> exact bytes to send instead of a proper reply."""
    silent: set[str] = field(default_factory=set)
    """methods that never get a reply."""
    _subscribers: list[_Subscriber] = field(default_factory=list)
    _server: asyncio.Server | None = None
    _handlers: set[asyncio.Task[None]] = field(default_factory=set)

    async def __aenter__(self) -> FakeHerdrServer:
        self._server = await asyncio.start_unix_server(self._handle, path=str(self.path))
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.drop_subscribers()
        assert self._server is not None
        self._server.close()
        for task in list(self._handlers):
            task.cancel()
        await self._server.wait_closed()

    def add_agent(self, pane_id: str, status: str = "idle", **extra: Any) -> dict[str, Any]:
        workspace_id, _, _ = pane_id.partition(":")
        agent: dict[str, Any] = {
            "pane_id": pane_id,
            "workspace_id": workspace_id,
            "tab_id": f"{workspace_id}:t1",
            "agent": "claude",
            "agent_status": status,
            "cwd": f"/home/u/{workspace_id}",
            "terminal_title_stripped": f"title {pane_id}",
            "focused": False,
        }
        agent.update(extra)
        self.agents.append(agent)
        return agent

    def subscription_count(self) -> int:
        return len(self._subscribers)

    def last_subscriptions(self) -> list[dict[str, Any]]:
        return self._subscribers[-1].subscriptions if self._subscribers else []

    async def set_status(self, pane_id: str, status: str) -> None:
        for agent in self.agents:
            if agent["pane_id"] == pane_id:
                agent["agent_status"] = status
        await self.emit(
            "pane.agent_status_changed",
            {"pane_id": pane_id, "agent_status": status, "agent": "claude"},
            subscription="pane.agent_status_changed",
            pane_id=pane_id,
        )

    async def emit(
        self,
        event: str,
        data: dict[str, Any],
        *,
        subscription: str,
        pane_id: str | None = None,
    ) -> None:
        line = json.dumps({"event": event, "data": data}).encode() + b"\n"
        for sub in list(self._subscribers):
            if sub.wants(subscription, pane_id):
                sub.writer.write(line)
                with contextlib.suppress(ConnectionError):
                    await sub.writer.drain()

    async def drop_subscribers(self) -> None:
        subscribers, self._subscribers = self._subscribers, []
        for sub in subscribers:
            sub.writer.close()
            with contextlib.suppress(ConnectionError):
                await sub.writer.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        self._handlers.add(task)
        try:
            line = await reader.readline()
            if not line:
                return
            request = json.loads(line)
            self.requests.append(request)
            method = request["method"]
            if method in self.silent:
                await reader.read()  # hold the connection open until the client gives up
                return
            if method in self.raw_replies:
                writer.write(self.raw_replies[method])
                await writer.drain()
                return
            if method in self.errors:
                code, message = self.errors[method]
                await self._reply(writer, request, error={"code": code, "message": message})
                return
            if method == "events.subscribe":
                await self._reply(writer, request, result={"type": "subscription_started"})
                sub = _Subscriber(writer, request["params"]["subscriptions"])
                self._subscribers.append(sub)
                await reader.read()  # stream until the client disconnects
                if sub in self._subscribers:
                    self._subscribers.remove(sub)
                return
            await self._dispatch(writer, request)
        except asyncio.CancelledError:
            pass
        finally:
            self._handlers.discard(task)
            writer.close()

    async def _dispatch(self, writer: asyncio.StreamWriter, request: dict[str, Any]) -> None:
        method, params = request["method"], request.get("params", {})
        if method == "agent.list":
            agents = [dict(agent) for agent in self.agents]
            await self._reply(writer, request, result={"type": "agent_list", "agents": agents})
        elif method == "agent.focus":
            await self._focus(writer, request, params["target"])
        else:
            error = {"code": "unknown_method", "message": method}
            await self._reply(writer, request, error=error)

    async def _focus(
        self, writer: asyncio.StreamWriter, request: dict[str, Any], target: str
    ) -> None:
        match = next((a for a in self.agents if target in (a["pane_id"], a.get("name"))), None)
        if match is None:
            error = {"code": "agent_not_found", "message": f"agent target {target} not found"}
            await self._reply(writer, request, error=error)
            return
        for agent in self.agents:
            agent["focused"] = agent is match
        await self._reply(writer, request, result={"type": "agent_info", "agent": dict(match)})
        if match["agent_status"] == "done":
            await self.set_status(match["pane_id"], "idle")
        await self.emit(
            "pane_focused",
            {"type": "pane_focused", "pane_id": match["pane_id"]},
            subscription="pane.focused",
        )

    @staticmethod
    async def _reply(
        writer: asyncio.StreamWriter,
        request: dict[str, Any],
        *,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        message: dict[str, Any] = {"id": request.get("id", "")}
        if error is not None:
            message["error"] = error
        else:
            message["result"] = result
        writer.write(json.dumps(message).encode() + b"\n")
        await writer.drain()
