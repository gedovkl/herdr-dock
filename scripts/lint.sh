#!/usr/bin/env bash
# Lint, format check and strict type check. Read-only; use scripts/format.sh to fix.
. "$(dirname "$0")/_lib.sh"
use_venv

log "ruff check"
ruff check .
log "ruff format --check"
ruff format --check .
log "mypy --strict (herdr_core, linux)"
mypy
