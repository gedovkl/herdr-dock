#!/usr/bin/env bash
# Build the StreamDock app plugin bundle into dist/com.herdr.dock.sdPlugin.
. "$(dirname "$0")/_lib.sh"
require_os macos
use_venv

bundle_src="$ROOT/macos/com.herdr.dock.sdPlugin"
spec="$ROOT/macos/plugin.spec"
[ -d "$bundle_src" ] || die "missing $bundle_src (DESIGN.md milestone 5)"
[ -f "$spec" ] || die "missing $spec (DESIGN.md milestone 5)"

out="$ROOT/dist/com.herdr.dock.sdPlugin"
log "pyinstaller $spec"
pyinstaller --noconfirm --clean --distpath "$ROOT/build/pyinstaller" --workpath "$ROOT/build/pyinstaller-work" "$spec"

log "assembling $out"
rm -rf "$out"
mkdir -p "$ROOT/dist"
cp -R "$bundle_src" "$out"
cp "$ROOT/build/pyinstaller/herdr-dock-plugin" "$out/"
log "built $out"
