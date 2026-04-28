from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Callable
from typing import Any


JsonObject = dict[str, Any]
ServerRequestHandler = Callable[[JsonObject], Any]


class LspConnectionError(ConnectionError):
    pass


class LspProtocolError(RuntimeError):
    pass


def encode_message(message: JsonObject) -> bytes:
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


async def read_message(reader: asyncio.StreamReader) -> JsonObject:
    headers: dict[str, str] = {}
    while True:
        line = await reader.readline()
        if line == b"":
            raise LspConnectionError("connection closed while reading headers")
        if line in (b"\r\n", b"\n"):
            break
        if b":" not in line:
            raise LspProtocolError(f"malformed header: {line.decode('ascii', errors='replace').strip()}")
        key, value = line.decode("ascii").split(":", 1)
        headers[key.lower()] = value.strip()

    if "content-length" not in headers:
        raise LspProtocolError("missing Content-Length header")
    try:
        length = int(headers["content-length"])
    except ValueError as exc:
        raise LspProtocolError("invalid Content-Length header") from exc
    if length < 0:
        raise LspProtocolError("invalid Content-Length header")

    try:
        body = await reader.readexactly(length)
    except asyncio.IncompleteReadError as exc:
        raise LspConnectionError("connection closed while reading body") from exc

    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise LspProtocolError("invalid JSON-RPC message body") from exc


class LspClient:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader = reader
        self._writer = writer
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[JsonObject]] = {}
        self._request_handlers: dict[str, ServerRequestHandler] = {}
        self._notifications: asyncio.Queue[JsonObject] = asyncio.Queue()
        self._notification_waiters: set[asyncio.Future[JsonObject]] = set()
        self._reader_task: asyncio.Task[None] | None = None
        self._closed_error: Exception | None = None

    def start(self) -> None:
        self._reader_task = asyncio.create_task(self._read_loop())

    def set_request_handler(self, method: str, handler: ServerRequestHandler) -> None:
        self._request_handlers[method] = handler

    async def stop(self) -> None:
        self._closed_error = LspConnectionError("LSP client stopped")
        self._fail_pending(self._closed_error)
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        self._writer.close()
        await self._writer.wait_closed()

    async def request(self, method: str, params: JsonObject | None = None) -> Any:
        self._raise_if_closed()
        request_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[JsonObject] = loop.create_future()
        self._pending[request_id] = future
        try:
            await self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
            response = await future
            if "error" in response:
                raise RuntimeError(response["error"])
            return response.get("result")
        except asyncio.CancelledError:
            self._pending.pop(request_id, None)
            if self._closed_error is None:
                await self._write_unchecked({"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": request_id}})
            raise
        finally:
            self._pending.pop(request_id, None)

    async def notify(self, method: str, params: JsonObject | None = None) -> None:
        self._raise_if_closed()
        await self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    async def next_notification(self) -> JsonObject:
        self._raise_if_closed()
        if not self._notifications.empty():
            return await self._notifications.get()

        loop = asyncio.get_running_loop()
        future: asyncio.Future[JsonObject] = loop.create_future()
        self._notification_waiters.add(future)
        try:
            return await future
        finally:
            self._notification_waiters.discard(future)

    async def _write(self, message: JsonObject) -> None:
        self._raise_if_closed()
        await self._write_unchecked(message)

    async def _write_unchecked(self, message: JsonObject) -> None:
        self._writer.write(encode_message(message))
        await self._writer.drain()

    async def _read_loop(self) -> None:
        try:
            while True:
                message = await read_message(self._reader)
                await self._handle_message(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._closed_error = exc
            self._fail_pending(exc)

    async def _handle_message(self, message: JsonObject) -> None:
        message_id = message.get("id")
        if "id" in message and "method" in message:
            await self._handle_server_request(message_id, message)
        elif isinstance(message_id, int) and message_id in self._pending:
            future = self._pending.pop(message_id)
            if not future.done():
                future.set_result(message)
        elif "id" in message:
            return
        else:
            self._put_notification(message)

    async def _handle_server_request(self, message_id: Any, message: JsonObject) -> None:
        method = message.get("method")
        handler = self._request_handlers.get(method)
        if handler is None:
            await self._write(
                {
                    "jsonrpc": "2.0",
                    "id": message_id,
                    "error": {"code": -32601, "message": "Method not found"},
                }
            )
            return

        try:
            result = handler(message.get("params", {}))
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            await self._write(
                {
                    "jsonrpc": "2.0",
                    "id": message_id,
                    "error": {"code": -32000, "message": str(exc)},
                }
            )
            return

        await self._write({"jsonrpc": "2.0", "id": message_id, "result": result})

    def _raise_if_closed(self) -> None:
        if self._closed_error is not None:
            raise self._closed_error

    def _fail_pending(self, exc: Exception) -> None:
        pending = list(self._pending.values())
        self._pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(exc)
        self._fail_notification_waiters(exc)

    def _put_notification(self, message: JsonObject) -> None:
        for future in list(self._notification_waiters):
            self._notification_waiters.discard(future)
            if not future.done():
                future.set_result(message)
                return
        self._notifications.put_nowait(message)

    def _fail_notification_waiters(self, exc: Exception) -> None:
        waiters = list(self._notification_waiters)
        self._notification_waiters.clear()
        for future in waiters:
            if not future.done():
                future.set_exception(exc)
