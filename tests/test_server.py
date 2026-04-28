from pathlib import Path

import pytest

from codex_lsp_mcp.server import ToolHandlers


class FakeSession:
    def __init__(self):
        self.calls = []

    async def definition(self, path, language_id, line, character):
        self.calls.append(("definition", path, language_id, line, character))
        return {
            "items": [
                {
                    "file": str(path),
                    "line": line,
                    "character": character,
                    "language_id": language_id,
                }
            ]
        }

    async def references(self, path, language_id, line, character, include_declaration):
        self.calls.append(
            ("references", path, language_id, line, character, include_declaration)
        )
        return {"items": [{"include_declaration": include_declaration}]}

    async def hover(self, path, language_id, line, character):
        self.calls.append(("hover", path, language_id, line, character))
        return {"contents": f"{language_id}:{line}:{character}"}

    async def diagnostics(self, path, language_id):
        self.calls.append(("diagnostics", path, language_id))
        return {"items": [{"path": str(path), "language_id": language_id}]}

    async def document_symbols(self, path, language_id):
        self.calls.append(("document_symbols", path, language_id))
        return {"items": [{"path": str(path), "language_id": language_id}]}

    async def workspace_symbols(self, query):
        self.calls.append(("workspace_symbols", query))
        return {"items": [{"query": query}]}


class FakeManager:
    def __init__(self):
        self.fallback_root = Path("/fallback")
        self.sessions = {}
        self.session = FakeSession()
        self.paths = []

    def get_session(self, path):
        resolved = Path(path).expanduser().resolve()
        self.paths.append(resolved)
        self.sessions[("clangd", resolved.parent)] = self.session
        return self.session

    def language_for(self, path):
        suffix = Path(path).suffix
        if suffix not in {".c", ".h"}:
            raise ValueError(f"unsupported file extension: {suffix}")
        return ("clangd", "c")


@pytest.mark.asyncio
async def test_definition_delegates_to_manager(tmp_path):
    path = tmp_path / "main.c"
    path.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    handlers = ToolHandlers(FakeManager())

    result = await handlers.definition(str(path), 1, 5)

    assert result["items"] == [
        {
            "file": str(path.resolve()),
            "line": 1,
            "character": 5,
            "language_id": "c",
        }
    ]


@pytest.mark.asyncio
async def test_definition_rejects_missing_file(tmp_path):
    handlers = ToolHandlers(FakeManager())

    with pytest.raises(FileNotFoundError):
        await handlers.definition(str(tmp_path / "missing.c"), 1, 1)


@pytest.mark.asyncio
async def test_position_tools_use_finalized_session_argument_order(tmp_path):
    path = tmp_path / "main.c"
    path.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    manager = FakeManager()
    handlers = ToolHandlers(manager)

    await handlers.references(str(path), 2, 3, include_declaration=True)
    await handlers.hover(str(path), 4, 5)

    assert manager.session.calls == [
        ("references", path.resolve(), "c", 2, 3, True),
        ("hover", path.resolve(), "c", 4, 5),
    ]


@pytest.mark.asyncio
async def test_file_tools_use_finalized_session_argument_order(tmp_path):
    path = tmp_path / "main.c"
    path.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    manager = FakeManager()
    handlers = ToolHandlers(manager)

    await handlers.diagnostics(str(path))
    await handlers.document_symbols(str(path))

    assert manager.session.calls == [
        ("diagnostics", path.resolve(), "c"),
        ("document_symbols", path.resolve(), "c"),
    ]


@pytest.mark.asyncio
async def test_workspace_symbols_uses_existing_session_without_root_hint():
    manager = FakeManager()
    session = FakeSession()
    manager.sessions[("clangd", Path("/repo"))] = session
    handlers = ToolHandlers(manager)

    result = await handlers.workspace_symbols("main")

    assert result == {"items": [{"query": "main"}]}
    assert session.calls == [("workspace_symbols", "main")]


@pytest.mark.asyncio
async def test_workspace_symbols_uses_fallback_root_without_root_hint_before_any_session():
    manager = FakeManager()
    handlers = ToolHandlers(manager)

    await handlers.workspace_symbols("main")

    assert manager.paths == [(Path("/fallback") / ".codex_lsp_workspace_hint.c").resolve()]
    assert manager.session.calls == [("workspace_symbols", "main")]


@pytest.mark.asyncio
async def test_workspace_symbols_uses_file_root_hint(tmp_path):
    path = tmp_path / "main.c"
    path.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    manager = FakeManager()
    handlers = ToolHandlers(manager)

    await handlers.workspace_symbols("main", root_hint=str(path))

    assert manager.paths == [path.resolve()]
    assert manager.session.calls == [("workspace_symbols", "main")]


@pytest.mark.asyncio
async def test_workspace_symbols_uses_synthetic_c_file_for_directory_hint(tmp_path):
    manager = FakeManager()
    handlers = ToolHandlers(manager)

    await handlers.workspace_symbols("main", root_hint=str(tmp_path))

    assert manager.paths == [(tmp_path / ".codex_lsp_workspace_hint.c").resolve()]
    assert manager.session.calls == [("workspace_symbols", "main")]
