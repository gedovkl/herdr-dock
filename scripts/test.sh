#!/usr/bin/env bash
# Unit tests with the coverage gate (fail_under in pyproject.toml).
# Extra args go to pytest, e.g. scripts/test.sh -k store -x
. "$(dirname "$0")/_lib.sh"
use_venv

log "unit tests + coverage"
python -m pytest --cov --cov-report=term-missing --cov-report=xml "$@"
