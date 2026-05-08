# File Tools Root Hint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional `root_hint` support to file-oriented LSP tools so each call can provide its project context explicitly.

**Architecture:** Keep `root_hint` as a per-call tool parameter. `ToolHandlers` resolves relative file paths from `root_hint` when provided, then passes the resolved root context to `SessionManager`; `SessionManager` uses normal marker discovery first and falls back to the per-call root when markers are absent.

**Tech Stack:** Python 3.11, pytest, MCP FastMCP, stdio LSP JSON-RPC, clangd, pyright-langserver.

---

## File Structure

- Modify `src/codex_lsp_mcp/server.py`
  - Add optional `root_hint` parameters to `definition`, `references`, `hover`, `diagnostics`, and `document_symbols`.
  - Extend `_resolve_file()` to resolve relative files from `root_hint` when provided.
  - Validate `root_hint` and pass its resolved context into `SessionManager.get_session()`.
- Modify `src/codex_lsp_mcp/manager.py`
  - Add optional `root_hint` to `get_session()`.
  - Add a small helper to convert a root hint into a fallback directory.
  - Extend `_get_session_for_server()` so marker discovery can fall back to the per-call root.
- Modify `tests/test_server.py`
  - Update fake manager signatures.
  - Add coverage for relative file paths with `root_hint`.
  - Add coverage that absolute file paths are not rewritten by `root_hint`.
  - Add coverage that invalid `root_hint` fails instead of falling back.
- Modify `tests/test_manager.py`
  - Add coverage that no-marker roots fall back to per-call `root_hint`.
  - Add coverage that marker roots override per-call `root_hint`.
  - Add coverage for clangd and pyright marker separation.
- Modify `README.md`
  - Document `root_hint` for file tools.
  - Document that `workspace_symbols` already accepts `root_hint`.

## Task 1: Add Handler Tests For File Tool Root Hints

**Files:**
- Modify: `tests/test_server.py`
- Test: `tests/test_server.py`

- [ ] **Step 1: Update `FakeManager` to record root hints**

In `tests/test_server.py`, replace the `FakeManager` class with:

```python
class FakeManager:
    def __init__(self):
        self.fallback_root = Path("/fallback")
        self.sessions = {}
        self.session = FakeSession()
        self.paths = []
        self.root_hints = []

    def get_session(self, path, root_hint=None):
        resolved = Path(path).expanduser().resolve()
        resolved_root_hint = (
            None if root_hint is None else Path(root_hint).expanduser().resolve()
        )
        self.paths.append(resolved)
        self.root_hints.append(resolved_root_hint)
        self.sessions[("clangd", resolved.parent)] = self.session
        return self.session

    def get_workspace_session(self, root_hint=None, server_name=None):
        self.workspace_server_name = server_name
        if root_hint is None:
            if self.sessions:
                return next(iter(self.sessions.values()))
            return self.get_session(self.fallback_root / ".codex_lsp_workspace_hint.c")
        return self.get_session(root_hint)

    def language_for(self, path):
        suffix = Path(path).suffix
        if suffix not in {".c", ".h"}:
            raise ValueError(f"unsupported file extension: {suffix}")
        return ("clangd", "c")
```

- [ ] **Step 2: Add a failing test for relative paths with directory root hints**

Append this test after `test_file_tools_resolve_relative_paths_from_fallback_root`:

```python
@pytest.mark.asyncio
async def test_file_tools_resolve_relative_paths_from_root_hint(tmp_path):
    workspace = tmp_path / "workspace"
    source = workspace / "src" / "main.c"
    source.parent.mkdir(parents=True)
    source.write_text("void main_symbol(void) {}\n", encoding="utf-8")
    manager = FakeManager()
    handlers = ToolHandlers(manager)

    await handlers.document_symbols("src/main.c", root_hint=str(workspace))

    assert manager.session.calls == [
        ("document_symbols", source.resolve(), "c"),
    ]
    assert manager.root_hints == [workspace.resolve()]
```

- [ ] **Step 3: Add a failing test for absolute paths with root hints**

Append this test after the previous new test:

```python
@pytest.mark.asyncio
async def test_file_tools_keep_absolute_file_path_when_root_hint_is_passed(tmp_path):
    workspace = tmp_path / "workspace"
    other = tmp_path / "other"
    source = workspace / "src" / "main.c"
    source.parent.mkdir(parents=True)
    other.mkdir()
    source.write_text("void main_symbol(void) {}\n", encoding="utf-8")
    manager = FakeManager()
    handlers = ToolHandlers(manager)

    await handlers.diagnostics(str(source), root_hint=str(other))

    assert manager.session.calls == [
        ("diagnostics", source.resolve(), "c"),
    ]
    assert manager.root_hints == [other.resolve()]
```

- [ ] **Step 4: Add a failing test for invalid root hints**

Append this test after the previous new test:

```python
@pytest.mark.asyncio
async def test_file_tools_reject_missing_root_hint_for_relative_path(tmp_path):
    workspace = tmp_path / "workspace"
    source = workspace / "src" / "main.c"
    source.parent.mkdir(parents=True)
    source.write_text("void main_symbol(void) {}\n", encoding="utf-8")
    manager = FakeManager()
    handlers = ToolHandlers(manager)

    with pytest.raises(FileNotFoundError):
        await handlers.document_symbols(
            "src/main.c",
            root_hint=str(tmp_path / "missing"),
        )

    assert manager.session.calls == []
```

- [ ] **Step 5: Run the focused handler tests and verify they fail**

Run:

```bash
rtk uv run pytest \
  tests/test_server.py::test_file_tools_resolve_relative_paths_from_root_hint \
  tests/test_server.py::test_file_tools_keep_absolute_file_path_when_root_hint_is_passed \
  tests/test_server.py::test_file_tools_reject_missing_root_hint_for_relative_path \
  -v
```

Expected: FAIL with `TypeError` because file tools do not accept `root_hint` yet.

- [ ] **Step 6: Commit the failing handler tests**

```bash
rtk git add tests/test_server.py
rtk git commit -m "test(server): cover file tool root hints"
```

## Task 2: Add Manager Tests For Per-Call Root Fallback

**Files:**
- Modify: `tests/test_manager.py`
- Test: `tests/test_manager.py`

- [ ] **Step 1: Add no-marker fallback coverage**

Append this test after `test_manager_uses_server_specific_root_markers`:

```python
def test_manager_get_session_falls_back_to_root_hint_without_markers(tmp_path):
    workspace = tmp_path / "workspace"
    source_dir = workspace / "src"
    fallback = tmp_path / "server"
    source_dir.mkdir(parents=True)
    fallback.mkdir()
    path = source_dir / "main.c"
    path.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    config = AppConfig(
        servers={
            "clangd": ServerConfig(
                command="clangd",
                args=["--background-index"],
                extension_to_language={".c": "c"},
            )
        }
    )
    manager = SessionManager(config, fallback_root=fallback, session_factory=FakeSession)

    session = manager.get_session(path, root_hint=workspace)

    assert session.root == workspace.resolve()
```

- [ ] **Step 2: Add marker-precedence coverage**

Append this test after the previous new test:

```python
def test_manager_get_session_prefers_marker_root_over_root_hint(tmp_path):
    workspace = tmp_path / "workspace"
    package = workspace / "packages" / "native"
    source_dir = package / "src"
    fallback = tmp_path / "server"
    source_dir.mkdir(parents=True)
    fallback.mkdir()
    (package / "compile_commands.json").write_text("[]", encoding="utf-8")
    path = source_dir / "main.c"
    path.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    config = AppConfig(
        servers={
            "clangd": ServerConfig(
                command="clangd",
                args=["--background-index"],
                extension_to_language={".c": "c"},
            )
        }
    )
    manager = SessionManager(config, fallback_root=fallback, session_factory=FakeSession)

    session = manager.get_session(path, root_hint=workspace)

    assert session.root == package.resolve()
```

- [ ] **Step 3: Add backend-specific marker coverage**

Append this test after the previous new test:

```python
def test_manager_root_hint_preserves_backend_specific_markers(tmp_path):
    workspace = tmp_path / "workspace"
    native = workspace / "native"
    python = workspace / "python"
    native_src = native / "src"
    python_src = python / "src"
    native_src.mkdir(parents=True)
    python_src.mkdir(parents=True)
    (native / "compile_commands.json").write_text("[]", encoding="utf-8")
    (python / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\n",
        encoding="utf-8",
    )
    c_file = native_src / "main.c"
    py_file = python_src / "app.py"
    c_file.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    py_file.write_text("def main():\n    return 0\n", encoding="utf-8")
    manager = SessionManager(
        default_config(),
        fallback_root=tmp_path / "server",
        session_factory=FakeSession,
    )

    c_session = manager.get_session(c_file, root_hint=workspace)
    py_session = manager.get_session(py_file, root_hint=workspace)

    assert c_session.root == native.resolve()
    assert c_session.server_config.command == "clangd"
    assert py_session.root == python.resolve()
    assert py_session.server_config.command == "pyright-langserver"
```

- [ ] **Step 4: Run the focused manager tests and verify they fail**

Run:

```bash
rtk uv run pytest \
  tests/test_manager.py::test_manager_get_session_falls_back_to_root_hint_without_markers \
  tests/test_manager.py::test_manager_get_session_prefers_marker_root_over_root_hint \
  tests/test_manager.py::test_manager_root_hint_preserves_backend_specific_markers \
  -v
```

Expected: FAIL with `TypeError` because `SessionManager.get_session()` does not accept `root_hint` yet.

- [ ] **Step 5: Commit the failing manager tests**

```bash
rtk git add tests/test_manager.py
rtk git commit -m "test(manager): cover per-call root fallback"
```

## Task 3: Implement Root Hint Support

**Files:**
- Modify: `src/codex_lsp_mcp/server.py`
- Modify: `src/codex_lsp_mcp/manager.py`
- Test: `tests/test_server.py`, `tests/test_manager.py`

- [ ] **Step 1: Update file tool signatures in `server.py`**

Change the five file-oriented tool methods to accept and forward `root_hint`:

```python
    async def definition(
        self,
        file: str,
        line: int,
        character: int,
        root_hint: str | None = None,
    ) -> JsonObject:
        """Return definition locations for a zero-based LSP position."""
        path, language_id, session = self._resolve_file(file, root_hint)
        return await session.definition(path, language_id, line, character)

    async def references(
        self,
        file: str,
        line: int,
        character: int,
        include_declaration: bool = False,
        root_hint: str | None = None,
    ) -> JsonObject:
        """Return references for a zero-based LSP position."""
        path, language_id, session = self._resolve_file(file, root_hint)
        return await session.references(
            path,
            language_id,
            line,
            character,
            include_declaration,
        )

    async def hover(
        self,
        file: str,
        line: int,
        character: int,
        root_hint: str | None = None,
    ) -> JsonObject:
        """Return hover text for a zero-based LSP position."""
        path, language_id, session = self._resolve_file(file, root_hint)
        return await session.hover(path, language_id, line, character)

    async def diagnostics(
        self,
        file: str,
        root_hint: str | None = None,
    ) -> JsonObject:
        """Return diagnostics for a file."""
        path, language_id, session = self._resolve_file(file, root_hint)
        return await session.diagnostics(path, language_id)

    async def document_symbols(
        self,
        file: str,
        root_hint: str | None = None,
    ) -> JsonObject:
        """Return document symbols for a file."""
        path, language_id, session = self._resolve_file(file, root_hint)
        return await session.document_symbols(path, language_id)
```

- [ ] **Step 2: Add root hint path helpers in `server.py`**

Replace `_resolve_file()` with these methods:

```python
    def _resolve_file(
        self,
        file: str,
        root_hint: str | None = None,
    ) -> tuple[Path, str, Any]:
        root_path = self._resolve_root_hint(root_hint)
        raw_path = Path(file).expanduser()
        if raw_path.is_absolute():
            path = raw_path.resolve()
        else:
            base = self._relative_file_base(root_path)
            path = (base / raw_path).resolve()
        if not path.exists():
            raise FileNotFoundError(path)

        _server_name, language_id = self.manager.language_for(path)
        session = self.manager.get_session(path, root_hint=root_path)
        return path, language_id, session

    def _resolve_root_hint(self, root_hint: str | None) -> Path | None:
        if root_hint is None:
            return None
        path = Path(root_hint).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(path)
        return path

    def _relative_file_base(self, root_hint: Path | None) -> Path:
        if root_hint is None:
            return self.manager.fallback_root
        if root_hint.is_file():
            return root_hint.parent
        return root_hint
```

- [ ] **Step 3: Update `manager.py` imports if needed**

Keep existing imports. `Path` is already imported and no new module import is needed.

- [ ] **Step 4: Update `get_session()` in `manager.py`**

Replace `get_session()` with:

```python
    def get_session(
        self,
        file_path: str | Path,
        root_hint: str | Path | None = None,
    ) -> LspNavigationSession:
        path = Path(file_path).expanduser().resolve()
        server_name, _language_id = self.language_for(path)
        fallback_root = self._session_fallback_root(root_hint)
        return self._get_session_for_server(server_name, path, fallback_root)
```

- [ ] **Step 5: Update `_get_session_for_server()` in `manager.py`**

Replace `_get_session_for_server()` with:

```python
    def _get_session_for_server(
        self,
        server_name: str,
        file_path: Path,
        fallback_root: Path | None = None,
    ) -> LspNavigationSession:
        server_config = self._server_config(server_name)
        root = discover_root(
            file_path,
            fallback_root or self.fallback_root,
            server_config.root_markers,
        )
        key = (server_name, root)
        if key not in self.sessions:
            self.sessions[key] = self.session_factory(root, server_config)
        return self.sessions[key]
```

- [ ] **Step 6: Add `_session_fallback_root()` in `manager.py`**

Insert this helper before `_workspace_hint_path()`:

```python
    def _session_fallback_root(self, root_hint: str | Path | None) -> Path:
        if root_hint is None:
            return self.fallback_root
        path = Path(root_hint).expanduser().resolve()
        if path.is_file():
            return path.parent
        return path
```

- [ ] **Step 7: Preserve workspace session behavior**

Do not change `get_workspace_session()` in this task. Existing calls to `_get_session_for_server(server_name, hint_file)` remain valid because `_get_session_for_server()` now defaults `fallback_root` to `None`.

- [ ] **Step 8: Run the focused handler tests**

Run:

```bash
rtk uv run pytest \
  tests/test_server.py::test_file_tools_resolve_relative_paths_from_root_hint \
  tests/test_server.py::test_file_tools_keep_absolute_file_path_when_root_hint_is_passed \
  tests/test_server.py::test_file_tools_reject_missing_root_hint_for_relative_path \
  -v
```

Expected: PASS.

- [ ] **Step 9: Run the focused manager tests**

Run:

```bash
rtk uv run pytest \
  tests/test_manager.py::test_manager_get_session_falls_back_to_root_hint_without_markers \
  tests/test_manager.py::test_manager_get_session_prefers_marker_root_over_root_hint \
  tests/test_manager.py::test_manager_root_hint_preserves_backend_specific_markers \
  -v
```

Expected: PASS.

- [ ] **Step 10: Run existing server and manager suites**

Run:

```bash
rtk uv run pytest tests/test_server.py tests/test_manager.py -v
```

Expected: PASS.

- [ ] **Step 11: Commit implementation**

```bash
rtk git add src/codex_lsp_mcp/server.py src/codex_lsp_mcp/manager.py tests/test_server.py tests/test_manager.py
rtk git commit -m "feat(lsp): add file tool root hints"
```

## Task 4: Document File Tool Root Hints

**Files:**
- Modify: `README.md`
- Test: `README.md`

- [ ] **Step 1: Add usage documentation**

Insert this section after the paragraph that says tool coordinates are zero-based:

````markdown
## Workspace roots

File-oriented tools (`definition`, `references`, `hover`, `diagnostics`, and
`document_symbols`) accept an optional `root_hint` argument. Use it when `file`
is relative or when the MCP server process is not running from the project root:

```json
{
  "file": "miio_test/cli.py",
  "line": 86,
  "character": 18,
  "root_hint": "/home/miot/Work/miot/tool/miio_test"
}
```

Absolute `file` paths are not rewritten by `root_hint`, but the hint is still
used as the fallback workspace root when no server-specific root marker is
found. Server-specific markers still take precedence, such as
`compile_commands.json` for clangd and `pyproject.toml` for pyright.

`workspace_symbols` already accepts `root_hint` and can also take `server_name`
when a directory is ambiguous across multiple configured LSP backends.
````

- [ ] **Step 2: Check README formatting**

Run:

```bash
rtk sed -n '1,180p' README.md
```

Expected: The new `Workspace roots` section renders as Markdown with the JSON block nested correctly.

- [ ] **Step 3: Commit README update**

```bash
rtk git add README.md
rtk git commit -m "docs(readme): document file tool root hints"
```

## Task 5: Full Verification And Real Pyright Smoke Test

**Files:**
- No source edits expected.
- Test: full repository tests and local MCP tool behavior.

- [ ] **Step 1: Run the full test suite**

Run:

```bash
rtk uv run pytest
```

Expected: PASS for all tests.

- [ ] **Step 2: Run the package import check**

Run:

```bash
rtk uv run python -c "from codex_lsp_mcp.server import build_mcp; build_mcp(); print('ok')"
```

Expected: prints `ok`.

- [ ] **Step 3: Use the updated MCP against the miio_test project**

Start or reload Codex with the updated local MCP package, then call:

```json
{
  "file": "miio_test/cli.py",
  "line": 86,
  "character": 18,
  "root_hint": "/home/miot/Work/miot/tool/miio_test"
}
```

for `hover` and `definition`.

Expected:

- `hover` for `normalize_method` returns `def normalize_method(method: str) -> str`.
- `definition` returns `/home/miot/Work/miot/tool/miio_test/miio_test/cli.py` line `55`.

- [ ] **Step 4: Use the updated MCP for cross-file pyright import resolution**

Call `hover` or `definition` on `ConfigManager` in:

```json
{
  "file": "miio_test/cli.py",
  "line": 8,
  "character": 31,
  "root_hint": "/home/miot/Work/miot/tool/miio_test"
}
```

Expected:

- `definition` resolves to `/home/miot/Work/miot/tool/miio_test/miio_test/config.py`.
- `hover` no longer reports `ConfigManager: Unknown`.

- [ ] **Step 5: Inspect final status**

Run:

```bash
rtk git status --short
rtk git log --oneline -5
```

Expected: clean worktree. Recent commits should include the test, implementation, and README commits from this plan.
