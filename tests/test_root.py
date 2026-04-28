from codex_lsp_mcp.root import discover_root


def test_discover_root_prefers_nearest_compile_commands(tmp_path):
    top = tmp_path / "repo"
    sub = top / "module"
    src = sub / "src"
    src.mkdir(parents=True)
    (top / "compile_commands.json").write_text("[]", encoding="utf-8")
    (sub / "compile_commands.json").write_text("[]", encoding="utf-8")
    file_path = src / "main.c"
    file_path.write_text("int main(void) { return 0; }\n", encoding="utf-8")

    assert discover_root(file_path, fallback=tmp_path) == sub


def test_discover_root_uses_compile_flags_before_repo_marker(tmp_path):
    repo = tmp_path / "repo"
    src = repo / "src"
    src.mkdir(parents=True)
    (repo / ".repo").mkdir()
    (src / "compile_flags.txt").write_text("-Wall\n", encoding="utf-8")
    file_path = src / "driver.c"
    file_path.write_text("void driver(void) {}\n", encoding="utf-8")

    assert discover_root(file_path, fallback=tmp_path) == src


def test_discover_root_falls_back_to_startup_dir(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    file_path = src / "driver.c"
    file_path.write_text("void driver(void) {}\n", encoding="utf-8")

    assert discover_root(file_path, fallback=tmp_path) == tmp_path
