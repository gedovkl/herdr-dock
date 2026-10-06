"""Status symbols shared by every renderer, matching herdr's `status_indicators = "symbols"`."""

from herdr_core.models import AgentStatus

STATUS_SYMBOL: dict[AgentStatus, str] = {
    AgentStatus.BLOCKED: "×",
    AgentStatus.WORKING: "◐",
    AgentStatus.DONE: "✓",
    AgentStatus.IDLE: "○",
    AgentStatus.UNKNOWN: "·",
}

# herdr's attention order (src/client/shell.rs status_priority): most urgent first.
STATUS_PRIORITY: tuple[AgentStatus, ...] = (
    AgentStatus.BLOCKED,
    AgentStatus.DONE,
    AgentStatus.WORKING,
    AgentStatus.IDLE,
    AgentStatus.UNKNOWN,
)
