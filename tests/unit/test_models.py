import pytest

from herdr_core.errors import HerdrProtocolError
from herdr_core.models import Agent, AgentStatus


def raw_agent(**overrides: object) -> dict[str, object]:
    raw: dict[str, object] = {
        "pane_id": "w2:p1",
        "workspace_id": "w2",
        "tab_id": "w2:t1",
        "agent": "claude",
        "agent_status": "working",
        "cwd": "/home/u/Projects",
        "foreground_cwd": "/home/u/Projects/api",
        "terminal_title": "◐ Fix tests",
        "terminal_title_stripped": "Fix tests",
        "focused": True,
    }
    raw.update(overrides)
    return raw


def test_status_parse_known_and_unknown() -> None:
    assert AgentStatus.parse("blocked") is AgentStatus.BLOCKED
    assert AgentStatus.parse("sleeping") is AgentStatus.UNKNOWN
    assert AgentStatus.parse(None) is AgentStatus.UNKNOWN


def test_from_api_reads_all_fields() -> None:
    agent = Agent.from_api(raw_agent(name="reviewer"))
    assert agent == Agent(
        pane_id="w2:p1",
        workspace_id="w2",
        tab_id="w2:t1",
        kind="claude",
        status=AgentStatus.WORKING,
        cwd="/home/u/Projects/api",
        title="Fix tests",
        name="reviewer",
        focused=True,
    )


def test_from_api_falls_back_for_missing_fields() -> None:
    agent = Agent.from_api({"pane_id": "w7:p3", "terminal_title": "raw", "cwd": "/x"})
    assert agent.workspace_id == "w7"
    assert agent.kind == "agent"
    assert agent.status is AgentStatus.UNKNOWN
    assert agent.cwd == "/x"
    assert agent.title == "raw"
    assert agent.name is None
    assert agent.focused is False


@pytest.mark.parametrize("pane_id", [None, "", 3])
def test_from_api_requires_pane_id(pane_id: object) -> None:
    with pytest.raises(HerdrProtocolError):
        Agent.from_api(raw_agent(pane_id=pane_id))


def test_with_status_and_focus_return_new_objects() -> None:
    agent = Agent.from_api(raw_agent())
    done = agent.with_status(AgentStatus.DONE)
    assert done.status is AgentStatus.DONE and agent.status is AgentStatus.WORKING
    assert agent.with_focus(False).focused is False


@pytest.mark.parametrize(
    ("style", "overrides", "expected"),
    [
        ("cwd", {}, "api"),
        ("cwd", {"foreground_cwd": "/home/u/web/"}, "web"),
        ("cwd", {"foreground_cwd": "/", "cwd": ""}, "/"),
        ("cwd", {"foreground_cwd": "", "cwd": ""}, "w2:p1"),
        ("title", {}, "Fix tests"),
        ("title", {"terminal_title": "", "terminal_title_stripped": ""}, "api"),
        ("name", {"name": "reviewer"}, "reviewer"),
        ("name", {}, "api"),
    ],
)
def test_label_styles(style: str, overrides: dict[str, object], expected: str) -> None:
    agent = Agent.from_api(raw_agent(**overrides))
    assert agent.label(style) == expected  # type: ignore[arg-type]
