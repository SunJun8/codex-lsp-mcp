from __future__ import annotations

from pathlib import Path


ROOT_MARKER_GROUPS = (
    ("compile_commands.json",),
    ("compile_flags.txt",),
    (".clangd",),
    (".git", ".repo"),
)


def discover_root(file_path: str | Path, fallback: str | Path) -> Path:
    path = Path(file_path).expanduser().resolve()
    current = path.parent if path.is_file() or path.suffix else path
    fallback_path = Path(fallback).expanduser().resolve()
    ancestors = [current, *current.parents]

    for markers in ROOT_MARKER_GROUPS:
        for directory in ancestors:
            if any((directory / marker).exists() for marker in markers):
                return directory

    return fallback_path
