#!/usr/bin/env bash
# Apply ruff autofixes and formatting.
. "$(dirname "$0")/_lib.sh"
use_venv

log "ruff check --fix"
ruff check --fix .
log "ruff format"
ruff format .
