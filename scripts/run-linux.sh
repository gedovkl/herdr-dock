#!/usr/bin/env bash
# Run the Linux daemon in the foreground. Milestone 3.
# Extra args go to the daemon, e.g. scripts/run-linux.sh --config ./config.toml --verbose
. "$(dirname "$0")/_lib.sh"
require_os linux
use_venv
require_module linux.daemon 3

exec python -m linux.daemon "$@"
