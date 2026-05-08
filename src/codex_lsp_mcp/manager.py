from __future__ import annotations

from pathlib import Path
from typing import Callable

from .config import AppConfig, ServerConfig
from .root import discover_root, find_marked_root
from .session import GenericLspSession, LspNavigationSession


SessionFactory = Callable[[Path, ServerConfig], LspNavigationSession]


class SessionManager:
    def __init__(
        self,
        config: AppConfig,
        fallback_root: str | Path,
        session_factory: SessionFactory = GenericLspSession,
    ) -> None:
        self.config = config
        self.fallback_root = Path(fallback_root).expanduser().resolve()
        self.session_factory = session_factory
        self.sessions: dict[tuple[str, Path], LspNavigationSession] = {}

    def get_session(
        self,
        file_path: str | Path,
        root_hint: str | Path | None = None,
    ) -> LspNavigationSession:
        path = Path(file_path).expanduser().resolve()
        server_name, _language_id = self.language_for(path)
        fallback_root = self._session_fallback_root(root_hint)
        return self._get_session_for_server(server_name, path, fallback_root)

    def get_workspace_session(
        self,
        root_hint: str | Path | None = None,
        server_name: str | None = None,
    ) -> LspNavigationSession:
        if server_name is not None:
            self._server_config(server_name)
            hint_file = self._workspace_hint_path(root_hint, server_name)
            return self._get_session_for_server(server_name, hint_file)

        if root_hint is not None:
            hint = Path(root_hint).expanduser().resolve()
            if hint.is_file():
                return self.get_session(hint)
            server_name = self._infer_workspace_server_name(hint)
            hint_file = self._workspace_hint_path(hint, server_name)
            return self._get_session_for_server(server_name, hint_file)

        try:
            return next(iter(self.sessions.values()))
        except StopIteration:
            server_name = self._default_server_name()
            hint_file = self._workspace_hint_path(self.fallback_root, server_name)
            return self._get_session_for_server(server_name, hint_file)

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

    def _session_fallback_root(self, root_hint: str | Path | None) -> Path:
        if root_hint is None:
            return self.fallback_root
        path = Path(root_hint).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(path)
        if path.is_file():
            return path.parent
        return path

    def _workspace_hint_path(self, root_hint: str | Path | None, server_name: str) -> Path:
        config = self._server_config(server_name)
        hint = self.fallback_root if root_hint is None else Path(root_hint).expanduser().resolve()
        if hint.is_file() or (not hint.exists() and hint.suffix):
            return hint
        return hint / f".codex_lsp_workspace_hint{config.workspace_hint_extension}"

    def _infer_workspace_server_name(self, directory: Path) -> str:
        selected: list[tuple[str, int]] = []

        for server_name, server_config in self.config.servers.items():
            hint_file = directory / f".codex_lsp_workspace_hint{server_config.workspace_hint_extension}"
            root = find_marked_root(hint_file, server_config.root_markers)
            if root is None:
                continue
            depth = len(root.parts)
            selected.append((server_name, depth))

        if not selected:
            return self._default_server_name()

        max_depth = max(depth for _server_name, depth in selected)
        deepest = [
            server_name for server_name, depth in selected if depth == max_depth
        ]
        if len(deepest) > 1:
            names = ", ".join(deepest)
            raise ValueError(
                f"ambiguous workspace LSP server for {directory}: {names}; "
                f"pass server_name explicitly"
            )
        return deepest[0]

    def _server_config(self, server_name: str) -> ServerConfig:
        try:
            return self.config.servers[server_name]
        except KeyError as exc:
            raise ValueError(f"unknown LSP server: {server_name}") from exc

    def _default_server_name(self) -> str:
        try:
            return next(iter(self.config.servers))
        except StopIteration as exc:
            raise RuntimeError("no LSP servers configured") from exc

    def language_for(self, file_path: str | Path) -> tuple[str, str]:
        path = Path(file_path)
        for server_name, server_config in self.config.servers.items():
            language_id = server_config.extension_to_language.get(path.suffix)
            if language_id:
                return server_name, language_id
        raise ValueError(f"unsupported file extension: {path.suffix}")
