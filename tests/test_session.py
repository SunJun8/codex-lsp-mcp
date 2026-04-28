import asyncio
import pytest

from codex_lsp_mcp.config import ServerConfig
from codex_lsp_mcp.session import ClangdSession


RANGE = {
    "start": {"line": 0, "character": 0},
    "end": {"line": 0, "character": 3},
}


class FakeProcess:
    def __init__(self):
        self.stdin = object()
        self.stdout = object()
        self.returncode = None
        self.terminated = False
        self.killed = False

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def kill(self):
        self.killed = True
        self.returncode = -9

    async def wait(self):
        return self.returncode


class FakeClient:
    instances = []
    initialize_delay = 0
    fail_initialize = False
    notify_delay = 0
    request_results = {}
    notifications = []

    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.started = False
        self.stopped = False
        self.requests = []
        self.notifies = []
        self.request_handlers = {}
        FakeClient.instances.append(self)

    def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def request(self, method, params=None):
        self.requests.append((method, params or {}))
        if method == "initialize" and FakeClient.fail_initialize:
            raise RuntimeError("initialize failed")
        if method == "initialize" and FakeClient.initialize_delay:
            await asyncio.sleep(FakeClient.initialize_delay)
        result = FakeClient.request_results.get(method)
        if callable(result):
            return result(self, method, params or {})
        if hasattr(result, "__next__"):
            return next(result)
        return result

    async def notify(self, method, params=None):
        if FakeClient.notify_delay:
            await asyncio.sleep(FakeClient.notify_delay)
        self.notifies.append((method, params or {}))

    def set_request_handler(self, method, handler):
        self.request_handlers[method] = handler

    async def next_notification(self):
        while not FakeClient.notifications:
            await asyncio.sleep(0.001)
        item = FakeClient.notifications.pop(0)
        if "_raise" in item:
            raise item["_raise"]
        delay = item.get("_delay", 0)
        if delay:
            await asyncio.sleep(delay)
        return item


@pytest.fixture(autouse=True)
def reset_fakes(monkeypatch):
    FakeClient.instances = []
    FakeClient.initialize_delay = 0
    FakeClient.fail_initialize = False
    FakeClient.notify_delay = 0
    FakeClient.request_results = {}
    FakeClient.notifications = []
    processes = []

    async def create_process(*args, **kwargs):
        process = FakeProcess()
        processes.append(process)
        return process

    monkeypatch.setattr("codex_lsp_mcp.session.LspClient", FakeClient)
    monkeypatch.setattr("codex_lsp_mcp.session.asyncio.create_subprocess_exec", create_process)
    return processes


@pytest.fixture
def server_config():
    return ServerConfig(
        command="clangd",
        args=["--background-index"],
        extension_to_language={".c": "c"},
    )


@pytest.mark.asyncio
async def test_definition_uses_planned_signature_returns_items_and_sends_did_open(
    tmp_path,
    server_config,
):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    FakeClient.request_results["textDocument/definition"] = [
        {"uri": source.as_uri(), "range": RANGE}
    ]
    session = ClangdSession(tmp_path, server_config)

    result = await session.definition(source, "c", 0, 4)

    client = FakeClient.instances[0]
    assert client.requests[0][0] == "initialize"
    assert (
        "textDocument/didOpen",
        {
            "textDocument": {
                "uri": source.as_uri(),
                "languageId": "c",
                "version": 1,
                "text": "int main(void) { return 0; }\n",
            }
        },
    ) in client.notifies
    assert (
        "textDocument/definition",
        {
            "textDocument": {"uri": source.as_uri()},
            "position": {"line": 0, "character": 4},
        },
    ) in client.requests
    assert result == {
        "items": [
            {
                "file": str(source),
                "line": 0,
                "character": 0,
                "end_line": 0,
                "end_character": 3,
                "preview": "int main(void) { return 0; }",
            }
        ]
    }


@pytest.mark.asyncio
async def test_start_wraps_missing_clangd_with_actionable_error(
    monkeypatch,
    tmp_path,
    server_config,
):
    async def create_process(*args, **kwargs):
        raise FileNotFoundError("clangd")

    monkeypatch.setattr("codex_lsp_mcp.session.asyncio.create_subprocess_exec", create_process)
    session = ClangdSession(tmp_path, server_config)

    with pytest.raises(RuntimeError, match="install clangd or set CLANGD_BIN"):
        await session.start()


@pytest.mark.asyncio
async def test_workspace_symbols_auto_starts_and_returns_items(tmp_path, server_config):
    FakeClient.request_results["workspace/symbol"] = [
        {
            "name": "main",
            "kind": 12,
            "location": {"uri": (tmp_path / "main.c").as_uri(), "range": RANGE},
        }
    ]
    session = ClangdSession(tmp_path, server_config)

    result = await session.workspace_symbols("main")

    assert FakeClient.instances[0].requests[0][0] == "initialize"
    assert result["items"][0]["name"] == "main"


@pytest.mark.asyncio
async def test_workspace_symbols_retries_after_background_index_wait_times_out(
    tmp_path,
    server_config,
    monkeypatch,
):
    FakeClient.request_results["workspace/symbol"] = iter(
        [
            [],
            [
                {
                    "name": "main",
                    "kind": 12,
                    "location": {"uri": (tmp_path / "main.c").as_uri(), "range": RANGE},
                }
            ],
        ]
    )
    monkeypatch.setattr("codex_lsp_mcp.session.WORKSPACE_SYMBOL_INDEX_IDLE_TIMEOUT", 0)
    session = ClangdSession(tmp_path, server_config)

    result = await session.workspace_symbols("main")

    client = FakeClient.instances[0]
    workspace_requests = [
        request for request in client.requests if request[0] == "workspace/symbol"
    ]
    assert len(workspace_requests) == 2
    assert result["items"][0]["name"] == "main"


@pytest.mark.asyncio
async def test_workspace_symbols_waits_for_background_index_end_after_empty_cold_result(
    tmp_path,
    server_config,
    monkeypatch,
):
    source = tmp_path / "main.c"
    FakeClient.notifications = [
        {
            "_delay": 0.01,
            "jsonrpc": "2.0",
            "method": "$/progress",
            "params": {
                "token": "backgroundIndexProgress",
                "value": {"kind": "end"},
            },
        }
    ]
    FakeClient.request_results["workspace/symbol"] = iter(
        [
            [],
            [
                {
                    "name": "main",
                    "kind": 12,
                    "location": {"uri": source.as_uri(), "range": RANGE},
                }
            ],
        ]
    )
    session = ClangdSession(tmp_path, server_config)

    result = await session.workspace_symbols("main")

    client = FakeClient.instances[0]
    workspace_requests = [
        request for request in client.requests if request[0] == "workspace/symbol"
    ]
    assert len(workspace_requests) == 2
    assert result["items"][0]["name"] == "main"
    assert "window/workDoneProgress/create" in client.request_handlers


@pytest.mark.asyncio
async def test_workspace_symbols_does_not_open_compile_database_candidates(
    tmp_path,
    server_config,
    monkeypatch,
):
    source = tmp_path / "main.c"
    source.write_text("void main(void) {}\n", encoding="utf-8")
    (tmp_path / "compile_commands.json").write_text("[]\n", encoding="utf-8")
    FakeClient.request_results["workspace/symbol"] = []
    monkeypatch.setattr("codex_lsp_mcp.session.WORKSPACE_SYMBOL_INDEX_IDLE_TIMEOUT", 0)
    session = ClangdSession(tmp_path, server_config)

    result = await session.workspace_symbols("main")

    assert result == {"items": []}
    assert [method for method, _params in FakeClient.instances[0].notifies] == [
        "initialized"
    ]


@pytest.mark.asyncio
async def test_concurrent_start_initializes_once(tmp_path, server_config, reset_fakes):
    FakeClient.initialize_delay = 0.01
    session = ClangdSession(tmp_path, server_config)

    await asyncio.gather(session.start(), session.start())

    assert len(reset_fakes) == 1
    assert len(FakeClient.instances) == 1
    assert [method for method, _ in FakeClient.instances[0].requests] == ["initialize"]


@pytest.mark.asyncio
async def test_failed_start_cleans_up_and_can_retry(tmp_path, server_config, reset_fakes):
    session = ClangdSession(tmp_path, server_config)
    FakeClient.fail_initialize = True

    with pytest.raises(RuntimeError, match="initialize failed"):
        await session.start()

    assert session.client is None
    assert session.process is None
    assert reset_fakes[0].terminated
    assert FakeClient.instances[0].stopped

    FakeClient.fail_initialize = False
    await session.start()

    assert len(reset_fakes) == 2
    assert len(FakeClient.instances) == 2
    assert FakeClient.instances[1].started


@pytest.mark.asyncio
async def test_stop_clears_open_files_so_later_ensure_sends_did_open(tmp_path, server_config):
    source = tmp_path / "main.c"
    source.write_text("int first;\n", encoding="utf-8")
    session = ClangdSession(tmp_path, server_config)

    await session.ensure_file_open(source, "c")
    await session.stop()
    source.write_text("int second;\n", encoding="utf-8")
    await session.ensure_file_open(source, "c")

    assert len(FakeClient.instances) == 2
    first_client, second_client = FakeClient.instances
    assert [method for method, _ in first_client.notifies].count("textDocument/didOpen") == 1
    assert [method for method, _ in second_client.notifies] == [
        "initialized",
        "textDocument/didOpen",
    ]


@pytest.mark.asyncio
async def test_diagnostics_waits_for_notification_and_returns_items(tmp_path, server_config):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return missing; }\n", encoding="utf-8")
    FakeClient.notifications = [
        {
            "_delay": 0.01,
            "jsonrpc": "2.0",
            "method": "textDocument/publishDiagnostics",
            "params": {
                "uri": source.as_uri(),
                "diagnostics": [
                    {
                        "severity": 1,
                        "message": "use of undeclared identifier",
                        "source": "clang",
                        "range": RANGE,
                    }
                ],
            },
        }
    ]
    session = ClangdSession(tmp_path, server_config)

    result = await session.diagnostics(source, "c")

    assert result == {
        "items": [
            {
                "severity": 1,
                "message": "use of undeclared identifier",
                "source": "clang",
                "range": {"line": 0, "character": 0, "end_line": 0, "end_character": 3},
            }
        ]
    }


@pytest.mark.asyncio
async def test_diagnostics_waits_for_fresh_publish_after_did_change(tmp_path, server_config):
    source = tmp_path / "main.c"
    source.write_text("int old;\n", encoding="utf-8")
    FakeClient.notifications = [
        {
            "jsonrpc": "2.0",
            "method": "textDocument/publishDiagnostics",
            "params": {
                "uri": source.as_uri(),
                "diagnostics": [{"severity": 1, "message": "old", "range": RANGE}],
            },
        }
    ]
    session = ClangdSession(tmp_path, server_config)

    assert (await session.diagnostics(source, "c"))["items"][0]["message"] == "old"

    source.write_text("int fresh;\n", encoding="utf-8")
    FakeClient.notifications = [
        {
            "_delay": 0.01,
            "jsonrpc": "2.0",
            "method": "textDocument/publishDiagnostics",
            "params": {
                "uri": source.as_uri(),
                "diagnostics": [{"severity": 1, "message": "fresh", "range": RANGE}],
            },
        }
    ]

    assert (await session.diagnostics(source, "c"))["items"][0]["message"] == "fresh"


@pytest.mark.asyncio
async def test_concurrent_ensure_file_open_sends_one_did_open(tmp_path, server_config):
    source = tmp_path / "main.c"
    source.write_text("int value;\n", encoding="utf-8")
    FakeClient.notify_delay = 0.01
    session = ClangdSession(tmp_path, server_config)

    await asyncio.gather(
        session.ensure_file_open(source, "c"),
        session.ensure_file_open(source, "c"),
    )

    did_open_count = [
        method for method, _ in FakeClient.instances[0].notifies
    ].count("textDocument/didOpen")
    assert did_open_count == 1


@pytest.mark.asyncio
async def test_notification_error_marks_session_retryable(tmp_path, server_config):
    FakeClient.notifications = [{"_raise": RuntimeError("connection closed")}]
    FakeClient.request_results["workspace/symbol"] = []
    session = ClangdSession(tmp_path, server_config)

    await session.start()
    await asyncio.sleep(0)

    assert not session._started

    result = await session.workspace_symbols("main")

    assert len(FakeClient.instances) == 2
    assert result == {"items": []}


@pytest.mark.asyncio
async def test_document_symbols_includes_nested_children(tmp_path, server_config):
    source = tmp_path / "main.c"
    source.write_text("int inner;\n", encoding="utf-8")
    FakeClient.request_results["textDocument/documentSymbol"] = [
        {
            "name": "outer",
            "kind": 12,
            "range": RANGE,
            "selectionRange": RANGE,
            "children": [
                {
                    "name": "inner",
                    "kind": 13,
                    "range": RANGE,
                    "selectionRange": RANGE,
                }
            ],
        }
    ]
    session = ClangdSession(tmp_path, server_config)

    result = await session.document_symbols(source, "c")

    assert [item["name"] for item in result["items"]] == ["outer", "inner"]
