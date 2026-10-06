"""Print live herdr agent states in the terminal: `python -m herdr_core.console`."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from collections.abc import Awaitable, Mapping, Sequence
from pathlib import Path
from typing import TextIO

from herdr_core.client import HerdrSocketClient
from herdr_core.config import Config, ConfigError, load_config
from herdr_core.errors import HerdrError
from herdr_core.models import Agent, LabelStyle
from herdr_core.paging import paginate
from herdr_core.raise_window import NullRaiser
from herdr_core.session import HerdrSession, SessionView
from herdr_core.socket_path import StatusReader, read_herdr_status, resolve_socket_path
from herdr_core.theme import STATUS_PRIORITY, STATUS_SYMBOL

_CLEAR = "\033[H\033[2J"


def format_agent(key: int, agent: Agent, label: LabelStyle) -> str:
    symbol = STATUS_SYMBOL[agent.status]
    focus = "*" if agent.focused else " "
    return (
        f"{key:>3}{focus} {symbol}  {agent.kind:<10} {agent.status.value:<8} "
        f"{agent.label(label):<24} {agent.pane_id}"
    )


def format_view(view: SessionView, label: LabelStyle) -> str:
    page = view.page
    state = "connected" if view.connected else "offline"
    lines = [
        f"herdr: {state} · {view.total_agents} agents · page {page.page + 1}/{page.page_count}"
    ]
    last = max((i for i, agent in enumerate(page.agents) if agent is not None), default=-1)
    for index, agent in enumerate(page.agents[: last + 1]):
        key = index + 1
        lines.append(f"{key:>3}  -" if agent is None else format_agent(key, agent, label))
    if page.has_pager:
        offpage = "".join(
            STATUS_SYMBOL[status] for status in STATUS_PRIORITY if status in page.offpage_statuses
        )
        lines.append(f"{len(page.agents) + 1:>3}  ▶ next page   off-page: {offpage or '-'}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="herdr-dock-console", description="Print live herdr agent states."
    )
    parser.add_argument("--socket", help="herdr socket path (default: auto-detect)")
    parser.add_argument("--config", type=Path, help="config file (default: ~/.config/herdr-dock)")
    parser.add_argument("--once", action="store_true", help="print the agent list once and exit")
    parser.add_argument(
        "--capacity", type=int, default=14, help="agent keys per page (default: 14, as on the M18)"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="debug logging to stderr")
    return parser


async def print_once(client: HerdrSocketClient, config: Config, capacity: int, out: TextIO) -> int:
    agents = await client.list_agents()
    page = paginate(agents, max(capacity, len(agents), 2), 0)
    view = SessionView(True, page, len(agents), frozenset(a.status for a in agents))
    print(format_view(view, config.label), file=out)
    return 0


async def follow(
    client: HerdrSocketClient,
    config: Config,
    capacity: int,
    out: TextIO,
    until: Awaitable[object],
) -> int:
    clear = _CLEAR if out.isatty() else ""

    def show(view: SessionView) -> None:
        print(clear + format_view(view, config.label), file=out, flush=True)
        if not clear:
            print(file=out, flush=True)

    session = HerdrSession(
        client,
        client,
        NullRaiser(),
        capacity=capacity,
        on_view=show,
        resync_interval=config.resync_seconds,
    )
    await session.start()
    try:
        await until
    finally:
        await session.stop()
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    out: TextIO = sys.stdout,
    env: Mapping[str, str] = os.environ,
    read_status: StatusReader = read_herdr_status,
) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if args.capacity < 2:
        print("error: --capacity must be at least 2", file=sys.stderr)
        return 2
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    socket = resolve_socket_path(args.socket or config.herdr_socket, env, Path.home(), read_status)
    client = HerdrSocketClient(socket)

    if args.once:
        try:
            return asyncio.run(print_once(client, config, args.capacity, out))
        except HerdrError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    try:
        return asyncio.run(_follow_forever(client, config, args.capacity, out))
    except KeyboardInterrupt:
        return 0


async def _follow_forever(
    client: HerdrSocketClient, config: Config, capacity: int, out: TextIO
) -> int:
    return await follow(client, config, capacity, out, asyncio.Event().wait())


if __name__ == "__main__":
    raise SystemExit(main())
