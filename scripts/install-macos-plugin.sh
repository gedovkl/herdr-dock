#!/usr/bin/env bash
# Copy the built plugin into the StreamDock app's plugin folder.
# The folder path is an open item in DESIGN.md; override it with STREAMDOCK_PLUGINS_DIR.
. "$(dirname "$0")/_lib.sh"
require_os macos

built="$ROOT/dist/com.herdr.dock.sdPlugin"
[ -d "$built" ] || die "nothing built; run scripts/build-macos-plugin.sh first"

dest_dir="${STREAMDOCK_PLUGINS_DIR:-$HOME/Library/Application Support/HotSpot/StreamDock/plugins}"
if [ -z "${STREAMDOCK_PLUGINS_DIR:-}" ]; then
    warn "using unverified default plugin dir: $dest_dir (set STREAMDOCK_PLUGINS_DIR)"
fi
[ -d "$dest_dir" ] || die "plugin dir not found: $dest_dir"

rm -rf "$dest_dir/com.herdr.dock.sdPlugin"
cp -R "$built" "$dest_dir/"
log "installed to $dest_dir; restart the StreamDock app"
