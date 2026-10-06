#!/usr/bin/env bash
# Copy the built plugin into the StreamDock app (VSD Craft)'s plugin folder.
# Override the folder with STREAMDOCK_PLUGINS_DIR.
. "$(dirname "$0")/_lib.sh"
require_os macos

built="$ROOT/dist/com.herdr.dock.sdPlugin"
[ -d "$built" ] || die "nothing built; run scripts/build-macos-plugin.sh first"

dest_dir="${STREAMDOCK_PLUGINS_DIR:-$HOME/Library/Application Support/HotSpot/StreamDock/plugins}"
[ -d "$dest_dir" ] || die "plugin dir not found: $dest_dir (is the StreamDock app installed?)"

rm -rf "$dest_dir/com.herdr.dock.sdPlugin"
cp -R "$built" "$dest_dir/"
log "installed to $dest_dir"
log "quit the StreamDock app completely (Cmd+Q) and reopen it; logs: ~/Library/Logs/herdr-dock/plugin.log"
