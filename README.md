# herdr-dock

Shows [herdr](https://herdr.dev) coding agents as live keys on a StreamDock M18. Each key shows
an agent's status with herdr's own symbols (`×` blocked, `◐` working, `✓` done, `○` idle). Blocked
agents blink. Press a key to switch herdr to that agent and bring its terminal window to the front.

- **Linux:** a standalone daemon that drives the M18 directly through the StreamDock Device SDK
- **macOS:** a plugin for the official StreamDock app (not built yet, milestone 5)

Both use the same `herdr_core` package. See [DESIGN.md](DESIGN.md) for the architecture,
engineering rules (SOLID, ≥ 80 % test coverage) and milestones, and [CHANGELOG.md](CHANGELOG.md)
for what was built and what was learned about herdr and the M18 along the way.

**Status:** Linux is done: the daemon works on the M18 and runs as a systemd user service
(milestones 1–4). The macOS plugin (milestone 5) is still to come.

## How it works on the dock

- **Home page:** keys you define in the config, such as launching an app, running a command, or
  `◐ herdr` (key 1 by default), which enters Herdr mode.
- **Herdr mode:** key 1 is `◀ herdr` (Exit, back to the home page). Keys 2–15 are your agents. With
  more than 14 agents, key 15 becomes the pager (`▶ 1/2`).
- **Buttons under the screen:** left enters or leaves Herdr mode, right shows the next page of
  agents, and middle does nothing. All three are configurable.
- herdr is only contacted while Herdr mode is on. Entering Herdr mode also brings the herdr
  window to the front (`focus_herdr_on_enter`).
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
| `[[home]]` | Home-page keys: `key = 1..15` plus one of `herdr = true`, `app = "<desktop id>"`, `run = "<shell command>"` or `widget = "clock" \| "weather"`. Optional `label`, `symbol`, `icon = "<path>"`, and `focus = "<window class regex>"` to focus an already-running window instead of starting another one |
| `[linux.buttons]` | `left`/`middle`/`right` → `"herdr"`, `"page"` or `"none"` |
| `[linux] focus_herdr_on_enter` | `true` (default): entering Herdr mode also brings the herdr window to the front (Hyprland) |
| `[raise] linux` | `"herdr-window"` (default): focus the window the herdr client runs in, via Hyprland. Any other value is a shell command (`{pane_id}`, `{cwd}`, … are filled in; write literal braces as `{{ }}`). Set `enabled = false` to never raise |
| `label` | Text under the symbol: `"cwd"` (folder), `"title"` or `"name"` |
| `attention` | Statuses that blink or pulse: `["blocked"]` by default; add `"done"` to make finished work pulse until you look at it |
| `[colors]` | Per-status colours (`blocked = "#ff0000"`) |
| `[linux] brightness`, `device_ids`, `app_launcher` | Screen brightness 0–100, USB IDs to look for, the command `app = …` keys use (`uwsm-app -- {app}`) |

Restart the daemon after changing the config (`systemctl --user restart herdr-dock` once it runs as a service).

#### Clock and weather keys

```toml
[[home]]
key = 5
widget = "clock"
time_format = "%H:%M"      # strftime format; "%I:%M %p" for 12-hour, "%H:%M:%S" with seconds
date_format = "%a %d %b"   # "" hides the date

[[home]]
key = 10
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
- Widget keys can also act when pressed: add `run`, `app` or `focus` (for example
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
| Weather key shows `--` | No network, or the coordinates are wrong. The log says `weather update failed …` once. It retries every minute |
| Service doesn't start at login | `systemctl --user status herdr-dock`. It needs `graphical-session.target`, which uwsm and most Wayland session managers provide |

## Setup on macOS

Not available yet (milestone 5). The plan is a plugin for the official StreamDock app that
appears as a "Herdr" folder of agent keys. See DESIGN.md, "macOS front end".

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
| `scripts/build-macos-plugin.sh` | Build `dist/com.herdr.dock.sdPlugin` with PyInstaller (macOS, milestone 5) |
| `scripts/install-macos-plugin.sh` | Copy the plugin into the StreamDock app (`STREAMDOCK_PLUGINS_DIR` overrides the path) |

Scripts whose code isn't written yet stop with the DESIGN.md milestone that adds it.
