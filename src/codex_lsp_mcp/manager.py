from __future__ import annotations

from pathlib import Path
from typing import Callable

from .config import AppConfig, ServerConfig
from .root import discover_root
from .session import ClangdSession


SessionFactory = Callable[[Path, ServerConfig], ClangdSession]


class SessionManager:
    def __init__(
        self,
        config: AppConfig,
        fallback_root: str | Path,
        session_factory: SessionFactory = ClangdSession,
    ) -> None:
        self.config = config
        self.fallback_root = Path(fallback_root).expanduser().resolve()
        self.session_factory = session_factory
        self.sessions: dict[tuple[str, Path], ClangdSession] = {}

    def get_session(self, file_path: str | Path) -> ClangdSession:
        path = Path(file_path).expanduser().resolve()
        server_name, _language_id = self.language_for(path)
        root = discover_root(path, self.fallback_root)
        key = (server_name, root)
        if key not in self.sessions:
            self.sessions[key] = self.session_factory(root, self.config.servers[server_name])
        return self.sessions[key]

    def language_for(self, file_path: str | Path) -> tuple[str, str]:
        path = Path(file_path)
        for server_name, server_config in self.config.servers.items():
            language_id = server_config.extension_to_language.get(path.suffix)
            if language_id:
                return server_name, language_id
        raise ValueError(f"unsupported file extension: {path.suffix}")
