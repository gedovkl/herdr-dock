from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from streamdock_plugin.watch import FileWatcher, Signature, file_signature


class Scripted:
    """A signature source that returns one value per poll, then stops the watcher."""

    def __init__(self, *values: Signature) -> None:
        self.values = list(values)

    def __call__(self, _path: Path) -> Signature:
        return self.values.pop(0)


async def run_until_exhausted(source: Scripted, changes: list[str]) -> None:
    done = asyncio.Event()

    async def sleep(_: float) -> None:
        if not source.values:
            done.set()
            await asyncio.Event().wait()  # park until cancelled
        await asyncio.sleep(0)

    watcher = FileWatcher(
        Path("config.toml"), lambda: changes.append("changed"), sleep=sleep, signature=source
    )
    task = asyncio.create_task(watcher.run())
    await asyncio.wait_for(done.wait(), 2)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_the_state_at_the_start_is_not_a_change() -> None:
    changes: list[str] = []
    await run_until_exhausted(Scripted((1, 10), (1, 10), (1, 10)), changes)
    assert changes == []


async def test_each_new_signature_is_one_change() -> None:
    changes: list[str] = []
    await run_until_exhausted(Scripted((1, 10), (2, 10), (2, 10), (3, 11)), changes)
    assert changes == ["changed", "changed"]


async def test_a_file_appearing_or_vanishing_is_a_change() -> None:
    changes: list[str] = []
    await run_until_exhausted(Scripted(None, (1, 1), None), changes)
    assert changes == ["changed", "changed"]


async def test_a_failing_handler_does_not_stop_the_watcher(
    caplog: pytest.LogCaptureFixture,
) -> None:
    source = Scripted((1, 1), (2, 1), (3, 1))
    calls: list[int] = []
    done = asyncio.Event()

    def on_change() -> None:
        calls.append(1)
        raise RuntimeError("boom")

    async def sleep(_: float) -> None:
        if not source.values:
            done.set()
            await asyncio.Event().wait()
        await asyncio.sleep(0)

    task = asyncio.create_task(
        FileWatcher(Path("c"), on_change, sleep=sleep, signature=source).run()
    )
    await asyncio.wait_for(done.wait(), 2)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert len(calls) == 2
    assert "handling a change" in caplog.text


def test_the_real_signature_follows_the_file(tmp_path: Path) -> None:
    path = tmp_path / "c.toml"
    assert file_signature(path) is None
    path.write_text("a")
    first = file_signature(path)
    path.write_text("abc")
    assert first is not None and file_signature(path) != first
