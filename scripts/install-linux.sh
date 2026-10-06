#!/usr/bin/env bash
# Install herdr-dock on Linux.
# Usage:
#   scripts/install-linux.sh             install + start the systemd --user service
#   scripts/install-linux.sh --udev      install the M18 udev rule (sudo)
#   scripts/install-linux.sh --uninstall stop + remove the service
. "$(dirname "$0")/_lib.sh"
require_os linux

unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
unit="$unit_dir/herdr-dock.service"

case "${1:-}" in
    --udev)
        rules="$ROOT/linux/70-herdr-dock.rules"
        log "installing $rules to /etc/udev/rules.d (sudo)"
        sudo install -m 0644 "$rules" /etc/udev/rules.d/70-herdr-dock.rules
        sudo udevadm control --reload-rules
        sudo udevadm trigger --subsystem-match=hidraw --subsystem-match=usb
        log "udev rule installed; replug the M18 if it still isn't accessible"
        exit 0
        ;;
    --uninstall)
        systemctl --user disable --now herdr-dock.service 2>/dev/null || true
        rm -f "$unit"
        systemctl --user daemon-reload
        log "service removed"
        exit 0
        ;;
    "") ;;
    *) die "unknown option: $1 (use --udev or --uninstall)" ;;
esac

use_venv
require_module linux.daemon 3

if pgrep -f "python -m linux.daemon" >/dev/null && ! systemctl --user -q is-active herdr-dock.service; then
    die "a herdr-dock daemon is already running outside systemd (only one can drive the M18); stop it first"
fi

mkdir -p "$unit_dir"
sed -e "s|@VENV@|$VENV|g" -e "s|@ROOT@|$ROOT|g" "$ROOT/linux/herdr-dock.service" > "$unit"
log "installed $unit"

systemctl --user daemon-reload
systemctl --user enable herdr-dock.service
systemctl --user restart herdr-dock.service
log "service running; status: systemctl --user status herdr-dock · logs: journalctl --user -u herdr-dock -f"
