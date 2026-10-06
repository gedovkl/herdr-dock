from __future__ import annotations

import shutil
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from tests.fakes.herdr_server import FakeHerdrServer


@pytest.fixture
def short_dir() -> Iterator[Path]:
    """A short temp dir: Unix socket paths are limited to ~104 bytes on macOS."""
    path = Path(tempfile.mkdtemp(prefix="hd-", dir="/tmp"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
async def herdr_server(short_dir: Path) -> AsyncIterator[FakeHerdrServer]:
    async with FakeHerdrServer(short_dir / "herdr.sock") as server:
        yield server
