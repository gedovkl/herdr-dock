# herdr-dock

Shows [herdr](https://herdr.dev) coding agents as live keys on a StreamDock M18. Each key shows
an agent's status with herdr's own symbols (`×` blocked, `◐` working, `✓` done, `○` idle). Blocked
agents blink. Press a key to switch herdr to that agent and bring its terminal window to the front.

- **Linux:** a standalone daemon that drives the M18 directly through the StreamDock Device SDK
- **macOS:** a plugin for the official StreamDock app (VSD Craft)

Both use the same `herdr_core` package. See [DESIGN.md](DESIGN.md) for the architecture,
engineering rules (SOLID, ≥ 80 % test coverage) and milestones, and [CHANGELOG.md](CHANGELOG.md)
for what was built and what was learned about herdr and the M18 along the way.

**Status:** both platforms work on the M18. Linux: the daemon runs as a systemd user service
(milestones 1-4). macOS: the plugin for the StreamDock app is verified on the dock (milestone 5).

## How it works on the dock

- **Home page:** keys you define in the config, such as launching an app, running a command, or
  `◐ herdr` (key 1 by default), which enters Herdr mode.
- **Herdr mode:** key 1 is `◀ herdr` (Exit, back to the home page). Keys 2–15 are your agents. With
  more than 14 agents, key 15 becomes the pager (`▶ 1/2`).
- **Buttons under the screen:** left enters or leaves Herdr mode, right shows the next page of
  agents, and middle does nothing. All three are configurable.
- herdr is only contacted while Herdr mode is on. Entering Herdr mode also brings the herdr
  window to the front (`focus_herdr_on_enter`).
- **Lock and sleep:** the dock turns off (brightness 0, keys cleared) while the session is
  locked or the machine is asleep, and comes back as it was. Presses are ignored while it's
  off, so nothing launches by accident. Configured with `blank_when_locked` and `blank_on_sleep`.
- The dock can be unplugged and replugged at any time. The daemon keeps running, logs
  "waiting for the M18", and redraws when the dock comes back. It also starts fine with no
  dock plugged in.

## Setup on Linux

**Short version**, once the prerequisites are in place:

```bash
git clone https://github.com/gedovkl/herdr-dock.git ~/Projects/herdr-dock
git clone https://github.com/MiraboxSpace/StreamDock-Device-SDK.git ~/Projects/StreamDock-Device-SDK
cd ~/Projects/herdr-dock
scripts/setup.sh                 # Python venv + dependencies + SDK link
scripts/install-linux.sh --udev  # device access for your user (sudo), then replug the M18
scripts/install-linux.sh         # install + start the systemd user service
```

The steps below explain each part.

Tested on Arch (Omarchy) with Hyprland 0.56, herdr 0.8.2 and a VSDinside StreamDock M18
(USB `5548:1000`).

### 1. Prerequisites

- **herdr** installed and running (`herdr status server` should say `running`)
- **Python ≥ 3.11** (with `venv`) and **git**
- **libudev** (part of systemd; already installed on practically every desktop distro)
- **Hyprland**, only needed for the default "raise the herdr window" behaviour. On other
  desktops, set your own raise command or turn raising off (see step 6).

No system hidapi package is needed: the SDK's native library has it built in.

### 2. Get the code

Clone this repo and the StreamDock Device SDK **next to each other**:

```bash
mkdir -p ~/Projects && cd ~/Projects
git clone https://github.com/gedovkl/herdr-dock.git
git clone https://github.com/MiraboxSpace/StreamDock-Device-SDK.git
```

If you keep the SDK somewhere else, export `STREAMDOCK_SDK=/path/to/StreamDock-Device-SDK/Python-SDK/src`
before running step 3.

### 3. Create the Python environment

```bash
cd ~/Projects/herdr-dock
scripts/setup.sh
```

This creates `.venv`, installs herdr-dock with its dependencies (Pillow, pyudev, and the test
tools), and links the StreamDock SDK into the environment. It should finish with
`linked StreamDock Device SDK: …`.

### 4. Give your user access to the M18

Plug in the M18, then:

```bash
scripts/install-linux.sh --udev
```

This needs sudo. It installs `linux/70-herdr-dock.rules` into `/etc/udev/rules.d/` and reloads
udev. The rule gives the **logged-in desktop user** access to the M18 (through logind's
`uaccess`). It does not open the device to all users.

To check, `getfacl /dev/hidraw*` should list `user:<you>:rw-` for the M18's hidraw node. If it
doesn't, unplug and replug the M18.

> Why this matters: without access, the vendor SDK *pretends* to work (opening and drawing
> report success, but nothing happens). The daemon checks access itself and logs
> `no read/write access to /dev/hidrawN; install the udev rule` instead.

### 5. Try it

```bash
scripts/run-console.sh --once   # optional: lists your herdr agents in the terminal, no device needed
scripts/run-linux.sh            # runs the daemon in the foreground; Ctrl+C to stop
```

The M18 shows the home page with `◐ herdr` on the top-left key. Press it to see your agents,
press an agent to jump to it, and press `◀ herdr` to go back. Add `-v` to `run-linux.sh` for debug
logging.

### 6. Configure (optional)

```bash
mkdir -p ~/.config/herdr-dock
cp config.example.toml ~/.config/herdr-dock/config.toml
```

Every setting is documented in [`config.example.toml`](config.example.toml). The ones you're most likely to change:

| Setting | What it does |
|---------|--------------|
| `[[home]]` | Home-page keys: `key = 1..15` plus one of `herdr = true`, `app = "<desktop id>"`, `run = "<shell command>"` or `widget = "clock" \| "weather" \| "pomodoro" \| "timer"`. Optional `label`, `symbol`, `icon = "<path>"`, and `focus = "<window class regex>"` to focus an already-running window instead of starting another one |
| `[linux.buttons]` | `left`/`middle`/`right` → `"herdr"`, `"page"` or `"none"` |
| `[linux] focus_herdr_on_enter` | `true` (default): entering Herdr mode also brings the herdr window to the front (Hyprland) |
| `[linux] blank_when_locked`, `blank_on_sleep` | `true` (default): turn the dock off while the session is locked / the machine sleeps. `lock_poll_seconds` (1) sets how quickly a lock is noticed |
| `[raise] linux` | `"herdr-window"` (default): focus the window the herdr client runs in, via Hyprland. Any other value is a shell command (`{pane_id}`, `{cwd}`, … are filled in; write literal braces as `{{ }}`). Set `enabled = false` to never raise |
| `label` | Text under the symbol: `"cwd"` (folder), `"title"` or `"name"` |
| `attention` | Statuses that blink or pulse: `["blocked"]` by default; add `"done"` to make finished work pulse until you look at it |
| `[colors]` | Per-status colours (`blocked = "#ff0000"`) |
| `[linux] brightness`, `device_ids`, `app_launcher` | Screen brightness 0–100, USB IDs to look for, the command `app = …` keys use (`uwsm-app -- {app}`) |

Restart the daemon after changing the config (`systemctl --user restart herdr-dock` once it runs as a service).

#### Clock and weather keys

```toml
[[home]]
key = 11
widget = "clock"
time_format = "%H:%M"      # strftime format; "%I:%M %p" for 12-hour, "%H:%M:%S" with seconds
date_format = "%a\n%-d %b"  # \n starts a new row (max 2): day, then date; "" hides it

[[home]]
key = 12
widget = "weather"         # current conditions from Open-Meteo (free, no API key)
place = "Nashua"           # label under the temperature
latitude = 42.7654         # your location (find it at https://open-meteo.com or any map)
longitude = -71.4676
units = "celsius"          # or "fahrenheit"
refresh_minutes = 15       # how often to fetch (≥ 1)
```

- The clock updates live while the home page shows. Only changed keys are sent, so a
  minute-precision clock writes to the dock once a minute.
- Weather shows a symbol (☀ ☾ ☁ ≡ ☂ ☔ ❄ ⚡), the rounded temperature and the place. With no network
  it keeps the last reading, or shows `--` before the first one, and retries every minute. One
  warning is logged per outage.
#### Pomodoro and timer keys

```toml
[[home]]
key = 13
widget = "pomodoro"   # press: start, press again: stop
work_minutes = 25
rest_minutes = 5
notify = true         # desktop notification (notify-send) when work/rest switches

[[home]]
key = 14
widget = "timer"      # stopwatch: press to start, press again to stop
```

- **Pomodoro:** stopped, it shows a tomato. Running, it shows `WORK` (red) or `REST`
  (green), the time left and a progress bar, and it alternates work and rest until you press it
  again. Notifications keep coming while you're in Herdr mode.
- **Timer:** stopped, it shows a colourful stopwatch. Running, it counts `m:ss` (`h:mm:ss`
  from one hour) with a blinking dot. Pressing it again stops and resets it.
- Both keep running in the background while you're in Herdr mode, and use the monotonic clock,
  so they aren't thrown off by clock changes.

- Clock and weather keys can also act when pressed: add `run`, `app` or `focus` (for example
  `run = "xdg-open https://weather.gov"`).

#### Home keys for apps: focus if running, otherwise launch

```toml
[[home]]
key = 2
label = "Browser"
icon = "/usr/share/icons/hicolor/128x128/apps/chromium.png"
app = "chromium"
focus = "^chromium$"

[[home]]
key = 3
label = "Merge"
icon = "/usr/share/icons/hicolor/128x128/apps/sublime-merge.png"
app = "sublime_merge.desktop"
focus = "^sublime_merge$"

[[home]]
key = 4
label = "Zed"
icon = "/usr/share/icons/hicolor/512x512/apps/zed.png"
app = "dev.zed.Zed.desktop"
focus = "^dev\\.zed\\.Zed$"
```

Where the values come from:

- **`app`** is passed to `uwsm-app --`. It's either a command on your `PATH` (`chromium`) or a
  desktop entry ID **including `.desktop`** (`sublime_merge.desktop`). Use the desktop ID when the
  binary isn't on `PATH`. List the IDs with `ls /usr/share/applications ~/.local/share/applications`.
- **`focus`** is a regex matched against Hyprland window **classes**. With the app open, run
  `hyprctl clients -j | jq -r '.[].class'`. Anchor it with `^…$`, so `^chromium$` doesn't also
  match Chromium web apps (`chrome-…`). In TOML strings, write a regex `\.` as `\\.`.
- **`icon`** is any image file. App icons usually live in `/usr/share/icons/hicolor/<size>/apps/`.
  Without an icon, use `symbol = "<glyph>"`.

### 7. Start automatically

```bash
scripts/install-linux.sh
```

This installs and starts a systemd **user** service (`~/.config/systemd/user/herdr-dock.service`).
It runs inside your graphical session, starts with it, stops with it, and restarts after a crash.
Stop any `scripts/run-linux.sh` you started by hand first, because only one process can drive the M18.

```bash
systemctl --user status herdr-dock      # is it running?
journalctl --user -u herdr-dock -f      # logs
systemctl --user restart herdr-dock     # after changing the config
scripts/install-linux.sh --uninstall    # remove the service
```

Re-run `scripts/install-linux.sh` if you move the repo or recreate `.venv`.

### Updating

```bash
cd ~/Projects/herdr-dock
git pull
scripts/setup.sh                       # picks up new dependencies
systemctl --user restart herdr-dock
```

### Troubleshooting

| Symptom | Fix |
|---------|-----|
| Log says `no read/write access to /dev/hidrawN` | Run step 4, then replug the M18 |
| Keys stay blank, nothing in the log about the M18 | Your unit has different USB IDs. Run `.venv/bin/python tools/probe_m18.py --vid 0x… --pid 0x…` with the IDs from `lsusb`/`/sys/bus/usb/devices/*/id*`, then add them to `[linux] device_ids` |
| Agent keys say `herdr offline` | herdr isn't running, or it uses a different socket. Check `herdr status server`, and set `herdr_socket` in the config if needed |
| Pressing an agent switches herdr but doesn't raise the window | You're not on Hyprland, or the herdr client isn't in a Hyprland window. Set `[raise] linux` to your own command |
| `tools/probe_m18.py` or the hardware tests can't open the device | Only one process can drive the M18. Stop the daemon first: `systemctl --user stop herdr-dock` |
| An `app = …` home key does nothing | `uwsm-app` couldn't resolve the name. Use the desktop ID with `.desktop` (see step 6), and check `journalctl --user -u herdr-dock` |
| Dock was unplugged | Nothing to do: plug it back in and it redraws within about 2 s |
| Dock doesn't turn off when locked | Lock detection uses Hyprland's session-lock state (`hyprctl -j monitors` → `solitaryBlockedBy` contains `LOCK`). It works with omarchy-shell, hyprlock and other ext-session-lock lockers. Without Hyprland it switches itself off, logging `lock blanking is off`. Sleep detection needs `dbus-monitor`, and `systemd-inhibit` to delay the suspend until the dock is dark (`systemd-inhibit --list` shows `herdr-dock`) |
| Weather key shows `--` | No network, or the coordinates are wrong. The log says `weather update failed …` once. It retries every minute |
| Service doesn't start at login | `systemctl --user status herdr-dock`. It needs `graphical-session.target`, which uwsm and most Wayland session managers provide |

## Setup on macOS

A plugin for the official StreamDock app (VSD Craft 3.10 was used). The app owns the home page and
folders, so the plugin only draws the agent keys: you create one folder and put the **Herdr Agent**
action on its keys. Tested on macOS 26 (Apple silicon), herdr 0.9.0 and a VSDinside M18.

```bash
git clone https://github.com/gedovkl/herdr-dock.git ~/Projects/herdr-dock
cd ~/Projects/herdr-dock
scripts/setup.sh                    # Python venv, dependencies, PyInstaller
scripts/build-macos-plugin.sh       # builds dist/com.herdr.dock.sdPlugin (about 15 MB, self-contained)
scripts/install-macos-plugin.sh     # copies it into the app's plugin folder
```

Then **quit VSD Craft completely (Cmd+Q) and reopen it** (new plugins are only found at startup).

### Put the keys on the dock

1. On the home page, add the app's own **folder** action to a key. Pressing it opens the folder, and
   the app puts its fixed back key on key 1 (top-left).
2. Inside the folder, drag **Herdr Agent** (category **herdr**) onto keys 2-15. Keys 2-5 are the
   top row, columns 2-5.
3. Open the folder. Each key shows one agent, in the same order and with the same symbols and colours
   as on Linux. Keys without an agent stay blank. With more than 14 agents key 15 becomes the pager.

Pressing a key focuses that agent in herdr (it also switches herdr's view to that agent's tab) and brings
the terminal that runs herdr to the front. This works with tiling managers such as AeroSpace, which
follow the app to its workspace.

### Configure

The plugin reads the same file as the Linux daemon, `~/.config/herdr-dock/config.toml` (see
[`config.example.toml`](config.example.toml)). Only the shared settings apply on macOS: `herdr_socket`,
`herdr_bin` (where the herdr binary is, if it isn't found automatically), `label`, `resync_seconds`,
animation, `[colors]` and `[raise] macos`. `[raise] macos` is `"herdr-window"` by default (bring forward
the terminal app that hosts herdr); any other value is a shell command, and `enabled = false` turns
raising off. The `[linux]` and `[[home]]` tables are ignored.

### Reload, logs, troubleshooting

```bash
pkill -f herdr-dock-plugin                  # the app relaunches the plugin (after a rebuild or config change)
tail -f ~/Library/Logs/herdr-dock/plugin.log
```

New plugins and manifest changes need a full app restart.

| Symptom | Fix |
|---------|-----|
| Keys stay black | Black means an empty slot. Agents fill the keys in order from key 2, so put the action on keys 2, 3, 4... The log says which key the plugin sees (`key 2 appeared (column 1, row 2)`) |
| Keys don't show anything after the plugin restarts | The app doesn't re-announce keys that are already showing: leave the folder and open it again |
| `herdr offline` on the keys | herdr isn't running, or the socket differs. `herdr status server` shows the socket, and `herdr_socket` / `herdr_bin` in the config override the lookup |
| A press moves herdr but the terminal doesn't come forward | The log says `no terminal app found`: herdr isn't running in a macOS app (ssh or tmux from elsewhere). Set `[raise] macos` to your own command |
| A press brings the terminal forward but herdr stays on its tab | Older herdr that lacks `tab.focus`: the log says `could not focus the tab` |

Limits: the whole terminal app comes forward (not one window of it), the Exit key with status dots
isn't available because the app's own back key owns key 1, and the home-page "Herdr" button is the app's
folder key, not a plugin key (a plugin can't switch pages: see DESIGN.md).

## Development

```bash
scripts/setup.sh                        # once
scripts/check.sh                        # lint + strict types + unit tests (≥ 80 % coverage), before every commit
scripts/test-integration.sh herdr_live  # against a throwaway headless herdr session
scripts/test-integration.sh hardware    # against the plugged-in M18 (systemctl --user stop herdr-dock first)
scripts/render-preview.sh               # every key image → build/preview/sheet.png
```

Contributor rules are in [CLAUDE.md](CLAUDE.md) and DESIGN.md "Engineering rules".

### Scripts

Run from anywhere; they resolve the repo root themselves. Works with macOS's bash 3.2.

| Script | What it does |
|--------|--------------|
| `scripts/setup.sh [--recreate]` | Create `.venv`, install dev tools + this OS's extras, link the StreamDock Device SDK on Linux (`STREAMDOCK_SDK` overrides the path) |
| `scripts/check.sh` | Everything required before pushing: lint + types + unit tests with the 80 % coverage gate |
| `scripts/test.sh [pytest args]` | Unit tests with the coverage gate |
| `scripts/test-integration.sh [herdr_live\|hardware\|all]` | Opt-in tests against a live herdr and/or the plugged-in M18 |
| `scripts/lint.sh` | `ruff check`, `ruff format --check`, `mypy --strict` |
| `scripts/format.sh` | Apply ruff fixes and formatting |
| `scripts/run-console.sh [--once]` | Print live herdr agent states in the terminal (no device) |
| `scripts/render-preview.sh [dir]` | Render all key states/frames to PNGs for review |
| `scripts/run-linux.sh [-v]` | Run the Linux daemon in the foreground |
| `scripts/install-linux.sh [--udev\|--uninstall]` | Install + start the systemd `--user` service. `--udev`: install the M18 udev rule (sudo). `--uninstall`: remove the service |
| `scripts/build-macos-plugin.sh` | Build `dist/com.herdr.dock.sdPlugin` with PyInstaller (macOS) |
| `scripts/install-macos-plugin.sh` | Copy the plugin into the StreamDock app's plugin folder (`STREAMDOCK_PLUGINS_DIR` overrides it), then restart the app |

