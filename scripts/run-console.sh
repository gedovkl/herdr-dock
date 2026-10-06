#!/usr/bin/env bash
# Print live herdr agent states in the terminal (no device needed). Milestone 1.
# Extra args go to the console entry point.
. "$(dirname "$0")/_lib.sh"
use_venv
require_module herdr_core.console 1

exec python -m herdr_core.console "$@"
