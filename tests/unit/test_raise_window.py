import pytest

from herdr_core.config import RaiseConfig
from herdr_core.models import Agent, AgentStatus
from herdr_core.raise_window import CommandRaiser, NullRaiser, raiser_from_config, run_shell

AGENT = Agent("w2:p1", "w2", "w2:t1", "claude", AgentStatus.DONE, cwd="/home/u/my project")


class Runner:
    def __init__(self, code: int = 0, error: OSError | None = None) -> None:
        self.commands: list[str] = []
        self.code = code
        self.error = error

    async def __call__(self, command: str) -> int:
        self.commands.append(command)
        if self.error:
            raise self.error
        return self.code


def test_placeholders_are_shell_quoted() -> None:
    raiser = CommandRaiser("focus {pane_id} {workspace_id} {tab_id} {cwd} {kind} {{literal}}")
    assert raiser.command_for(AGENT) == "focus w2:p1 w2 w2:t1 '/home/u/my project' claude {literal}"


@pytest.mark.parametrize("template", ["focus {unknown}", "focus {0}", "focus {"])
def test_invalid_templates_are_rejected(template: str) -> None:
    with pytest.raises(ValueError, match="invalid raise command"):
        CommandRaiser(template)


async def test_runs_command() -> None:
    runner = Runner()
    await CommandRaiser("activate {kind}", runner).raise_window(AGENT)
    assert runner.commands == ["activate claude"]


async def test_failures_are_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    await CommandRaiser("x", Runner(code=3)).raise_window(AGENT)
    await CommandRaiser("x", Runner(error=FileNotFoundError("sh"))).raise_window(AGENT)
    assert "exited with 3" in caplog.text
    assert "failed to start" in caplog.text


async def test_null_raiser_does_nothing() -> None:
    await NullRaiser().raise_window(AGENT)


@pytest.mark.parametrize(
    ("config", "platform", "expected"),
    [
        (RaiseConfig(linux="lx", macos="mc"), "linux", "lx"),
        (RaiseConfig(linux="lx", macos="mc"), "darwin", "mc"),
        (RaiseConfig(enabled=False, linux="lx"), "linux", None),
        (RaiseConfig(linux="   "), "linux", None),
    ],
)
def test_raiser_from_config(config: RaiseConfig, platform: str, expected: str | None) -> None:
    raiser = raiser_from_config(config, platform)
    if expected is None:
        assert isinstance(raiser, NullRaiser)
    else:
        assert isinstance(raiser, CommandRaiser) and raiser.command_for(AGENT) == expected


async def test_run_shell_exit_codes_and_timeout() -> None:
    assert await run_shell("true") == 0
    assert await run_shell("exit 4") == 4
    assert await run_shell("sleep 5", timeout=0.05) == -1
