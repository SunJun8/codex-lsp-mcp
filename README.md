# codex-lsp-mcp

`codex-lsp-mcp` is a local MCP stdio server that exposes read-only LSP navigation tools to Codex.

First supported backend: `clangd`.

## Local development

```bash
uv run pytest
uvx --from . codex-lsp-mcp
```

## Codex configuration

```bash
codex mcp add codex-lsp-mcp -- uvx --from git+https://github.com/SunJun8/codex-lsp-mcp.git@v0.1.0 codex-lsp-mcp
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
