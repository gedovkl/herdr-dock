# Shared helpers for scripts/*.sh. Source it; don't run it.
# Kept compatible with macOS's bash 3.2 (no mapfile, no ${var,,}, no assoc arrays).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${HERDR_DOCK_VENV:-$ROOT/.venv}"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33mwarn:\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

os_name() {
    case "$(uname -s)" in
        Linux) echo linux ;;
        Darwin) echo macos ;;
        *) echo unsupported ;;
    esac
}

require_os() {
    [ "$(os_name)" = "$1" ] || die "this script only runs on $1 (this machine: $(os_name))"
}

# First python3.x on PATH that is >= 3.11.
find_python() {
    for candidate in "${PYTHON:-}" python3.14 python3.13 python3.12 python3.11 python3; do
        [ -n "$candidate" ] || continue
        if command -v "$candidate" >/dev/null 2>&1 &&
            "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
            command -v "$candidate"
            return 0
        fi
    done
    die "Python >= 3.11 not found (set PYTHON=/path/to/python3)"
}

# Activate the project venv, or tell the user to run setup first.
use_venv() {
    [ -x "$VENV/bin/python" ] || die "no virtualenv at $VENV; run scripts/setup.sh first"
    # shellcheck disable=SC1091
    . "$VENV/bin/activate"
    cd "$ROOT"
}

# Fail with a pointer to the milestone when an entry point isn't written yet.
require_module() {
    module="$1"
    milestone="$2"
    python -c "import importlib.util, sys; sys.exit(importlib.util.find_spec('$module') is None)" ||
        die "$module is not implemented yet (DESIGN.md milestone $milestone)"
}
