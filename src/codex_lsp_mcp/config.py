from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
import os
import shlex
import tomllib


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "codex-lsp-mcp" / "config.toml"
DEFAULT_ROOT_MARKER_GROUPS = (
    ("compile_commands.json",),
    ("compile_flags.txt",),
    (".clangd",),
    (".git", ".repo"),
)


@dataclass(frozen=True)
class ServerConfig:
    command: str
    args: list[str]
    extension_to_language: dict[str, str]
    root_markers: tuple[tuple[str, ...], ...] = DEFAULT_ROOT_MARKER_GROUPS
    workspace_hint_extension: str = ".c"
    initialization_options: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, Any] = field(
        default_factory=lambda: {"window": {"workDoneProgress": True}}
    )
    index_progress_token: str | None = None


@dataclass(frozen=True)
class AppConfig:
    servers: dict[str, ServerConfig]


def default_config() -> AppConfig:
    return AppConfig(
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
            )
        }
    )


def load_config(env: dict[str, str] | None = None) -> AppConfig:
    values = dict(os.environ if env is None else env)
    config = default_config()

    config_path = Path(values.get("CODEX_LSP_MCP_CONFIG", DEFAULT_CONFIG_PATH)).expanduser()
    if config_path.exists():
        config = _merge_config_file(config, config_path)

    servers = dict(config.servers)
    if "clangd" in servers:
        clangd = servers["clangd"]
        if "CLANGD_BIN" in values:
            clangd = replace(clangd, command=values["CLANGD_BIN"])
        if "CLANGD_ARGS" in values:
            clangd = replace(clangd, args=shlex.split(values["CLANGD_ARGS"]))
        servers["clangd"] = clangd
    return AppConfig(servers=servers)


def _merge_config_file(config: AppConfig, path: Path) -> AppConfig:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    servers = dict(config.servers)

    for name, raw_server in data.get("servers", {}).items():
        existing = servers.get(name, ServerConfig(command=name, args=[], extension_to_language={}))
        extension_to_language = raw_server.get(
            "extension_to_language", existing.extension_to_language
        )
        servers[name] = ServerConfig(
            command=raw_server.get("command", existing.command),
            args=list(raw_server.get("args", existing.args)),
            extension_to_language=dict(extension_to_language),
            root_markers=tuple(
                tuple(group)
                for group in raw_server.get("root_markers", existing.root_markers)
            ),
            workspace_hint_extension=raw_server.get(
                "workspace_hint_extension",
                existing.workspace_hint_extension,
            ),
            initialization_options=dict(
                raw_server.get("initialization_options", existing.initialization_options)
            ),
            capabilities=dict(raw_server.get("capabilities", existing.capabilities)),
            index_progress_token=raw_server.get(
                "index_progress_token",
                existing.index_progress_token,
            ),
        )

    return AppConfig(servers=servers)
