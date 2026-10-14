#!/usr/bin/env bash
# Copy the built plugin into the Elgato Stream Deck app's plugin folder.
# Override the folder with ELGATO_PLUGINS_DIR.
. "$(dirname "$0")/_lib.sh"
require_os macos

built="$ROOT/dist/elgato/com.herdr.dock.sdPlugin"
[ -d "$built" ] || die "nothing built; run scripts/build-elgato-plugin.sh first"

dest_dir="${ELGATO_PLUGINS_DIR:-$HOME/Library/Application Support/com.elgato.StreamDeck/Plugins}"
[ -d "$dest_dir" ] || die "plugin dir not found: $dest_dir (is the Elgato Stream Deck app installed?)"

rm -rf "$dest_dir/com.herdr.dock.sdPlugin"
cp -R "$built" "$dest_dir/"
log "installed to $dest_dir"
log "quit the Stream Deck app completely (Cmd+Q) and reopen it; logs: ~/Library/Logs/herdr-dock/elgato-plugin.log"
