# Changelog

What was built, in order, and what was learned along the way. Architecture and rationale live in
[DESIGN.md](DESIGN.md); setup is in [README.md](README.md).

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
