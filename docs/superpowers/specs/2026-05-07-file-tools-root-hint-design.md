# 文件类 LSP 工具 root_hint 设计

## 背景

`codex-lsp-mcp` 是一个通用 MCP stdio server，进程路径可能位于工具仓库或
包缓存目录，而不是当前被分析的项目目录。当前文件类工具只接收 `file`，当
`file` 是相对路径时会基于 `SessionManager.fallback_root` 解析；session root
发现也会在没有 marker 时回退到这个 fallback root。

这会让工具进程位置和被分析项目位置产生不必要耦合。`workspace_symbols`
已经支持 `root_hint`，但 `definition`、`references`、`hover`、`diagnostics`
和 `document_symbols` 尚不支持。目标是让每次工具调用显式携带项目上下文，
不依赖全局配置、环境变量或移动 MCP 安装路径。

## 目标

- 给所有文件类工具新增可选 `root_hint` 参数。
- 让相对 `file` 可以基于调用方传入的 `root_hint` 解析。
- 让 session root discovery 在没有 marker 时回退到本次调用的 `root_hint`。
- 保持未传 `root_hint` 的旧行为兼容。
- 保持 `clangd` 和 `pyright` 共用同一套机制，只使用各自已有 root markers。

## 非目标

- 不新增全局 workspace 状态。
- 不新增环境变量或配置项。
- 不改变 MCP 进程的启动目录或安装路径。
- 不改变 LSP 后端选择算法。
- 不改变工具返回结构。

## API 设计

所有文件类工具新增可选参数 `root_hint: str | None = None`：

```python
async def definition(
    self,
    file: str,
    line: int,
    character: int,
    root_hint: str | None = None,
) -> JsonObject

async def references(
    self,
    file: str,
    line: int,
    character: int,
    include_declaration: bool = False,
    root_hint: str | None = None,
) -> JsonObject

async def hover(
    self,
    file: str,
    line: int,
    character: int,
    root_hint: str | None = None,
) -> JsonObject

async def diagnostics(
    self,
    file: str,
    root_hint: str | None = None,
) -> JsonObject

async def document_symbols(
    self,
    file: str,
    root_hint: str | None = None,
) -> JsonObject
```

参数名复用 `workspace_symbols` 已有的 `root_hint`，避免引入
`workspace_root` 等第二套概念。

## 路径解析

`ToolHandlers._resolve_file()` 接收 `root_hint`，并按以下顺序解析文件路径：

1. 如果 `file` 是绝对路径，直接解析为该绝对路径。
2. 如果 `file` 是相对路径且传入 `root_hint`，基于 `root_hint` 解析。
3. 如果 `file` 是相对路径且未传 `root_hint`，基于现有 `fallback_root` 解析。

如果解析后的文件不存在，返回 `FileNotFoundError`。传错 `root_hint` 时不静默
回退到 `fallback_root`，这样可以尽早暴露调用方上下文错误。

`root_hint` 可以是目录或文件：

- 目录：作为相对路径基准和 session root fallback。
- 文件：其父目录作为相对路径基准；该文件自身可参与 root discovery。

## Session Root 选择

新增 manager 层能力，让文件类工具可以在本次调用中传入 root fallback：

```python
SessionManager.get_session(file_path, root_hint=None)
```

流程：

1. `language_for(file_path)` 根据文件扩展名选择后端。
2. 使用该后端的 `root_markers` 从 `file_path` 向上发现 root。
3. 如果找到 marker root，使用 marker root。
4. 如果没有找到 marker root，回退到本次调用的 `root_hint`。
5. 如果没有传 `root_hint`，继续回退到现有 `fallback_root`。

session cache key 仍然是 `(server_name, root)`，所以不同项目的 session 会自然
分离，不需要全局 workspace 状态。

## clangd 与 pyright 行为

这个改动是后端无关的。

`clangd` 仍使用已有 root markers：

- `compile_commands.json`
- `compile_flags.txt`
- `.clangd`
- `.git` 或 `.repo`

`pyright` 仍使用已有 root markers：

- `pyrightconfig.json`
- `pyproject.toml`
- `setup.py`
- `setup.cfg`
- `requirements.txt`
- `Pipfile`
- `poetry.lock`
- `.git` 或 `.repo`

`root_hint` 只提供调用上下文和 marker 缺失时的 fallback，不覆盖更具体的
marker root。这样不会削弱 clangd 对 `compile_commands.json` 的优先级。

## 错误处理

- `root_hint` 不存在时，返回明确错误。
- 相对 `file` 加 `root_hint` 后解析出的文件不存在时，返回 `FileNotFoundError`。
- 文件后缀没有后端匹配时，继续返回 `unsupported file extension`。
- 多后端匹配和 `workspace_symbols` 的歧义处理不变。

## 测试计划

- `ToolHandlers` 测试：相对 `file` 加目录 `root_hint` 时从该目录解析。
- `ToolHandlers` 测试：绝对 `file` 加 `root_hint` 时文件路径不被改写。
- `ToolHandlers` 测试：传错 `root_hint` 导致文件不存在时不回退。
- `SessionManager` 测试：无 marker 时 session root 回退到传入 `root_hint`。
- `SessionManager` 测试：有 marker 时 marker root 优先于 `root_hint`。
- `SessionManager` 测试：clangd 和 pyright 使用各自 markers，互不影响。
- 回归测试：未传 `root_hint` 的现有行为和测试保持通过。

## 成功标准

- 文件类工具可以通过显式 `root_hint` 在任意项目目录上稳定工作。
- MCP 进程 cwd 或安装路径不再影响带 `root_hint` 的相对路径调用。
- `clangd` 和 `pyright` 的 root discovery 行为保持各自语义。
- 现有测试和新增测试通过。
