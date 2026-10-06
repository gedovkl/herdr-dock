#!/usr/bin/env bash
# Everything that must pass before pushing: lint, types, unit tests + coverage gate.
. "$(dirname "$0")/_lib.sh"

"$ROOT/scripts/lint.sh"
"$ROOT/scripts/test.sh" "$@"
log "all checks passed"
