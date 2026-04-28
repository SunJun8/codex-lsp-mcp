from pathlib import Path

from codex_lsp_mcp.preview import lsp_range_to_user_range, make_position, read_preview


def test_make_position_uses_lsp_zero_based_coordinates():
    assert make_position(0, 0) == {"line": 0, "character": 0}
    assert make_position(2, 4) == {"line": 2, "character": 4}


def test_lsp_range_to_user_range_preserves_lsp_zero_based_coordinates():
    result = lsp_range_to_user_range(
        {"start": {"line": 2, "character": 4}, "end": {"line": 2, "character": 9}}
    )

    assert result == {
        "line": 2,
        "character": 4,
        "end_line": 2,
        "end_character": 9,
    }


def test_read_preview_returns_trimmed_line(tmp_path):
    path = Path(tmp_path / "main.c")
    path.write_text("int a;\n  int target(void);\n", encoding="utf-8")

    assert read_preview(path, 2) == "int target(void);"
