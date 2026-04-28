from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path


DEFAULT_ROOT_MARKER_GROUPS = (
    ("compile_commands.json",),
    ("compile_flags.txt",),
    (".clangd",),
    (".git", ".repo"),
)


def discover_root(
    file_path: str | Path,
    fallback: str | Path,
    marker_groups: Sequence[Sequence[str]] = DEFAULT_ROOT_MARKER_GROUPS,
) -> Path:
    return find_marked_root(file_path, marker_groups) or Path(fallback).expanduser().resolve()


def find_marked_root(
    file_path: str | Path,
    marker_groups: Sequence[Sequence[str]] = DEFAULT_ROOT_MARKER_GROUPS,
) -> Path | None:
    path = Path(file_path).expanduser().resolve()
    current = path.parent if path.is_file() or path.suffix else path
    ancestors = [current, *current.parents]

    for markers in marker_groups:
        for directory in ancestors:
            if any((directory / marker).exists() for marker in markers):
                return directory

    return None
