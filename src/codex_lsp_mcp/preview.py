from __future__ import annotations

from pathlib import Path
from typing import Any


def make_position(line: int, character: int) -> dict[str, int]:
    if line < 0 or character < 0:
        raise ValueError("line and character must be zero-based non-negative integers")
    return {"line": line, "character": character}


def lsp_range_to_user_range(lsp_range: dict[str, Any]) -> dict[str, int]:
    start = lsp_range["start"]
    end = lsp_range["end"]
    return {
        "line": start["line"],
        "character": start["character"],
        "end_line": end["line"],
        "end_character": end["character"],
    }


def read_preview(path: str | Path, line: int) -> str:
    if line < 1:
        return ""
    file_path = Path(path)
    try:
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return ""
    if line > len(lines):
        return ""
    return lines[line - 1].strip()
