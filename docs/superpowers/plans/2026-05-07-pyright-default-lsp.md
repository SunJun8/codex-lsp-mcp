# Pyright Default LSP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add built-in pyright support so `.py` files automatically route to `pyright-langserver --stdio`.

**Architecture:** Keep the existing generic LSP architecture. Extend `default_config()` with a second built-in `ServerConfig` named `pyright`; `SessionManager.language_for()` and `get_session()` will continue selecting backends from `extension_to_language` and server-specific root markers.

**Tech Stack:** Python 3.11, pytest, MCP FastMCP, stdio LSP JSON-RPC, pyright-langserver.

---

## File Structure

- Modify `src/codex_lsp_mcp/config.py`
  - Add Python root marker defaults.
  - Add built-in `pyright` to `default_config()`.
- Modify `tests/test_config.py`
  - Assert default config contains `pyright`.
  - Assert pyright command, args, `.py` mapping, workspace hint extension, and root markers.
- Modify `tests/test_manager.py`
  - Add coverage that default config routes `.py` files to pyright and discovers a Python project root.
- Modify `README.md`
  - Document that built-in defaults cover `clangd` and `pyright`.
  - Document that `pyright-langserver` must be available on the MCP server process `PATH`.
  - Document optional `config.toml` override for users with pyright in a non-standard path.

## Task 1: Add Failing Default Config Tests

**Files:**
- Modify: `tests/test_config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Update the built-in defaults test**

Change `test_load_config_uses_builtin_clangd_defaults` to assert both built-in servers and pyright defaults:

```python
def test_load_config_uses_builtin_clangd_and_pyright_defaults(monkeypatch):
    monkeypatch.delenv("CODEX_LSP_MCP_CONFIG", raising=False)
    monkeypatch.delenv("CLANGD_BIN", raising=False)
    monkeypatch.delenv("CLANGD_ARGS", raising=False)

    config = load_config(env={})

    assert set(config.servers) == {"clangd", "pyright"}

    clangd = config.servers["clangd"]
    assert clangd.command == "clangd"
    assert clangd.args == ["--background-index"]
    assert clangd.extension_to_language[".c"] == "c"
    assert clangd.extension_to_language[".cpp"] == "cpp"
    assert clangd.workspace_hint_extension == ".c"
    assert clangd.index_progress_token == "backgroundIndexProgress"

    pyright = config.servers["pyright"]
    assert pyright.command == "pyright-langserver"
    assert pyright.args == ["--stdio"]
    assert pyright.extension_to_language == {".py": "python"}
    assert pyright.workspace_hint_extension == ".py"
    assert pyright.root_markers == (
        ("pyproject.toml",),
        ("setup.py",),
        ("setup.cfg",),
        ("requirements.txt",),
        ("Pipfile",),
        ("poetry.lock",),
        (".git", ".repo"),
    )
    assert pyright.index_progress_token is None
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
rtk uv run pytest tests/test_config.py::test_load_config_uses_builtin_clangd_and_pyright_defaults -v
```

Expected: FAIL because `config.servers` only contains `clangd`, or because `pyright` is missing.

- [ ] **Step 3: Commit the failing test**

```bash
rtk git add tests/test_config.py
rtk git commit -m "test(lsp): cover default pyright config"
```

## Task 2: Implement Built-In Pyright Defaults

**Files:**
- Modify: `src/codex_lsp_mcp/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Add Python root marker defaults**

In `src/codex_lsp_mcp/config.py`, add this constant after `DEFAULT_ROOT_MARKER_GROUPS`:

```python
DEFAULT_PYRIGHT_ROOT_MARKER_GROUPS = (
    ("pyproject.toml",),
    ("setup.py",),
    ("setup.cfg",),
    ("requirements.txt",),
    ("Pipfile",),
    ("poetry.lock",),
    (".git", ".repo"),
)
```

- [ ] **Step 2: Add the pyright server to `default_config()`**

Replace the `servers={...}` body in `default_config()` with:

```python
        servers={
            "clangd": ServerConfig(
                command="clangd",
                args=["--background-index"],
                extension_to_language={
                    ".c": "c",
                    ".h": "c",
                    ".cpp": "cpp",
                    ".cc": "cpp",
                    ".cxx": "cpp",
                    ".hpp": "cpp",
                    ".hxx": "cpp",
                    ".C": "cpp",
                    ".H": "cpp",
                },
                index_progress_token="backgroundIndexProgress",
            ),
            "pyright": ServerConfig(
                command="pyright-langserver",
                args=["--stdio"],
                extension_to_language={".py": "python"},
                root_markers=DEFAULT_PYRIGHT_ROOT_MARKER_GROUPS,
                workspace_hint_extension=".py",
            ),
        }
```

- [ ] **Step 3: Run the focused config test and verify it passes**

Run:

```bash
rtk uv run pytest tests/test_config.py::test_load_config_uses_builtin_clangd_and_pyright_defaults -v
```

Expected: PASS.

- [ ] **Step 4: Run all config tests**

Run:

```bash
rtk uv run pytest tests/test_config.py -v
```

Expected: PASS. This verifies existing config file merge behavior still works with the new default server.

- [ ] **Step 5: Commit the implementation**

```bash
rtk git add src/codex_lsp_mcp/config.py tests/test_config.py
rtk git commit -m "feat(lsp): add default pyright backend"
```

## Task 3: Add Manager Routing Coverage

**Files:**
- Modify: `tests/test_manager.py`
- Test: `tests/test_manager.py`

- [ ] **Step 1: Import `default_config` in manager tests**

Change the import at the top of `tests/test_manager.py` from:

```python
from codex_lsp_mcp.config import AppConfig, ServerConfig
```

to:

```python
from codex_lsp_mcp.config import AppConfig, ServerConfig, default_config
```

- [ ] **Step 2: Add a default pyright routing test**

Append this test near the other pyright manager tests:

```python
def test_manager_default_config_routes_python_files_to_pyright(tmp_path):
    root = tmp_path / "repo"
    src = root / "src"
    src.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    path = src / "app.py"
    path.write_text("def main():\n    return 0\n", encoding="utf-8")
    manager = SessionManager(
        default_config(),
        fallback_root=tmp_path,
        session_factory=FakeSession,
    )

    server_name, language_id = manager.language_for(path)
    session = manager.get_session(path)

    assert (server_name, language_id) == ("pyright", "python")
    assert session.root == root
    assert session.server_config.command == "pyright-langserver"
    assert session.server_config.args == ["--stdio"]
```

- [ ] **Step 3: Run the focused manager test**

Run:

```bash
rtk uv run pytest tests/test_manager.py::test_manager_default_config_routes_python_files_to_pyright -v
```

Expected: PASS after Task 2. If it fails, inspect whether `default_config()` contains `pyright` and whether root markers include `pyproject.toml`.

- [ ] **Step 4: Run all manager tests**

Run:

```bash
rtk uv run pytest tests/test_manager.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit manager coverage**

```bash
rtk git add tests/test_manager.py
rtk git commit -m "test(lsp): cover default python routing"
```

## Task 4: Update README

**Files:**
- Modify: `README.md`
- Test: manual README review

- [ ] **Step 1: Update the default backend description**

Replace:

```markdown
Built-in defaults target `clangd`; additional LSP backends can be configured in
`~/.config/codex-lsp-mcp/config.toml`.
```

with:

```markdown
Built-in defaults target `clangd` for C/C++ and `pyright` for Python; additional
LSP backends can be configured in `~/.config/codex-lsp-mcp/config.toml`.
```

- [ ] **Step 2: Add pyright installation/path note**

After the `CLANGD_BIN` example, add:

````markdown
For Python navigation, ensure `pyright-langserver` is on Codex's `PATH`.
If pyright is installed in a non-standard location, override the built-in
backend in `~/.config/codex-lsp-mcp/config.toml`:

```toml
[servers.pyright]
command = "/home/miot/.local/share/nvim/mason/bin/pyright-langserver"
args = ["--stdio"]
root_markers = [["pyproject.toml"], ["setup.py"], ["setup.cfg"], ["requirements.txt"], ["Pipfile"], ["poetry.lock"], [".git", ".repo"]]
workspace_hint_extension = ".py"

[servers.pyright.extension_to_language]
".py" = "python"
```
````

- [ ] **Step 3: Review README rendering**

Run:

```bash
rtk sed -n '1,120p' README.md
```

Expected: The TOML code fence is closed correctly, and the pyright note appears after the clangd environment variable example.

- [ ] **Step 4: Commit README update**

```bash
rtk git add README.md
rtk git commit -m "docs(readme): document default pyright backend"
```

## Task 5: Final Verification

**Files:**
- Read: `src/codex_lsp_mcp/config.py`
- Read: `tests/test_config.py`
- Read: `tests/test_manager.py`
- Read: `README.md`

- [ ] **Step 1: Run full test suite**

Run:

```bash
rtk uv run pytest
```

Expected: PASS for all tests.

- [ ] **Step 2: Verify pyright binary availability for local runtime**

Run:

```bash
rtk /home/miot/.local/share/nvim/mason/bin/pyright-langserver --help
```

Expected: The command prints pyright language server help text or exits successfully after displaying usage information. If the command is missing, do not change project defaults; report that local runtime verification could not be completed.

- [ ] **Step 3: Verify clean working tree**

Run:

```bash
rtk git status --short
```

Expected: no output.

- [ ] **Step 4: Record final status**

Summarize:

- Tests run and result.
- Whether the local pyright binary exists at `/home/miot/.local/share/nvim/mason/bin/pyright-langserver`.
- Final commit hashes created by the implementation.

## Self-Review

- Spec coverage: Tasks 1 and 2 implement default pyright config; Task 3 covers automatic `.py` backend selection and Python root discovery; Task 4 covers README updates and local non-standard pyright path; Task 5 covers full verification.
- Placeholder scan: The plan contains concrete file paths, code snippets, commands, and expected results.
- Type consistency: The plan uses existing `ServerConfig`, `AppConfig`, `SessionManager`, `FakeSession`, and `default_config()` names consistently with the current codebase.
