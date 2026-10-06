#!/usr/bin/env bash
# Create .venv and install the package with dev tools and this OS's extras.
# Usage: scripts/setup.sh [--recreate]
. "$(dirname "$0")/_lib.sh"

if [ "${1:-}" = "--recreate" ]; then
    log "removing $VENV"
    rm -rf "$VENV"
fi

case "$(os_name)" in
    linux) extras="dev,linux" ;;
    macos) extras="dev,macos" ;;
    *) die "unsupported OS: $(uname -s)" ;;
esac

if [ ! -x "$VENV/bin/python" ]; then
    py="$(find_python)"
    log "creating virtualenv with $py"
    "$py" -m venv "$VENV"
fi

log "installing herdr-dock[$extras] (editable)"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -e "$ROOT[$extras]"

if [ "$(os_name)" = linux ]; then
    sdk="${STREAMDOCK_SDK:-$(cd "$ROOT/.." && pwd)/StreamDock-Device-SDK/Python-SDK/src}"
    if [ -d "$sdk/StreamDock" ]; then
        site="$("$VENV/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
        echo "$sdk" > "$site/streamdock-device-sdk.pth"
        log "linked StreamDock Device SDK: $sdk"
    else
        warn "StreamDock Device SDK not found at $sdk (set STREAMDOCK_SDK); the daemon needs it"
    fi
fi

log "done; activate with: source $VENV/bin/activate"
