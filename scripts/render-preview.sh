#!/usr/bin/env bash
# Render every key state/frame to PNG files for visual review. Milestone 2.
# Usage: scripts/render-preview.sh [output-dir]   (default: build/preview)
. "$(dirname "$0")/_lib.sh"
use_venv
require_module herdr_core.preview 2

out="${1:-$ROOT/build/preview}"
mkdir -p "$out"
python -m herdr_core.preview --out "$out"
log "previews written to $out"
