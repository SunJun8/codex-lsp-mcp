# 默认支持 pyright LSP 设计

## 背景

`codex-lsp-mcp` 当前通过 `AppConfig.servers` 支持多个 LSP 后端，并由
`SessionManager.language_for()` 根据文件后缀选择后端。内置默认配置只包含
`clangd`，因此 Python 文件会返回 `unsupported file extension: .py`。

仓库已有通用 LSP 配置能力，用户可以在 `config.toml` 中手动添加 pyright。
本次目标是把 pyright 作为内置默认后端，让 Python 文件无需用户配置即可被路由
到合适的 LSP。

## 目标

- 默认配置同时支持 C/C++ 和 Python。
- `.py` 文件自动选择 `pyright` 后端，language id 为 `python`。
- 现有 C/C++ 文件继续选择 `clangd`，行为保持不变。
- 保留现有 `config.toml` 覆盖机制，用户可以覆盖 pyright 的命令、参数、
  root markers、初始化选项等。
- 不新增 `PYRIGHT_BIN` 或 `PYRIGHT_ARGS` 环境变量。

## 非目标

- 不实现新的后端选择算法。
- 不改变 MCP tool 的参数或返回结构。
- 不内置用户本机绝对路径作为默认命令。
- 不新增 pyright 安装或包管理逻辑。

## 方案

在 `default_config()` 中新增 `pyright` 的 `ServerConfig`：

```python
ServerConfig(
    command="pyright-langserver",
    args=["--stdio"],
    extension_to_language={".py": "python"},
    root_markers=(
        ("pyproject.toml",),
        ("setup.py",),
        ("setup.cfg",),
        ("requirements.txt",),
        ("Pipfile",),
        ("poetry.lock",),
        (".git", ".repo"),
    ),
    workspace_hint_extension=".py",
)
```

`SessionManager` 保持现有流程：

1. `ToolHandlers._resolve_file()` 解析并校验文件路径。
2. `SessionManager.language_for()` 按 `extension_to_language` 匹配文件后缀。
3. `.py` 文件返回 `("pyright", "python")`。
4. `SessionManager.get_session()` 使用 pyright 的 root markers 发现项目根。
5. `GenericLspSession` 启动 `pyright-langserver --stdio`。
6. definition、references、hover、diagnostics、document_symbols 和
   workspace_symbols 继续走现有通用 LSP 请求流程。

## 配置与本地环境

项目默认命令使用 `pyright-langserver`，依赖调用方的 `PATH`。这保持发布包的
可移植性，避免绑定到某个用户目录。

当前本机环境中 pyright 位于：

```text
/home/miot/.local/share/nvim/mason/bin/pyright-langserver
```

本地验证可以选择以下任一方式：

- 确保该目录在运行 `codex-lsp-mcp` 的 `PATH` 中。
- 使用现有 `config.toml` 覆盖：

```toml
[servers.pyright]
command = "/home/miot/.local/share/nvim/mason/bin/pyright-langserver"
args = ["--stdio"]
root_markers = [["pyproject.toml"], ["setup.py"], ["setup.cfg"], ["requirements.txt"], ["Pipfile"], ["poetry.lock"], [".git", ".repo"]]
workspace_hint_extension = ".py"

[servers.pyright.extension_to_language]
".py" = "python"
```

## 错误处理

沿用现有错误行为：

- 如果 `pyright-langserver` 不在 `PATH`，启动 LSP session 时返回
  `LSP server not found...`。
- 如果文件后缀没有任何后端匹配，继续返回 `unsupported file extension`。
- 如果目录 workspace hint 同时匹配多个后端且深度相同，继续返回 ambiguous
  workspace LSP server，并要求用户传 `server_name`。

## 测试计划

- 更新默认配置测试，断言 `load_config(env={})` 同时包含 `clangd` 和 `pyright`。
- 新增默认 pyright 配置断言：命令、参数、`.py` 映射、workspace hint 扩展名、
  root markers。
- 新增 manager 测试，断言默认配置下 `.py` 文件选择 pyright session。
- 新增 root discovery 覆盖，确认 pyright 使用 Python 项目标记发现根目录。
- 更新 README，说明内置默认支持 `clangd` 和 `pyright`，并说明
  `pyright-langserver` 需要在运行环境的 `PATH` 中。

## 成功标准

- `.py` 文件不再报 `unsupported file extension: .py`。
- `.py` 文件默认启动 `pyright-langserver --stdio`。
- 现有 clangd 默认行为不回退。
- 现有测试和新增测试通过。
