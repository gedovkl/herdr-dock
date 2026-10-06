"""Render the systemd unit template: `python -m linux.service TEMPLATE ROOT VENV`."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path


def _systemd_escape(value: str) -> str:
    """systemd expands %-specifiers in unit files; a literal % must be written %%."""
    return value.replace("%", "%%")


def _quote(value: str) -> str:
    """Double-quote one ExecStart word (systemd's quoting: backslash escapes \\ and ")."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_unit(template: str, root: Path, venv: Path) -> str:
    python = _quote(_systemd_escape(str(venv / "bin" / "python")))
    return template.replace("@PYTHON@", python).replace("@ROOT@", _systemd_escape(str(root)))


def main(argv: Sequence[str] | None = None) -> int:
    template, root, venv = argv if argv is not None else sys.argv[1:]
    sys.stdout.write(render_unit(Path(template).read_text(), Path(root), Path(venv)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
