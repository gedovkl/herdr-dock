# herdr-dock

Shows herdr coding agents as live keys on a StreamDock M18. `DESIGN.md` is the source of truth
for architecture, milestones and open items. Read it before changing anything. `CHANGELOG.md`
records what was built and verified. Add to it when you finish something notable.

## Rules (binding, from DESIGN.md "Engineering rules")

- SOLID: `herdr_core` depends only on the Protocols in `herdr_core/ports.py`, never on the
  StreamDock SDKs, sockets, `subprocess` or `time` directly. Concrete adapters are wired up
  only in a front end's composition root.
- Every behaviour change ships with tests. Bug fixes start with a failing test.
- Unit tests use the fakes in `tests/fakes/`, never real hardware, herdr, the StreamDock app or
  the window manager. Real-world tests are opt-in (`-m herdr_live`, `-m hardware`).
- `scripts/check.sh` must pass before committing: ruff, `mypy --strict` on `herdr_core`,
  unit tests with branch coverage ≥ 80 %.
- Python ≥ 3.11, frozen dataclasses for value objects, asyncio for I/O, `logging` instead of print
  (except CLI output).

## Commands

- `scripts/setup.sh`: create `.venv` and install the extras for this OS
- `scripts/check.sh`: everything required before committing
- `scripts/test.sh [-k name]`: unit tests + coverage
- `scripts/test-integration.sh herdr_live`: against a throwaway headless herdr session
- `scripts/run-console.sh`: print live agent states (no device)

## herdr protocol gotchas (verified on herdr 0.8.2)

- One request per connection. The server closes the connection after replying.
- Event names are mixed: `pane.agent_status_changed` (dot), but `pane_created`,
  `pane_closed`, `pane_agent_detected`, `pane_focused`, `workspace_closed` (underscore).
- `pane.agent_status_changed` subscriptions need a `pane_id`. Resubscribe when the agent set changes.
- Closing a workspace emits only `workspace_closed` (no `pane_closed` for its panes).
- `pane_focused` events replay recent focus history to new subscribers. Read focus from
  `agent.list`, never from the events.
- Experiment in a throwaway session (`herdr --session <name> server`), never against the
  user's live session. `pane.report_agent` can drive agent states there.

## M18 gotchas (verified)

- USB `5548:1000` isn't in the SDK's product table; `linux.device_ids` lists the IDs to try.
- Without permissions the SDK's `open()`/`set_key_image()` still report success; check access.
- Images use `set_key_image(index + 1)`; presses must be decoded from raw packets
  (`data[9]` = index + 1), because the SDK's decoded key numbers are wrong on this unit.
- Only one process can drive the device: `systemctl --user stop herdr-dock` before
  `tools/probe_m18.py` or `scripts/test-integration.sh hardware`, and start it again after.

## Platform split

Linux work happens on Linux (`linux/`). The macOS StreamDock app plugin (`macos/`, milestone 5)
is built and tested on a Mac. Its open items are listed in DESIGN.md.
