"""Composition helpers shared by every front end: the herdr stack and logging setup."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Protocol

from herdr_core.animation import Animator
from herdr_core.client import HerdrSocketClient
from herdr_core.config import Config
from herdr_core.faces import KeyLayout
from herdr_core.ports import KeySurface, Raiser
from herdr_core.presenter import DeckPresenter
from herdr_core.render import KeyRenderer, Palette
from herdr_core.session import HerdrSession


class Startable(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...


class Redrawable(Startable, Protocol):
    def invalidate(self) -> None: ...


async def start_herdr(presenter: Redrawable, session: Startable) -> None:
    """Begin showing herdr: redraw everything, then follow the agents."""
    presenter.invalidate()
    await presenter.start()
    await session.start()


async def stop_herdr(presenter: Startable, session: Startable) -> None:
    """Stop drawing first, so the session's final "offline" view never reaches the keys."""
    await presenter.stop()
    await session.stop()


@dataclass(frozen=True, slots=True)
class HerdrStack:
    """What a front end needs to show herdr agents on a surface."""

    renderer: KeyRenderer
    presenter: DeckPresenter
    session: HerdrSession


def build_herdr_stack(
    config: Config,
    surface: KeySurface,
    raiser: Raiser,
    socket: Path,
    *,
    layout: KeyLayout,
    key_count: int,
    key_size: int = 64,
) -> HerdrStack:
    """Wire renderer → presenter → surface and a session that feeds the presenter."""
    renderer = KeyRenderer(Palette().with_status_colors(config.colors), size=key_size)
    presenter = DeckPresenter(
        surface, renderer, Animator(config.animation), layout=layout, label=config.label
    )
    client = HerdrSocketClient(socket)
    session = HerdrSession(
        client,
        client,
        raiser,
        capacity=layout.session_capacity(key_count),
        on_view=presenter.update,
        resync_interval=config.resync_seconds,
    )
    return HerdrStack(renderer, presenter, session)


def configure_logging(*, verbose: bool, log_file: Path | None = None) -> None:
    """Root logging for a front end: stderr, plus an optional file (plugins have no terminal)."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        )
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.getLogger("PIL").setLevel(logging.INFO)  # chunk-level PNG debug noise
