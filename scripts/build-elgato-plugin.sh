#!/usr/bin/env bash
# Build the Elgato Stream Deck app plugin bundle into dist/elgato/com.herdr.dock.sdPlugin.
. "$(dirname "$0")/_lib.sh"
require_os macos
use_venv

bundle_src="$ROOT/elgato/com.herdr.dock.sdPlugin"
spec="$ROOT/elgato/plugin.spec"
[ -d "$bundle_src" ] || die "missing $bundle_src"
[ -f "$spec" ] || die "missing $spec"

out="$ROOT/dist/elgato/com.herdr.dock.sdPlugin"
log "pyinstaller $spec"
pyinstaller --noconfirm --clean --distpath "$ROOT/build/pyinstaller-elgato" --workpath "$ROOT/build/pyinstaller-elgato-work" "$spec"

log "assembling $out"
rm -rf "$out"
mkdir -p "$ROOT/dist/elgato"
cp -R "$bundle_src" "$out"
cp "$ROOT/build/pyinstaller-elgato/herdr-dock-plugin" "$out/"
log "built $out"
