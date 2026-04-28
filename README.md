# codex-lsp-mcp

`codex-lsp-mcp` is a local MCP stdio server that exposes read-only LSP navigation tools to Codex.

Built-in defaults target `clangd`; additional LSP backends can be configured in
`~/.config/codex-lsp-mcp/config.toml`.

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

The server discovers the closest `compile_commands.json` from the queried file path.

Tool coordinates follow the LSP convention: zero-based `line` and `character`.

When multiple configured LSP backends match the same workspace directory, pass
`server_name` to `workspace_symbols` to select the intended backend explicitly.
