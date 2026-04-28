from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import load_config
from .manager import SessionManager


JsonObject = dict[str, Any]


class ToolHandlers:
    def __init__(self, manager: SessionManager) -> None:
        self.manager = manager

    async def definition(self, file: str, line: int, character: int) -> JsonObject:
        """Return definition locations for a zero-based LSP position."""
        path, language_id, session = self._resolve_file(file)
        return await session.definition(path, language_id, line, character)

    async def references(
        self,
        file: str,
        line: int,
        character: int,
        include_declaration: bool = False,
    ) -> JsonObject:
        """Return references for a zero-based LSP position."""
        path, language_id, session = self._resolve_file(file)
        return await session.references(
            path,
            language_id,
            line,
            character,
            include_declaration,
        )

    async def hover(self, file: str, line: int, character: int) -> JsonObject:
        """Return hover text for a zero-based LSP position."""
        path, language_id, session = self._resolve_file(file)
        return await session.hover(path, language_id, line, character)

    async def diagnostics(self, file: str) -> JsonObject:
        """Return diagnostics for a file."""
        path, language_id, session = self._resolve_file(file)
        return await session.diagnostics(path, language_id)

    async def document_symbols(self, file: str) -> JsonObject:
        """Return document symbols for a file."""
        path, language_id, session = self._resolve_file(file)
        return await session.document_symbols(path, language_id)

    async def workspace_symbols(
        self,
        query: str,
        root_hint: str | None = None,
    ) -> JsonObject:
        """Return workspace symbols, optionally scoped by a root hint."""
        if root_hint is not None:
            hint = Path(root_hint).expanduser().resolve()
            session_path = hint if hint.is_file() else hint / ".codex_lsp_workspace_hint.c"
            session = self.manager.get_session(session_path)
        else:
            try:
                session = next(iter(self.manager.sessions.values()))
            except StopIteration:
                session_path = self.manager.fallback_root / ".codex_lsp_workspace_hint.c"
                session = self.manager.get_session(session_path)
        return await session.workspace_symbols(query)

    def _resolve_file(self, file: str) -> tuple[Path, str, Any]:
        path = Path(file).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(path)

        _server_name, language_id = self.manager.language_for(path)
        session = self.manager.get_session(path)
        return path, language_id, session


def build_mcp() -> FastMCP:
    config = load_config()
    manager = SessionManager(config, fallback_root=Path.cwd())
    handlers = ToolHandlers(manager)
    mcp = FastMCP("codex-lsp-mcp")

    mcp.tool()(handlers.definition)
    mcp.tool()(handlers.references)
    mcp.tool()(handlers.hover)
    mcp.tool()(handlers.diagnostics)
    mcp.tool()(handlers.document_symbols)
    mcp.tool()(handlers.workspace_symbols)

    return mcp


def main() -> None:
    build_mcp().run()
