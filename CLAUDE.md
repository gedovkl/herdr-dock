# herdr-dock

Shows herdr coding agents as live keys on a StreamDock M18, plus a home page of app, clock,
weather, pomodoro and timer keys. Read before changing anything: `README.md` (user guide, every
option), `DESIGN.md` (architecture, decisions, verified facts, milestones, open items),
`CHANGELOG.md` (everything built and learned; add to it when you finish something), and
`config.example.toml` (mirrors the author's real config).

## Current state

- **Linux: done and in daily use** (milestones 1–4 plus widgets, lock/sleep, three code reviews).
  Runs as a systemd user service on the author's machine.
- Verified on the real M18: home page, Herdr mode, agent switching + window raise, extra buttons,
  unplug/replug, lock blanking, clock/weather, pomodoro/timer.
- **Not verified on hardware yet:** dock off across a real suspend/resume (unit-tested).
- **macOS plugin (milestone 5): done and verified on the M18** (VSD Craft 3.10, macOS 26, herdr
  0.9.0, AeroSpace + WezTerm): agents draw, presses focus the agent, switch herdr's tab and raise the
  terminal. Not built: widgets on macOS (clock, weather, pomodoro, timer), an Exit status key
  (the app owns the folder back key), and a plugin-driven Herdr page (the app ignores
  `switchToProfile`).

## The author's machine

- Arch/Omarchy, Hyprland 0.56 (Lua config; `hyprctl dispatch 'hl.dsp.focus({ window = "address:…" })'`),
  uwsm, terminal foot. herdr 0.8.2 at `~/.config/herdr/herdr.sock`.
- SDK at `~/Projects/StreamDock-Device-SDK`. M18 `5548:1000`, udev rule
  `/etc/udev/rules.d/70-herdr-dock.rules`. Service `~/.config/systemd/user/herdr-dock.service`.
  Config `~/.config/herdr-dock/config.toml`.
- Home keys: 1 herdr · 2 Browser · 3 Merge · 4 Zed · 11 clock · 12 weather (Nashua NH, °C) ·
  13 pomodoro 25/5 · 14 timer.
- Git `origin` = github.com/gedovkl/herdr-dock (`master`); this repo's git email is the GitHub
  no-reply address (the private Gmail is blocked by GitHub).

## Working agreements

- Document everything in the repo; don't rely on source code or chat history.
- Keep `config.example.toml` identical to the author's config (test checks the key list).
- Settings go in the config, not in code. Commit and push each finished change.
- Verify device behaviour on the real M18 with the author, then confirm in
  `journalctl --user -u herdr-dock`.
- Review findings: re-check each against the code, fix only the real ones test-first, and reject
  unsafe suggestions with a reason.
- Never crash on missing hardware, tools or network: degrade, log once, recover.
- After daemon changes: `scripts/check.sh`, then `systemctl --user restart herdr-dock`.

## Rules (binding, from DESIGN.md "Engineering rules")

- SOLID: `herdr_core` depends only on the Protocols in `herdr_core/ports.py`, never on the
  StreamDock SDKs, sockets, `subprocess` or `time` directly. Concrete adapters are wired up
  only in a front end's composition root.
- Every behaviour change ships with tests. Bug fixes start with a failing test.
- Unit tests use the fakes in `tests/fakes/`, never real hardware, herdr, the StreamDock app or
  the window manager. Real-world tests are opt-in (`-m herdr_live`, `-m hardware`).
- `scripts/check.sh` must pass before committing: ruff, `mypy --strict` on `herdr_core`, `linux` and `macos`,
  unit tests with branch coverage ≥ 80 %.
- Python ≥ 3.11, frozen dataclasses for value objects, asyncio for I/O, `logging` instead of print
  (except CLI output).

## Commands

- `scripts/setup.sh`: create `.venv` and install the extras for this OS
- `scripts/check.sh`: everything required before committing
- `scripts/test.sh [-k name]`: unit tests + coverage
- `scripts/test-integration.sh herdr_live`: against a throwaway headless herdr session
- `scripts/test-integration.sh hardware`: against the M18 (stop the service first)
- `scripts/run-console.sh`: print live agent states (no device)
- `scripts/build-macos-plugin.sh`, `scripts/install-macos-plugin.sh`: build and install the macOS plugin
- `scripts/render-preview.sh`: all key faces → `build/preview/sheet.png` (look at it after rendering changes)
- `scripts/install-linux.sh [--udev|--uninstall]`, `journalctl --user -u herdr-dock -f`

## herdr protocol gotchas (verified on herdr 0.8.2; 0.9.0 notes at the end)

- One request per connection. The server closes the connection after replying.
- Event names are mixed: `pane.agent_status_changed` (dot), but `pane_created`,
  `pane_closed`, `pane_agent_detected`, `pane_focused`, `workspace_closed` (underscore).
- `pane.agent_status_changed` subscriptions need a `pane_id`. Resubscribe when the agent set changes.
- Closing a workspace emits only `workspace_closed` (no `pane_closed` for its panes).
- `pane_focused` events replay recent focus history to new subscribers. Read focus from
  `agent.list`, never from the events.
- Experiment in a throwaway session (`herdr --session <name> server`), never against the
  user's live session. `pane.report_agent` can drive agent states there.

- herdr 0.9.0: an attached UI ignores `agent.focus` and follows `tab.focus {"tab_id"}`, so a press
  sends both. An unseen finished agent is reported `idle`, not `done`, in a headless session.

## M18 gotchas (verified)

- USB `5548:1000` isn't in the SDK's product table; `linux.device_ids` lists the IDs to try.
- Without permissions the SDK's `open()`/`set_key_image()` still report success; check access.
- Images use `set_key_image(index + 1)`; presses must be decoded from raw packets
  (`data[9]` = index + 1), because the SDK's decoded key numbers are wrong on this unit.
- Writing to a removed device can kill the process natively: check the hidraw node before every
  write; close removed devices with `close(notify=False)`.
- The SDK writes temp JPEGs into the current directory, so the daemon `chdir`s. Keep every path
  absolute.
- Lock state: `hyprctl -j monitors` → `"LOCK"` in `solitaryBlockedBy` (Omarchy uses
  omarchy-shell, not hyprlock). Sleep: `PrepareForSleep` via `dbus-monitor` plus a
  `systemd-inhibit --mode=delay` lock.
- `ruff format` rewraps code: check that scripted edits actually applied before trusting tests.
- Only one process can drive the device: `systemctl --user stop herdr-dock` before
  `tools/probe_m18.py` or `scripts/test-integration.sh hardware`, and start it again after.

## The Mac

- macOS 26, Apple silicon, Python 3.14 (`scripts/setup.sh`; pip points at the Axon Nexus mirror:
  VPN on first). StreamDock app = VSD Craft 3.10 (`~/Library/Application Support/HotSpot/StreamDock`),
  herdr 0.9.0 at `~/.config/herdr/herdr.sock`, WezTerm, AeroSpace.
- Plugin loop: `scripts/check.sh`, `scripts/build-macos-plugin.sh`, `scripts/install-macos-plugin.sh`,
  then `pkill -f herdr-dock-plugin` (the app relaunches it); log `~/Library/Logs/herdr-dock/plugin.log`.
  Gate the build on `check.sh`'s exit code, not on `| tail`.
- The app numbers the M18's rows from the bottom (`row 2` is the top row). Agents fill keys from key 2.

## Platform split

Linux work happens on Linux (`linux/`). The macOS StreamDock app plugin (`macos/`, milestone 5)
is built and tested on a Mac. Its open items are listed in DESIGN.md.
