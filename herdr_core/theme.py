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

# Weather conditions → glyph (all present in the bundled DejaVu Sans).
WEATHER_SYMBOL: dict[str, str] = {
    "sun": "☀",
    "moon": "☾",
    "cloud": "☁",
    "fog": "≡",
    "drizzle": "☂",
    "rain": "☔",
    "snow": "❄",
    "thunder": "⚡",
    "unknown": "?",
}

# Catppuccin Mocha accents for the home-page widgets.
WEATHER_COLOR: dict[str, str] = {
    "sun": "#f9e2af",  # yellow
    "moon": "#b4befe",  # lavender
    "cloud": "#9399b2",  # overlay2
    "fog": "#7f849c",  # overlay1
    "drizzle": "#89dceb",  # sky
    "rain": "#89b4fa",  # blue
    "snow": "#f5f5f5",
    "thunder": "#fab387",  # peach
    "unknown": "#7f849c",
}

# Temperature (°C, upper bound) → colour, cold to hot.
TEMPERATURE_COLORS: tuple[tuple[float, str], ...] = (
    (-5, "#b4befe"),  # lavender: freezing
    (5, "#89dceb"),  # sky: cold
    (15, "#94e2d5"),  # teal: cool
    (22, "#a6e3a1"),  # green: mild
    (28, "#f9e2af"),  # yellow: warm
    (33, "#fab387"),  # peach: hot
    (float("inf"), "#f38ba8"),  # red: very hot
)

CLOCK_TIME_COLOR = "#b4befe"  # lavender
CLOCK_DAY_COLOR = "#fab387"  # peach
CLOCK_DATE_COLOR = "#a6adc8"  # subtext0


def temperature_color(celsius: float) -> str:
    return next(color for limit, color in TEMPERATURE_COLORS if celsius < limit)


POMODORO_WORK_COLOR = "#f38ba8"  # red
POMODORO_REST_COLOR = "#a6e3a1"  # green
TOMATO_COLOR = "#e64553"
TOMATO_HIGHLIGHT = "#f5a3b5"
TOMATO_LEAF_COLOR = "#40a02b"
STOPWATCH_RING = ("#89b4fa", "#cba6f7", "#f5c2e7", "#fab387")  # blue → mauve → pink → peach
STOPWATCH_FACE = "#eff1f5"
STOPWATCH_HAND = "#1e1e2e"
TIMER_RUNNING_COLOR = "#89dceb"  # sky
