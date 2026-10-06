#!/usr/bin/env bash
# Install the systemd --user service, or (with --udev) only the M18 udev rule.
# Usage: scripts/install-linux.sh [--udev]
. "$(dirname "$0")/_lib.sh"
require_os linux

if [ "${1:-}" = "--udev" ]; then
    rules="$ROOT/linux/70-herdr-dock.rules"
    log "installing $rules to /etc/udev/rules.d (sudo)"
    sudo install -m 0644 "$rules" /etc/udev/rules.d/70-herdr-dock.rules
    sudo udevadm control --reload-rules
    sudo udevadm trigger --subsystem-match=hidraw --subsystem-match=usb
    log "udev rule installed; replug the M18 if it still isn't accessible"
    exit 0
fi

use_venv
require_module linux.daemon 3

unit_src="$ROOT/linux/herdr-dock.service"
[ -f "$unit_src" ] || die "missing $unit_src (DESIGN.md milestone 4)"

unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$unit_dir"
sed -e "s|@VENV@|$VENV|g" -e "s|@ROOT@|$ROOT|g" "$unit_src" > "$unit_dir/herdr-dock.service"
log "installed $unit_dir/herdr-dock.service"

systemctl --user daemon-reload
systemctl --user enable --now herdr-dock.service
log "service running; logs: journalctl --user -u herdr-dock -f"
