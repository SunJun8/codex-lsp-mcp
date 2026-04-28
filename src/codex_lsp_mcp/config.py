from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import os
import shlex
import tomllib


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "codex-lsp-mcp" / "config.toml"


@dataclass(frozen=True)
class ServerConfig:
    command: str
    args: list[str]
    extension_to_language: dict[str, str]


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
            )
        }
    )


def load_config(env: dict[str, str] | None = None) -> AppConfig:
    values = dict(os.environ if env is None else env)
    config = default_config()

    config_path = Path(values.get("CODEX_LSP_MCP_CONFIG", DEFAULT_CONFIG_PATH)).expanduser()
    if config_path.exists():
        config = _merge_config_file(config, config_path)

    clangd = config.servers["clangd"]
    if "CLANGD_BIN" in values:
        clangd = replace(clangd, command=values["CLANGD_BIN"])
    if "CLANGD_ARGS" in values:
        clangd = replace(clangd, args=shlex.split(values["CLANGD_ARGS"]))

    servers = dict(config.servers)
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
        )

    return AppConfig(servers=servers)
