#!/usr/bin/env bash
# Opt-in integration tests against real things.
# Usage: scripts/test-integration.sh [herdr_live|hardware|all] [pytest args...]
#   herdr_live  needs a running herdr server
#   hardware    needs the StreamDock M18 plugged in
. "$(dirname "$0")/_lib.sh"
use_venv

target="${1:-all}"
[ $# -gt 0 ] && shift
case "$target" in
    herdr_live) marker="herdr_live" ;;
    hardware) marker="hardware" ;;
    all) marker="herdr_live or hardware" ;;
    *) die "unknown target '$target' (use herdr_live, hardware or all)" ;;
esac

if [ "$target" != hardware ] && ! command -v herdr >/dev/null 2>&1; then
    warn "herdr is not on PATH; herdr_live tests will skip or fail"
fi

log "integration tests: $marker"
# -o addopts= drops the default "not hardware and not herdr_live" filter; no coverage gate here.
status=0
python -m pytest -o addopts= --strict-markers -m "$marker" tests/integration "$@" || status=$?
# pytest exit 5 = no tests collected; not a failure while integration tests are still being written.
[ "$status" -eq 5 ] && { warn "no $marker tests collected yet"; exit 0; }
exit "$status"
