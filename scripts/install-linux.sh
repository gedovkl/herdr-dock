#!/usr/bin/env bash
# Install the systemd --user service and (with --udev) the StreamDock udev rule.
# Usage: scripts/install-linux.sh [--udev]
. "$(dirname "$0")/_lib.sh"
require_os linux
use_venv
require_module linux.daemon 3

unit_src="$ROOT/linux/herdr-dock.service"
[ -f "$unit_src" ] || die "missing $unit_src (DESIGN.md milestone 4)"

unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$unit_dir"
sed -e "s|@VENV@|$VENV|g" -e "s|@ROOT@|$ROOT|g" "$unit_src" > "$unit_dir/herdr-dock.service"
log "installed $unit_dir/herdr-dock.service"

if [ "${1:-}" = "--udev" ]; then
    rules="${STREAMDOCK_SDK:-$ROOT/../StreamDock-Device-SDK/Python-SDK}/99-streamdock.rules"
    [ -f "$rules" ] || die "udev rules not found at $rules"
    log "installing udev rule (sudo)"
    sudo install -m 0644 "$rules" /etc/udev/rules.d/99-streamdock.rules
    sudo udevadm control --reload-rules
    sudo udevadm trigger
fi

systemctl --user daemon-reload
systemctl --user enable --now herdr-dock.service
log "service running; logs: journalctl --user -u herdr-dock -f"
