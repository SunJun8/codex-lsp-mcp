import asyncio
import json

import pytest

from codex_lsp_mcp.lsp import LspClient, LspConnectionError, LspProtocolError, encode_message, read_message


class MemoryWriter:
    def __init__(self) -> None:
        self.data = bytearray()
        self.drain_count = 0
        self.closed = False

    def write(self, data: bytes) -> None:
        self.data.extend(data)

    async def drain(self) -> None:
        self.drain_count += 1

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        pass


class BlockedDrainWriter(MemoryWriter):
    def __init__(self) -> None:
        super().__init__()
        self.first_drain_started = asyncio.Event()
        self.release_first_drain = asyncio.Event()

    async def drain(self) -> None:
        self.drain_count += 1
        if self.drain_count == 1:
            self.first_drain_started.set()
            await self.release_first_drain.wait()


def feed_message(reader: asyncio.StreamReader, message: dict) -> None:
    reader.feed_data(encode_message(message))


async def read_written_message(writer: MemoryWriter) -> dict:
    reader = asyncio.StreamReader()
    reader.feed_data(bytes(writer.data))
    reader.feed_eof()
    return await read_message(reader)


async def read_written_messages(writer: MemoryWriter) -> list[dict]:
    reader = asyncio.StreamReader()
    reader.feed_data(bytes(writer.data))
    reader.feed_eof()
    messages = []
    while not reader.at_eof():
        messages.append(await read_message(reader))
    return messages


def test_encode_message_uses_content_length_header():
    encoded = encode_message({"jsonrpc": "2.0", "id": 1, "method": "ping"})

    header, body = encoded.split(b"\r\n\r\n", 1)
    assert header.startswith(b"Content-Length: ")
    assert json.loads(body.decode("utf-8"))["method"] == "ping"


@pytest.mark.asyncio
async def test_read_message_decodes_content_length_frame():
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "result": 7}).encode("utf-8")
    data = f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()

    message = await read_message(reader)

    assert message == {"jsonrpc": "2.0", "id": 1, "result": 7}


@pytest.mark.asyncio
async def test_read_message_rejects_negative_content_length():
    reader = asyncio.StreamReader()
    reader.feed_data(b"Content-Length: -1\r\n\r\n")
    reader.feed_eof()

    with pytest.raises(LspProtocolError, match="invalid Content-Length"):
        await read_message(reader)


@pytest.mark.asyncio
async def test_lsp_client_matches_response_to_pending_request():
    reader = asyncio.StreamReader()
    writer = MemoryWriter()
    client = LspClient(reader, writer)
    client.start()

    request_task = asyncio.create_task(client.request("workspace/symbol", {"query": "main"}))
    await asyncio.sleep(0)
    feed_message(reader, {"jsonrpc": "2.0", "id": 1, "result": ["main"]})

    assert await request_task == ["main"]
    assert writer.drain_count == 1

    await client.stop()


@pytest.mark.asyncio
async def test_lsp_client_queues_notifications():
    reader = asyncio.StreamReader()
    writer = MemoryWriter()
    client = LspClient(reader, writer)
    client.start()

    feed_message(reader, {"jsonrpc": "2.0", "method": "window/logMessage", "params": {"message": "hi"}})

    assert await client.next_notification() == {
        "jsonrpc": "2.0",
        "method": "window/logMessage",
        "params": {"message": "hi"},
    }

    await client.stop()


@pytest.mark.asyncio
async def test_lsp_client_notify_awaits_writer_drain():
    reader = asyncio.StreamReader()
    writer = MemoryWriter()
    client = LspClient(reader, writer)

    await client.notify("initialized", {})

    assert writer.drain_count == 1
    assert await read_written_message(writer) == {"jsonrpc": "2.0", "method": "initialized", "params": {}}


@pytest.mark.asyncio
async def test_lsp_client_raises_json_rpc_error_response():
    reader = asyncio.StreamReader()
    writer = MemoryWriter()
    client = LspClient(reader, writer)
    client.start()

    request_task = asyncio.create_task(client.request("textDocument/definition"))
    await asyncio.sleep(0)
    feed_message(reader, {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "failed"}})

    with pytest.raises(RuntimeError, match="failed"):
        await request_task

    await client.stop()


@pytest.mark.asyncio
async def test_lsp_client_fails_pending_request_on_eof():
    reader = asyncio.StreamReader()
    writer = MemoryWriter()
    client = LspClient(reader, writer)
    client.start()

    request_task = asyncio.create_task(client.request("initialize"))
    await asyncio.sleep(0)
    reader.feed_eof()

    with pytest.raises(LspConnectionError, match="connection closed"):
        await request_task

    await client.stop()


@pytest.mark.asyncio
async def test_lsp_client_request_fails_after_idle_read_loop_eof():
    reader = asyncio.StreamReader()
    writer = MemoryWriter()
    client = LspClient(reader, writer)
    client.start()

    reader.feed_eof()
    await asyncio.sleep(0)

    with pytest.raises(LspConnectionError, match="connection closed"):
        await asyncio.wait_for(client.request("initialize"), timeout=0.1)
    with pytest.raises(LspConnectionError, match="connection closed"):
        await client.notify("initialized")

    await client.stop()


@pytest.mark.asyncio
async def test_lsp_client_wakes_waiting_notification_on_eof():
    reader = asyncio.StreamReader()
    writer = MemoryWriter()
    client = LspClient(reader, writer)
    client.start()

    notification_task = asyncio.create_task(client.next_notification())
    await asyncio.sleep(0)
    reader.feed_eof()

    with pytest.raises(LspConnectionError, match="connection closed"):
        await asyncio.wait_for(notification_task, timeout=0.1)

    await client.stop()


@pytest.mark.asyncio
async def test_lsp_client_stop_fails_pending_request():
    reader = asyncio.StreamReader()
    writer = MemoryWriter()
    client = LspClient(reader, writer)
    client.start()

    request_task = asyncio.create_task(client.request("initialize"))
    await asyncio.sleep(0)
    await client.stop()

    with pytest.raises(LspConnectionError, match="stopped"):
        await request_task


@pytest.mark.asyncio
async def test_lsp_client_request_and_notify_fail_after_stop():
    reader = asyncio.StreamReader()
    writer = MemoryWriter()
    client = LspClient(reader, writer)
    client.start()

    await client.stop()

    with pytest.raises(LspConnectionError, match="stopped"):
        await asyncio.wait_for(client.request("initialize"), timeout=0.1)
    with pytest.raises(LspConnectionError, match="stopped"):
        await client.notify("initialized")
    assert not client._pending


@pytest.mark.asyncio
async def test_lsp_client_next_notification_fails_after_stop():
    reader = asyncio.StreamReader()
    writer = MemoryWriter()
    client = LspClient(reader, writer)
    client.start()

    await client.stop()

    with pytest.raises(LspConnectionError, match="stopped"):
        await asyncio.wait_for(client.next_notification(), timeout=0.1)


@pytest.mark.asyncio
async def test_lsp_client_fails_pending_request_on_malformed_header():
    reader = asyncio.StreamReader()
    writer = MemoryWriter()
    client = LspClient(reader, writer)
    client.start()

    request_task = asyncio.create_task(client.request("initialize"))
    await asyncio.sleep(0)
    reader.feed_data(b"Broken-Header\r\n\r\n")

    with pytest.raises(LspProtocolError, match="malformed header"):
        await request_task

    await client.stop()


@pytest.mark.asyncio
async def test_lsp_client_replies_method_not_found_to_unknown_server_request():
    reader = asyncio.StreamReader()
    writer = MemoryWriter()
    client = LspClient(reader, writer)
    client.start()

    feed_message(reader, {"jsonrpc": "2.0", "id": 99, "method": "workspace/configuration", "params": {}})
    await asyncio.sleep(0)

    response = await read_written_message(writer)
    assert response == {
        "jsonrpc": "2.0",
        "id": 99,
        "error": {"code": -32601, "message": "Method not found"},
    }
    assert writer.drain_count == 1

    await client.stop()


@pytest.mark.asyncio
async def test_lsp_client_replies_to_registered_server_request():
    reader = asyncio.StreamReader()
    writer = MemoryWriter()
    client = LspClient(reader, writer)
    client.set_request_handler("window/workDoneProgress/create", lambda _params: None)
    client.start()

    feed_message(
        reader,
        {
            "jsonrpc": "2.0",
            "id": 99,
            "method": "window/workDoneProgress/create",
            "params": {"token": "backgroundIndexProgress"},
        },
    )
    await asyncio.sleep(0)

    response = await read_written_message(writer)
    assert response == {"jsonrpc": "2.0", "id": 99, "result": None}

    await client.stop()


@pytest.mark.asyncio
async def test_lsp_client_replies_method_not_found_when_server_request_id_collides():
    reader = asyncio.StreamReader()
    writer = MemoryWriter()
    client = LspClient(reader, writer)
    client.start()

    request_task = asyncio.create_task(client.request("initialize"))
    await asyncio.sleep(0)
    feed_message(reader, {"jsonrpc": "2.0", "id": 1, "method": "workspace/configuration", "params": {}})
    await asyncio.sleep(0)

    assert not request_task.done()
    written_messages = await read_written_messages(writer)
    assert written_messages[1] == {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32601, "message": "Method not found"},
    }

    feed_message(reader, {"jsonrpc": "2.0", "id": 1, "result": {"capabilities": {}}})
    assert await request_task == {"capabilities": {}}

    await client.stop()


@pytest.mark.asyncio
async def test_lsp_client_drops_late_response_for_cancelled_request():
    reader = asyncio.StreamReader()
    writer = MemoryWriter()
    client = LspClient(reader, writer)
    client.start()

    request_task = asyncio.create_task(client.request("cancel/me"))
    await asyncio.sleep(0)
    request_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request_task

    feed_message(reader, {"jsonrpc": "2.0", "id": 1, "result": None})
    await asyncio.sleep(0)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(client.next_notification(), timeout=0.01)

    await client.stop()


@pytest.mark.asyncio
async def test_lsp_client_sends_cancel_request_when_request_is_cancelled():
    reader = asyncio.StreamReader()
    writer = MemoryWriter()
    client = LspClient(reader, writer)
    client.start()

    request_task = asyncio.create_task(client.request("cancel/me"))
    await asyncio.sleep(0)
    request_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request_task

    written_messages = await read_written_messages(writer)
    assert written_messages[1] == {
        "jsonrpc": "2.0",
        "method": "$/cancelRequest",
        "params": {"id": 1},
    }

    await client.stop()


@pytest.mark.asyncio
async def test_lsp_client_sends_cancel_request_when_cancelled_during_initial_drain():
    reader = asyncio.StreamReader()
    writer = BlockedDrainWriter()
    client = LspClient(reader, writer)
    client.start()

    request_task = asyncio.create_task(client.request("cancel/me"))
    await writer.first_drain_started.wait()
    request_task.cancel()
    writer.release_first_drain.set()
    with pytest.raises(asyncio.CancelledError):
        await request_task

    written_messages = await read_written_messages(writer)
    assert written_messages[1] == {
        "jsonrpc": "2.0",
        "method": "$/cancelRequest",
        "params": {"id": 1},
    }
    assert not client._pending

    await client.stop()


@pytest.mark.asyncio
async def test_lsp_client_removes_cancelled_pending_request():
    reader = asyncio.StreamReader()
    writer = MemoryWriter()
    client = LspClient(reader, writer)
    client.start()

    request_task = asyncio.create_task(client.request("cancel/me"))
    await asyncio.sleep(0)
    request_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request_task

    assert not client._pending
    feed_message(reader, {"jsonrpc": "2.0", "id": 1, "result": None})
    await asyncio.sleep(0)
    assert client._reader_task is not None
    assert not client._reader_task.done()

    await client.stop()
