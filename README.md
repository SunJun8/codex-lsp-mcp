# codex-lsp-mcp

`codex-lsp-mcp` is a local MCP stdio server that exposes read-only LSP navigation tools to Codex.

Built-in defaults target `clangd` for C/C++ and `pyright` for Python; additional
LSP backends can be configured in `~/.config/codex-lsp-mcp/config.toml`.

## Quick start

Run the published package from PyPI:

```bash
uvx codex-lsp-mcp
```

## Local development

```bash
uv run pytest
uvx --from . codex-lsp-mcp
```

## Codex configuration

```bash
codex mcp add codex-lsp-mcp -- uvx codex-lsp-mcp
```

Check registration:

```bash
codex mcp get codex-lsp-mcp
```

If `clangd` is not on Codex's `PATH`, set:

```toml
[mcp_servers.codex-lsp-mcp.env]
CLANGD_BIN = "/path/to/clangd"
```

For Python navigation, ensure `pyright-langserver` is on Codex's `PATH`.
If pyright is installed in a non-standard location, override the built-in
backend in `~/.config/codex-lsp-mcp/config.toml`:

```toml
[servers.pyright]
command = "/home/miot/.local/share/nvim/mason/bin/pyright-langserver"
args = ["--stdio"]
root_markers = [["pyrightconfig.json"], ["pyproject.toml"], ["setup.py"], ["setup.cfg"], ["requirements.txt"], ["Pipfile"], ["poetry.lock"], [".git", ".repo"]]
workspace_hint_extension = ".py"

[servers.pyright.extension_to_language]
".py" = "python"
```

The server discovers the closest `compile_commands.json` from the queried file path.

Tool coordinates follow the LSP convention: zero-based `line` and `character`.

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

When multiple configured LSP backends match the same workspace directory, pass
`server_name` to `workspace_symbols` to select the intended backend explicitly.
