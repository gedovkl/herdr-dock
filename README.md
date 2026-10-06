# herdr-dock

Shows [herdr](https://herdr.dev) coding agents as live keys on a StreamDock M18 and lets you press a key to
jump to that agent.

- **Linux:** standalone daemon on the StreamDock Device SDK
- **macOS:** plugin for the official StreamDock app

Both use the same `herdr_core` package. See [DESIGN.md](DESIGN.md) for the architecture,
engineering rules (SOLID, ≥ 80 % test coverage) and milestones.

Status: project skeleton and tooling; feature code starts with milestone 1.

## Scripts

Run from anywhere; they resolve the repo root themselves. Works with macOS's bash 3.2.

| Script | What it does |
|--------|--------------|
| `scripts/setup.sh [--recreate]` | Create `.venv`, install dev tools + this OS's extras, link the StreamDock Device SDK on Linux (`STREAMDOCK_SDK` overrides the path) |
| `scripts/check.sh` | Everything required before pushing: lint + types + unit tests with the 80 % coverage gate |
| `scripts/test.sh [pytest args]` | Unit tests with the coverage gate |
| `scripts/test-integration.sh [herdr_live\|hardware\|all]` | Opt-in tests against a live herdr and/or the plugged-in M18 |
| `scripts/lint.sh` | `ruff check`, `ruff format --check`, `mypy --strict` |
| `scripts/format.sh` | Apply ruff fixes and formatting |
| `scripts/run-console.sh` | Print live herdr agent states in the terminal (no device) |
| `scripts/render-preview.sh [dir]` | Render all key states/frames to PNGs for review |
| `scripts/run-linux.sh [args]` | Run the Linux daemon in the foreground |
| `scripts/install-linux.sh [--udev]` | Install the systemd `--user` service, optionally the udev rule (sudo) |
| `scripts/build-macos-plugin.sh` | Build `dist/com.herdr.dock.sdPlugin` with PyInstaller (macOS) |
| `scripts/install-macos-plugin.sh` | Copy the plugin into the StreamDock app (`STREAMDOCK_PLUGINS_DIR` overrides the path) |

Scripts whose code isn't written yet stop with the DESIGN.md milestone that adds it.
