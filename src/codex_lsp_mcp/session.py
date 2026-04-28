from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .config import ServerConfig
from .lsp import LspClient
from .preview import lsp_range_to_user_range, make_position, read_preview


JsonObject = dict[str, Any]


@dataclass
class OpenFile:
    version: int
    mtime_ns: int
    size: int


BACKGROUND_INDEX_PROGRESS_TOKEN = "backgroundIndexProgress"
WORKSPACE_SYMBOL_INDEX_IDLE_TIMEOUT = 2.0


class ClangdSession:
    def __init__(self, root: Path, server_config: ServerConfig) -> None:
        self.root = Path(root).expanduser().resolve()
        self.server_config = server_config
        self.process: asyncio.subprocess.Process | None = None
        self.client: LspClient | None = None
        self.open_files: dict[Path, OpenFile] = {}
        self.diagnostics_by_uri: dict[str, list[JsonObject]] = {}
        self._diagnostic_events: dict[str, asyncio.Event] = {}
        self._file_locks: dict[Path, asyncio.Lock] = {}
        self._background_index_idle = asyncio.Event()
        self._notification_task: asyncio.Task[None] | None = None
        self._started = False
        self._start_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._started:
            return

        async with self._start_lock:
            if self._started:
                return

            try:
                try:
                    self.process = await asyncio.create_subprocess_exec(
                        self.server_config.command,
                        *self.server_config.args,
                        cwd=self.root,
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                except FileNotFoundError as exc:
                    raise RuntimeError(
                        f"clangd not found: install clangd or set CLANGD_BIN "
                        f"to the clangd executable path (current command: "
                        f"{self.server_config.command})"
                    ) from exc
                if self.process.stdout is None or self.process.stdin is None:
                    raise RuntimeError("failed to open clangd stdio pipes")

                self._background_index_idle.clear()
                self.client = LspClient(self.process.stdout, self.process.stdin)
                self.client.set_request_handler(
                    "window/workDoneProgress/create",
                    self._handle_work_done_progress_create,
                )
                self.client.start()
                await self.client.request(
                    "initialize",
                    {
                        "processId": None,
                        "rootUri": self.root.as_uri(),
                        "capabilities": {"window": {"workDoneProgress": True}},
                    },
                )
                await self.client.notify("initialized", {})
                self._started = True
                self._notification_task = asyncio.create_task(self._consume_notifications())
            except Exception:
                await self._cleanup_started_resources(clear_caches=True)
                raise

    async def stop(self) -> None:
        async with self._start_lock:
            await self._cleanup_started_resources(clear_caches=True)

    async def _cleanup_started_resources(
        self,
        clear_caches: bool,
        cancel_notification_task: bool = True,
    ) -> None:
        self._started = False
        current_task = asyncio.current_task()
        if self._notification_task is not None:
            if cancel_notification_task and self._notification_task is not current_task:
                self._notification_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._notification_task
            self._notification_task = None

        if self.client is not None:
            with contextlib.suppress(Exception):
                await self.client.stop()
            self.client = None

        if self.process is not None:
            if self.process.returncode is None:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=2)
                except asyncio.TimeoutError:
                    self.process.kill()
                    await self.process.wait()
            self.process = None

        if clear_caches:
            self.open_files.clear()
            self.diagnostics_by_uri.clear()
            self._diagnostic_events.clear()
            self._file_locks.clear()
            self._background_index_idle.clear()

    async def ensure_file_open(self, path: str | Path, language_id: str) -> None:
        await self.start()
        file_path = Path(path).expanduser().resolve()
        lock = self._file_locks.setdefault(file_path, asyncio.Lock())
        async with lock:
            stat = file_path.stat()
            text = file_path.read_text(encoding="utf-8", errors="replace")
            uri = file_path.as_uri()
            client = self._require_client()
            open_file = self.open_files.get(file_path)

            if open_file is None:
                await client.notify(
                    "textDocument/didOpen",
                    {
                        "textDocument": {
                            "uri": uri,
                            "languageId": language_id,
                            "version": 1,
                            "text": text,
                        }
                    },
                )
                self.open_files[file_path] = OpenFile(
                    version=1,
                    mtime_ns=stat.st_mtime_ns,
                    size=stat.st_size,
                )
                return

            if open_file.mtime_ns == stat.st_mtime_ns and open_file.size == stat.st_size:
                return

            version = open_file.version + 1
            self.diagnostics_by_uri.pop(uri, None)
            self._diagnostic_events.setdefault(uri, asyncio.Event()).clear()
            await client.notify(
                "textDocument/didChange",
                {
                    "textDocument": {"uri": uri, "version": version},
                    "contentChanges": [{"text": text}],
                },
            )
            self.open_files[file_path] = OpenFile(
                version=version,
                mtime_ns=stat.st_mtime_ns,
                size=stat.st_size,
            )

    async def definition(
        self,
        path: str | Path,
        language_id: str,
        line: int,
        character: int,
    ) -> JsonObject:
        file_path = Path(path).expanduser().resolve()
        await self.ensure_file_open(file_path, language_id)
        result = await self._require_client().request(
            "textDocument/definition",
            self._text_document_position_params(file_path, line, character),
        )
        return {"items": self._locations_to_items(result)}

    async def references(
        self,
        path: str | Path,
        language_id: str,
        line: int,
        character: int,
        include_declaration: bool = False,
    ) -> JsonObject:
        file_path = Path(path).expanduser().resolve()
        await self.ensure_file_open(file_path, language_id)
        params = self._text_document_position_params(file_path, line, character)
        params["context"] = {"includeDeclaration": include_declaration}
        result = await self._require_client().request("textDocument/references", params)
        return {"items": self._locations_to_items(result)}

    async def hover(
        self,
        path: str | Path,
        language_id: str,
        line: int,
        character: int,
    ) -> JsonObject:
        file_path = Path(path).expanduser().resolve()
        await self.ensure_file_open(file_path, language_id)
        result = await self._require_client().request(
            "textDocument/hover",
            self._text_document_position_params(file_path, line, character),
        )
        if not result:
            return {"contents": ""}
        return {
            "contents": self._hover_contents_to_text(result.get("contents")),
            "range": self._range_to_user_range(result.get("range")),
        }

    async def diagnostics(self, path: str | Path, language_id: str) -> JsonObject:
        file_path = Path(path).expanduser().resolve()
        await self.ensure_file_open(file_path, language_id)
        uri = file_path.as_uri()
        if uri not in self.diagnostics_by_uri:
            event = self._diagnostic_events.setdefault(uri, asyncio.Event())
            event.clear()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(event.wait(), timeout=0.05)
        return {
            "items": [
                {
                    "severity": diagnostic.get("severity"),
                    "message": diagnostic.get("message", ""),
                    "source": diagnostic.get("source"),
                    "range": lsp_range_to_user_range(diagnostic["range"]),
                }
                for diagnostic in self.diagnostics_by_uri.get(uri, [])
            ]
        }

    async def document_symbols(self, path: str | Path, language_id: str) -> JsonObject:
        file_path = Path(path).expanduser().resolve()
        await self.ensure_file_open(file_path, language_id)
        result = await self._require_client().request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": file_path.as_uri()}},
        )
        return {"items": self._symbols_to_items(result)}

    async def workspace_symbols(self, query: str) -> JsonObject:
        was_started = self._started
        await self.start()
        items = await self._workspace_symbol_items(query)
        if items:
            return {"items": items}

        if was_started:
            return {"items": items}

        await self._wait_for_background_index_idle()
        items = await self._workspace_symbol_items(query)

        return {"items": items}

    async def _workspace_symbol_items(self, query: str) -> list[JsonObject]:
        result = await self._require_client().request("workspace/symbol", {"query": query})
        return self._symbols_to_items(result)

    async def _wait_for_background_index_idle(self) -> None:
        if self._background_index_idle.is_set():
            return
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(
                self._background_index_idle.wait(),
                timeout=WORKSPACE_SYMBOL_INDEX_IDLE_TIMEOUT,
            )

    def _handle_work_done_progress_create(self, _params: JsonObject) -> None:
        return None

    async def _consume_notifications(self) -> None:
        client = self._require_client()
        while True:
            try:
                notification = await client.next_notification()
            except asyncio.CancelledError:
                raise
            except Exception:
                await self._cleanup_started_resources(
                    clear_caches=True,
                    cancel_notification_task=False,
                )
                return

            if notification.get("method") == "textDocument/publishDiagnostics":
                params = notification.get("params", {})
                uri = params.get("uri")
                diagnostics = params.get("diagnostics", [])
                if isinstance(uri, str) and isinstance(diagnostics, list):
                    self.diagnostics_by_uri[uri] = diagnostics
                    self._diagnostic_events.setdefault(uri, asyncio.Event()).set()
            elif notification.get("method") == "$/progress":
                self._handle_progress_notification(notification.get("params", {}))

    def _handle_progress_notification(self, params: Any) -> None:
        if not isinstance(params, dict):
            return
        if params.get("token") != BACKGROUND_INDEX_PROGRESS_TOKEN:
            return
        value = params.get("value")
        if not isinstance(value, dict):
            return

        kind = value.get("kind")
        if kind == "end":
            self._background_index_idle.set()
        elif kind in {"begin", "report"}:
            self._background_index_idle.clear()

    def _require_client(self) -> LspClient:
        if self.client is None:
            raise RuntimeError("clangd session has not been started")
        return self.client

    def _text_document_position_params(
        self,
        path: Path,
        line: int,
        character: int,
    ) -> JsonObject:
        return {
            "textDocument": {"uri": path.as_uri()},
            "position": make_position(line, character),
        }

    def _locations_to_items(self, result: Any) -> list[JsonObject]:
        if result is None:
            return []
        locations = result if isinstance(result, list) else [result]
        items: list[JsonObject] = []

        for location in locations:
            if not isinstance(location, dict):
                continue
            uri = location.get("uri") or location.get("targetUri")
            lsp_range = location.get("range") or location.get("targetSelectionRange")
            if not isinstance(uri, str) or not isinstance(lsp_range, dict):
                continue
            path = self._path_from_file_uri(uri)
            user_range = lsp_range_to_user_range(lsp_range)
            items.append(
                {
                    "file": str(path),
                    "line": user_range["line"],
                    "character": user_range["character"],
                    "end_line": user_range["end_line"],
                    "end_character": user_range["end_character"],
                    "preview": read_preview(path, user_range["line"] + 1),
                }
            )

        return items

    def _symbols_to_items(self, result: Any) -> list[JsonObject]:
        if not isinstance(result, list):
            return []

        items: list[JsonObject] = []
        for symbol in result:
            self._add_symbol_item(symbol, items)

        return items

    def _add_symbol_item(self, symbol: Any, items: list[JsonObject]) -> None:
        if not isinstance(symbol, dict):
            return
        if "location" in symbol:
            location = symbol.get("location", {})
            uri = location.get("uri")
            lsp_range = location.get("range")
        else:
            uri = None
            lsp_range = symbol.get("selectionRange") or symbol.get("range")

        item: JsonObject = {
            "name": symbol.get("name", ""),
            "kind": symbol.get("kind"),
            "container": symbol.get("containerName"),
        }
        if isinstance(uri, str) and isinstance(lsp_range, dict):
            path = self._path_from_file_uri(uri)
            user_range = lsp_range_to_user_range(lsp_range)
            item.update(
                {
                    "path": str(path),
                    "range": user_range,
                    "preview": read_preview(path, user_range["line"] + 1),
                }
            )
        elif isinstance(lsp_range, dict):
            item["range"] = lsp_range_to_user_range(lsp_range)
        items.append(item)

        for child in symbol.get("children", []):
            self._add_symbol_item(child, items)

    def _path_from_file_uri(self, uri: str) -> Path:
        parsed = urlparse(uri)
        if parsed.scheme != "file":
            raise ValueError(f"unsupported URI scheme: {parsed.scheme}")
        return Path(unquote(parsed.path))

    def _range_to_user_range(self, value: Any) -> JsonObject | None:
        if not isinstance(value, dict):
            return None
        return lsp_range_to_user_range(value)

    def _hover_contents_to_text(self, contents: Any) -> str:
        if isinstance(contents, str):
            return contents
        if isinstance(contents, dict):
            value = contents.get("value")
            return value if isinstance(value, str) else ""
        if isinstance(contents, list):
            parts = [self._hover_contents_to_text(item) for item in contents]
            return "\n".join(part for part in parts if part)
        return ""
