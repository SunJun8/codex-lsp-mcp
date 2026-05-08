from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import load_config
from .manager import SessionManager


JsonObject = dict[str, Any]


class ToolHandlers:
    def __init__(self, manager: SessionManager) -> None:
        self.manager = manager

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

    async def workspace_symbols(
        self,
        query: str,
        root_hint: str | None = None,
        server_name: str | None = None,
    ) -> JsonObject:
        """Return workspace symbols, optionally scoped by a root hint."""
        session = self.manager.get_workspace_session(root_hint, server_name=server_name)
        return await session.workspace_symbols(query)

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


def _default_fallback_root() -> Path:
    logical_cwd = os.environ.get("PWD")
    if logical_cwd:
        path = Path(logical_cwd).expanduser()
        if path.is_absolute() and path.exists():
            return path.resolve()
    return Path.cwd()


def build_mcp() -> FastMCP:
    config = load_config()
    manager = SessionManager(config, fallback_root=_default_fallback_root())
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
