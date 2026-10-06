# Changelog

What was built, in order, and what was learned along the way. Architecture and rationale live in
[DESIGN.md](DESIGN.md); setup is in [README.md](README.md).

## Linux check after the macOS work

Re-checked Linux after the macOS plugin landed. `scripts/check.sh` had stopped passing on Linux:

- `mypy` now checks `macos/`, and two macOS test modules import `websocket`, but
  `websocket-client` was only in the `macos` extra. It is in `dev` now, so every OS type-checks and
  unit-tests the plugin (with fakes; nothing connects).
- Six `test_herdr_path.py` tests used the real `/usr/bin` as the "herdr-free" PATH and searched
  the real `/opt/homebrew/bin` and `/usr/local/bin`, so they failed on any machine with herdr
  installed there (this one has `/usr/bin/herdr`). The fixed directories are now
  `herdr_path.SYSTEM_DIRS`, emptied by a fixture, and the tests use a PATH under `tmp_path`.
- Verified on Linux: `check.sh` (476 tests), `test-integration.sh herdr_live` against herdr 0.8.2
  (0.8.2 accepts `tab.focus`, and a press still keeps the chosen pane when a tab has two agents),
  and the service restarted on the new code (socket found, M18 connected).
- Verified on the M18 with the author: agent presses still switch herdr and raise foot with
  `tab.focus` now sent too; the journal shows no tab-focus warning.

## macOS plugin core (milestone 5, step 1)

- `macos/`: protocol parsing, WebSocket transport, `StreamDockSurface`, visibility lifecycle with a
  0.3 s grace delay, `HerdrPlugin`, `herdr` lookup and the entry point. One action
  (`com.herdr.dock.agent`) instead of separate slot and pager actions, because the core already
  decides what each key shows. Not yet: manifest, PyInstaller spec, install, hardware test.
- **Shared with Linux, not copied:** `herdr_core/wiring.py` now holds the renderer/presenter/session
  wiring, the start/stop order and the logging setup. `linux/daemon.py` and `linux/controller.py`
  use it, with no behaviour change (all Linux tests unchanged and passing).
- `read_herdr_status(herdr=...)` takes the binary to run, so a front end with a minimal `PATH`
  can pass an absolute path.

## Code review fixes (macOS plugin and shared code)

A review of the four macOS commits found 10 issues. 6 were real and got a failing test first, 1 was
checked and found harmless, 3 were rejected or documented:

1. **Real, Linux regression of my refactor:** moving the ancestry walk into
   `herdr_core.processes.ancestors` dropped matches for a window owned by a parent process missing from
   the `/proc` table (the old loop checked the window before the lookup). Added `ancestor_pids`, used by
   `window_for`, and a Linux test.
2. **Real:** the plugin latched the dock on a rejected first event (the back key position, off the
   grid), then refused the real dock. It latches only on a key it draws on.
3. **Real:** a context moved onto a key we don't use stayed attached to its old key and kept herdr
   running. It is detached now.
4. **Real:** a late `willAppear` after `close()` started a new worker nobody awaited. `close()` is final.
5. **Real:** the socket thread raised `RuntimeError: Event loop is closed` when reporting a close
   after shutdown. Callbacks tolerate a closed loop.
6. **Real:** the plugin log file grew without bound. It rotates (1 MB x 3).
7. **Checked, harmless:** `tab.focus` after `agent.focus` could have undone the pane choice in a
   tab with two agents. A live test in a throwaway herdr 0.9.0 session shows it keeps the pressed pane,
   both ways (kept as a regression guard).
8. **Rejected:** a slow `herdr status server` delaying the plugin's start (the SDK's own sample waits
   1 s; the call has a 3 s timeout; a different socket is covered by `herdr_socket`).
9. **Documented limits:** several terminals with herdr clients (the lowest pid wins) and a herdr binary
   under a path with spaces (`ps` can't separate the words).

## macOS plugin: manifest, build, install (milestone 5, step 2)

- **herdr 0.9.0: pressing an agent didn't switch the herdr UI.** `agent.focus` completes `ok` and
  moves the server's focus, but an attached UI ignores it. `tab.focus` makes the UI follow, so
  `HerdrSession.press` now sends both (`HerdrApi.focus_tab`, shared with Linux; a failure is
  logged once and never blocks the raise). Verified by hand on the live session and by a live
  test in a throwaway one. The live tests also now accept 0.9's `idle` (0.8: `done`) and the
  macOS `/private/tmp` path.
- **Pressing an agent now raises its terminal** (macOS default `[raise] macos = "herdr-window"`):
  `macos/raiser.py` finds the terminal app above the attached herdr client and `open`s it. Verified
  on this Mac's process table: WezTerm. The process helpers (`Process`, `herdr_clients`,
  `ancestors`, `run_exec`) moved from `linux/hyprland.py` into `herdr_core/processes.py` and the
  Linux raiser uses them, with no behaviour change (all Linux tests unchanged).
- Presses were already reaching herdr (`agent.focus` completed `ok` in herdr's own log); only the
  window raise was missing, which is why the keys seemed to do nothing.
- **Bug found on the dock:** the app numbers the M18's rows from the bottom (the folder back key,
  top-left, is stored at `0,2`), but the plugin treated row 0 as the top. Agents placed on keys
  2-5 were read as keys 12-15, empty slots, so they stayed black. Fixed test-first:
  key index = `(2 - row) * 5 + column`. The first spike's "top-left origin" note was never checked
  against the physical dock.

- `macos/com.herdr.dock.sdPlugin/manifest.json` (one action, `com.herdr.dock.agent`), the icon
  (`tools/make_plugin_icons.py`, drawn by the same `KeyRenderer` as the keys) and
  `macos/plugin.spec`. `scripts/build-macos-plugin.sh` builds a 15 MB self-contained binary (the
  script now creates `dist/`); `scripts/install-macos-plugin.sh` installs it.
- Smoke-tested the frozen binary against a fake StreamDock app: it registers, draws a key
  (fonts bundled) and exits when the app hangs up.
- **Found by that test:** herdr reports a temp-dir socket when `$HOME` is missing, so the plugin
  sets `HOME` itself.
- New shared setting `herdr_bin` (path to the herdr binary, empty = search), used by Linux, macOS
  and the console tool through `status_reader()`.
- INFO logging of key appear/disappear/press and herdr start/stop in
  `~/Library/Logs/herdr-dock/plugin.log`, which also appears in the app's own log.
- Reloading: `pkill -f herdr-dock-plugin` makes the app relaunch the plugin with the new binary.
  New plugins and manifest changes still need an app restart.
- Page switching from a plugin doesn't work (two spikes, see DESIGN.md "Open items"), so Herdr
  mode on macOS can't be a plugin-driven page yet.

## macOS spike (VSD Craft 3.10.205)

A throwaway plugin on the real M18 settled the macOS open items (details in DESIGN.md "Open items"):

- `CodePathMac` launches a script or executable with `-port -pluginUUID -registerEvent -info`.
  Plugins get a minimal `PATH`, so the plugin must find `herdr` itself.
- Key events carry `coordinates {column, row}`; rows count from the bottom (found later, see below).
- Folders get a fixed back key on key 1: no Exit action. Folder enter/leave arrives as bursts of
  `willDisappear` then `willAppear`, so the session stop needs a short grace delay.
- 64 × 64 PNG `setImage` displays sharp.
- `tests/unit/linux/test_hyprland.py`: the real-`/proc` test is skipped where there is no `/proc`
  (macOS), so `scripts/check.sh` passes on the Mac.
- On this Mac pip points at the Axon Nexus mirror: connect to the VPN before `scripts/setup.sh`.

## Pomodoro and timer keys

- `widget = "pomodoro"`: `work_minutes` / `rest_minutes` (25/5) and `notify` in the config.
  - Press to start, press again to stop.
  - Running: `WORK` (red) or `REST` (green), time left, a progress bar, and automatic cycling.
  - Phase changes send a `notify-send` notification, also while in Herdr mode.
  - Stopped: a drawn tomato.
- `widget = "timer"`: a stopwatch. Press to start, press again to stop and reset.
  - Running: `m:ss` / `h:mm:ss` with a blinking dot.
  - Stopped: a drawn stopwatch with a four-colour ring.
- All widgets share one interface (`face`, `press`, `advance`). Clock and weather pass presses
  through to `run`/`app`/`focus`.
- The author's config, mirrored in `config.example.toml`: pomodoro on key 13, timer on key 14.
- Verified on the M18: both keys toggle, count and redraw as described.

## Third code review fixes

All three findings were real. Each fix has a test that failed first:

1. **Lock monitor gave up after 3 `hyprctl` failures.** Locked at that moment, the dock stayed
   dark until a restart; starting before Hyprland was reachable, lock blanking stayed off for
   the session. It now retries forever with backoff (up to 30 s) and **keeps the last known
   state**. The suggested "report unlocked before giving up" would have lit the dock and
   re-enabled presses on a locked machine. One log line when failing, one when it recovers.
2. **No logind delay lock for sleep.** logind could suspend before the dock went dark. The sleep
   monitor now holds `systemd-inhibit --what=sleep --mode=delay` while awake (Omarchy does the
   same for its lock). On `PrepareForSleep(true)` it waits for the blank to be *applied* (at
   most 3 s, under logind's 5 s default) and only then releases the lock. It takes the lock
   again on resume. Without `systemd-inhibit` it still blanks, and logs a warning once.
3. **Weather code 1 ("mainly clear") at night showed a cloud.** It now shows the moon, like
   the sun by day.

## Dock off on lock and sleep

- `[linux] blank_when_locked` / `blank_on_sleep` (both default `true`): brightness 0 plus cleared
  keys while the session is locked or the machine sleeps, then a full redraw on return.
- **Lock detection**: Omarchy locks with omarchy-shell's ext-session-lock, not hyprlock, so
  watching a locker process doesn't work. Hyprland lists `LOCK` in each monitor's
  `solitaryBlockedBy` while any session lock is active, so that's polled every
  `lock_poll_seconds`.
- **Sleep detection**: logind `PrepareForSleep` via `dbus-monitor --system`, which is already
  installed and is what Omarchy's own sleep monitor uses. No new Python dependency.
- While off, presses are ignored (a stray press while locked can't launch apps), the clock stops
  ticking, and Herdr-mode animation pauses. The off state survives a USB re-enumeration on
  resume.
- Without `hyprctl` or `dbus-monitor`, that feature switches itself off with one log line.
- Verified on the M18 with `omarchy-system-lock`: dark within a second of locking, restored on
  unlock, same process, no restart. Suspend/resume has unit tests but hasn't been tried on hardware yet.

## Clock and weather keys

- `widget = "clock"`: time and date with configurable `time_format`/`date_format` (strftime,
  default `%a\n%-d %b`: the day and the date on separate rows, so both are bigger, with no
  zero-padded day).
  The text shrinks to fit 64 px keys instead of being cut off.
- `widget = "weather"`: current conditions from Open-Meteo (no API key). `latitude`,
  `longitude`, `place`, `units` (celsius/fahrenheit) and `refresh_minutes` are set in the config.
  WMO codes map to glyphs the bundled font has (☀ ☾ ☁ ≡ ☂ ☔ ❄ ⚡; ⛅ and 🌫 are missing). Failures
  keep the last reading, log once, and retry after 60 s.
- Colours (Catppuccin, in `herdr_core/theme.py`): clock time lavender, weekday peach, date soft
  grey; weather glyph by condition (yellow sun, lavender moon, blue rain, white snow, peach
  thunder); temperature from lavender (freezing) through teal and green to red (very hot). The weather
  face carries the condition and °C, and the renderer picks the glyph and colours.
- A one-second tick, through the input queue, redraws only home keys whose text changed. It
  costs about 0.1 % of one core.
- The author's config, mirrored in `config.example.toml`, gained a clock and Nashua, NH weather (°C) on
  the first two keys of the bottom row (keys 11 and 12).
- Second code review: one finding, fixed. With a relative `--config` path, relative icon paths
  stayed relative and broke after the SDK's `chdir`. They are now always absolute.

## Code review fixes

A review of `herdr_core/`, `linux/` and `scripts/` found 7 issues. All were confirmed, and each fix
comes with a test that failed before it:

1. **Presenter retry**: after a failed key write, the presenter asked for another tick only if
   something it had already checked was animating. A failed write on a static page wasn't
   retried, and later blinking keys stopped. Now any failure schedules a retry tick, and
   animation is evaluated across all keys.
2. **Half-opened device leak**: if `open()`/`init()` failed while connecting, the SDK device was
   never closed. Each 2 s retry leaked a handle and threads. It's now closed with `notify=False`.
3. **Missing `hyprctl`**: `create_subprocess_exec` raised `FileNotFoundError`, so a home key with
   `focus` never launched its app on non-Hyprland desktops. `run_exec` now returns 127, and any
   focus failure falls through to launching.
4. **Single-process terminals** (foot --server, Ghostty, kitty --single-instance): the raiser took
   the first window listed for the PID. It now takes the most recently focused one. Hyprland can't
   tell which of them holds the herdr TTY, so this remains a documented limitation.
5. **Process-wide `chdir`** (needed by the SDK): relative icon paths now resolve against the
   config file's folder, `run` commands start in `$HOME`, and the herdr socket path is made
   absolute before connecting.
6. **Replug redraw race**: the watcher redrew the home page concurrently with key handling.
   Redraws now go through the same queue as presses.
7. **Service unit quoting**: `ExecStart` is now quoted and `%` escaped by `linux/service.py`
   (replacing `sed`), so paths with spaces, `&`, `|` or `%` work. Verified with
   `systemd-analyze verify`.

`config.example.toml` now uses the four home keys from the author's own setup (herdr, Browser,
Merge, Zed).

## Linux hardening and home keys

- **Unplug-safe device handling.** The vendor SDK can kill the process natively when it writes to
  a removed device (its own `close()` comment says so). The daemon now:
  - checks that the hidraw node exists before **every** write and every 0.25 s while connected;
  - closes a removed device with `close(notify=False)`, which skips the disconnect write;
  - drops key updates while the dock is absent and redraws everything on replug;
  - logs "waiting for the M18 to be plugged in" once per absence, never floods;
  - starts normally with no dock plugged in.

  Verified on the M18 by unplugging mid-animation: same PID, no restart, clean log.
- **Presenter**: draw failures are logged once per failure streak and retried on the next push,
  instead of logging a traceback for every key on every tick.
- **`focus = "<window class regex>"` on home keys**: focus the most recently used matching
  Hyprland window, and launch `app`/`run` only if there is none. Used for the Browser, Merge
  and Zed keys.
- **`[linux] focus_herdr_on_enter`** (default `true`): the Herdr button also brings the herdr window
  to the front.
- `app = "<id>.desktop"` works for apps whose binary isn't on `PATH` (`uwsm-app` resolves desktop IDs).

## Milestone 4: systemd user service

- `linux/herdr-dock.service` is bound to `graphical-session.target` (uwsm provides it together with
  `HYPRLAND_INSTANCE_SIGNATURE` and `WAYLAND_DISPLAY`) and restarts on failure.
- `scripts/install-linux.sh` installs and starts it, `--uninstall` removes it, and `--udev`
  installs the device rule. It refuses to run while a hand-started daemon holds the dock.

## Milestone 3: Linux daemon on the M18

- **Hardware probe** (`tools/probe_m18.py`) on the actual unit:
  - USB `5548:1000` "HOTSPOTEKUSB HID DEMO", firmware `V3.VSDM18_HBOE.02.017`. It is a
    VSDinside-branded M18 and **missing from the SDK's product table**, so the daemon enumerates
    configured IDs itself.
  - Key images: `set_key_image(n)`, with n = 1 top-left, row by row. Presses: raw code n for
    the same key. The SDK's *decoded* press numbers are wrong (raw 1 → "KEY_11"), so presses are
    decoded from raw packets.
  - Three buttons under the screen send `0x25`, `0x30`, `0x31`.
  - 15 keys plus refresh take about 10–13 ms, so animation is cheap.
  - **Without permissions the SDK reports success anyway** (`open()` returns `True`, image writes
    return 0). The daemon checks `os.access()` itself.
- **udev rule** `linux/70-herdr-dock.rules`: `uaccess` for the M18 IDs only, so the logged-in user
  gets access. The SDK's own rule makes every StreamDock world-writable (`0666`).
- **Daemon**: home page from `[[home]]` (herdr / app / run keys), Herdr mode with Exit on key 1,
  agent keys 2–15, pager on overflow, extra buttons, and replug handling.
- **Raise the herdr window** (`HerdrWindowRaiser`): walks `/proc` from the attached herdr client up
  to the process that owns a Hyprland window, then focuses it by address. This works for any
  terminal. Hyprland 0.56 needs the Lua dispatcher (`hl.dsp.focus({ window = "address:…" })`),
  with the old `focuswindow` syntax as a fallback.
- **herdr quirk found**: `pane_focused` events replay recent focus history to every new subscriber
  (about 10/s, across tabs) while `agent.list` stays steady. This made the focus border flicker
  when entering Herdr mode. The session now treats focus events as a hint and re-reads focus from
  `agent.list`, throttled to every 0.5 s.
- `config.example.toml` documents every setting and is checked by a test.

## Milestone 2: key rendering

- `faces.py` (what each key shows) → `animation.py` (blink/spin/pulse as a pure function of
  time, so blinks stay in phase) → `render.py` (Pillow, cached PNGs) → `presenter.py` (sends only
  changed keys; ticks only while something animates).
- Symbols and colour roles taken from herdr's source (`status_icon` and `status_color` in
  `src/client/shell.rs`): `×` blocked/red, `◐` working/yellow, `✓` done/teal, `○` idle/green,
  `·` unknown. Idle and unknown keys are dark with a coloured symbol, so full colour means activity.
- Bundled DejaVu Sans and DejaVu Sans Condensed Bold (with licence), so keys look the same on every machine.
- `scripts/render-preview.sh` writes every face and frame plus a contact sheet.

## Milestone 1: herdr core

- **herdr socket API** (protocol 20, herdr 0.8.2), verified against a throwaway
  `herdr --session <name> server`:
  - NDJSON over a Unix socket. One request per connection, except `events.subscribe`.
  - Request `id` must be a **string**.
  - Event names mix `pane.agent_status_changed` (dot) with `pane_created` (underscore).
  - Status subscriptions need a `pane_id`, so the session resubscribes when the agent set changes.
  - Closing a workspace emits only `workspace_closed` (no `pane_closed`), so any topology event
    triggers a full resync.
  - `agent.focus` marks `done` as seen (→ `idle`). blocked → idle while unseen becomes `done`.
- `HerdrSession`: list → subscribe → list again (closes the gap) → follow events. Also periodic
  resync, reconnect with backoff, stable key slots, and paging.
- `scripts/run-console.sh` shows live agent states without a device.

## Project setup

- Design document with Mermaid diagrams, binding engineering rules (SOLID, ≥ 80 % branch coverage,
  fakes only in unit tests, opt-in `herdr_live`/`hardware` tests), `CLAUDE.md` for future sessions.
- `scripts/` for setup, check, test, lint, format, run, install and build (bash 3.2 compatible
  for macOS).
- Researched the StreamDock app plugin SDK for macOS. A plugin can only draw on keys holding its
  actions and can't switch pages (SDK issue #33), so on macOS Herdr mode will be a folder in the
  StreamDock app (milestone 5).
