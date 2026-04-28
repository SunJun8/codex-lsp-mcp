from pathlib import Path

from codex_lsp_mcp import config as config_module
from codex_lsp_mcp.config import AppConfig, ServerConfig, load_config


def test_load_config_uses_builtin_clangd_defaults(monkeypatch):
    monkeypatch.delenv("CODEX_LSP_MCP_CONFIG", raising=False)
    monkeypatch.delenv("CLANGD_BIN", raising=False)
    monkeypatch.delenv("CLANGD_ARGS", raising=False)

    config = load_config(env={})

    clangd = config.servers["clangd"]
    assert clangd.command == "clangd"
    assert clangd.args == ["--background-index"]
    assert clangd.extension_to_language[".c"] == "c"
    assert clangd.extension_to_language[".cpp"] == "cpp"
    assert clangd.workspace_hint_extension == ".c"
    assert clangd.index_progress_token == "backgroundIndexProgress"


def test_load_config_reads_config_file(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[servers.clangd]
command = "/opt/clangd"
args = ["--background-index", "--clang-tidy"]

[servers.clangd.extension_to_language]
".c" = "c"
".h" = "c"
""",
        encoding="utf-8",
    )

    config = load_config(env={"CODEX_LSP_MCP_CONFIG": str(config_path)})

    clangd = config.servers["clangd"]
    assert clangd.command == "/opt/clangd"
    assert clangd.args == ["--background-index", "--clang-tidy"]
    assert clangd.extension_to_language == {".c": "c", ".h": "c"}


def test_load_config_reads_generic_lsp_server_fields(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[servers.pyright]
command = "pyright-langserver"
args = ["--stdio"]
root_markers = [["pyproject.toml"], ["setup.py"], [".git"]]
workspace_hint_extension = ".py"

[servers.pyright.initialization_options]
pythonPath = ".venv/bin/python"

[servers.pyright.extension_to_language]
".py" = "python"
""",
        encoding="utf-8",
    )

    config = load_config(env={"CODEX_LSP_MCP_CONFIG": str(config_path)})

    pyright = config.servers["pyright"]
    assert pyright.command == "pyright-langserver"
    assert pyright.args == ["--stdio"]
    assert pyright.extension_to_language == {".py": "python"}
    assert pyright.root_markers == (("pyproject.toml",), ("setup.py",), (".git",))
    assert pyright.workspace_hint_extension == ".py"
    assert pyright.initialization_options == {"pythonPath": ".venv/bin/python"}


def test_env_overrides_config_file(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[servers.clangd]
command = "/opt/clangd"
args = ["--background-index"]
""",
        encoding="utf-8",
    )

    config = load_config(
        env={
            "CODEX_LSP_MCP_CONFIG": str(config_path),
            "CLANGD_BIN": "/custom/clangd",
            "CLANGD_ARGS": "--background-index --clang-tidy",
        }
    )

    clangd = config.servers["clangd"]
    assert clangd.command == "/custom/clangd"
    assert clangd.args == ["--background-index", "--clang-tidy"]


def test_missing_config_path_is_ignored(tmp_path):
    config = load_config(env={"CODEX_LSP_MCP_CONFIG": str(tmp_path / "missing.toml")})

    assert config.servers["clangd"].command == "clangd"


def test_clangd_env_override_is_ignored_when_clangd_is_not_configured(monkeypatch):
    monkeypatch.setattr(
        config_module,
        "default_config",
        lambda: AppConfig(
            servers={
                "pyright": ServerConfig(
                    command="pyright-langserver",
                    args=["--stdio"],
                    extension_to_language={".py": "python"},
                )
            }
        ),
    )

    config = load_config(env={"CLANGD_BIN": "/custom/clangd"})

    assert set(config.servers) == {"pyright"}
