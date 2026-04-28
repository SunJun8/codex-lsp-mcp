from codex_lsp_mcp.config import AppConfig, ServerConfig
from codex_lsp_mcp.manager import SessionManager


class FakeSession:
    created = []

    def __init__(self, root, server_config):
        self.root = root
        self.server_config = server_config
        self.started = False
        FakeSession.created.append(self)

    async def start(self):
        self.started = True


def test_manager_reuses_session_for_same_discovered_root(tmp_path):
    root = tmp_path / "repo"
    src = root / "src"
    src.mkdir(parents=True)
    (root / "compile_commands.json").write_text("[]", encoding="utf-8")
    one = src / "one.c"
    two = src / "two.c"
    one.write_text("int one;\n", encoding="utf-8")
    two.write_text("int two;\n", encoding="utf-8")
    config = AppConfig(
        servers={
            "clangd": ServerConfig(
                command="clangd",
                args=["--background-index"],
                extension_to_language={".c": "c"},
            )
        }
    )
    manager = SessionManager(config, fallback_root=tmp_path, session_factory=FakeSession)

    first = manager.get_session(one)
    second = manager.get_session(two)

    assert first is second
    assert first.root == root


def test_manager_rejects_unsupported_extension(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("hello\n", encoding="utf-8")
    config = AppConfig(
        servers={
            "clangd": ServerConfig(
                command="clangd",
                args=[],
                extension_to_language={".c": "c"},
            )
        }
    )
    manager = SessionManager(config, fallback_root=tmp_path, session_factory=FakeSession)

    try:
        manager.get_session(path)
    except ValueError as exc:
        assert "unsupported file extension" in str(exc)
    else:
        raise AssertionError("unsupported extension did not fail")
