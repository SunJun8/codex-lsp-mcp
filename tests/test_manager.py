from codex_lsp_mcp.config import AppConfig, ServerConfig
from codex_lsp_mcp.manager import SessionManager


class FakeSession:
    created = []
    requested_roots = []

    def __init__(self, root, server_config):
        self.root = root
        self.server_config = server_config
        self.started = False
        FakeSession.created.append(self)
        FakeSession.requested_roots.append(root)

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


def test_manager_uses_server_specific_root_markers(tmp_path):
    root = tmp_path / "repo"
    src = root / "src"
    src.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    path = src / "app.py"
    path.write_text("print('hi')\n", encoding="utf-8")
    config = AppConfig(
        servers={
            "pyright": ServerConfig(
                command="pyright-langserver",
                args=["--stdio"],
                extension_to_language={".py": "python"},
                root_markers=(("pyproject.toml",),),
                workspace_hint_extension=".py",
            )
        }
    )
    manager = SessionManager(config, fallback_root=tmp_path, session_factory=FakeSession)

    session = manager.get_session(path)

    assert session.root == root


def test_manager_builds_workspace_hint_from_default_server_config(tmp_path):
    config = AppConfig(
        servers={
            "pyright": ServerConfig(
                command="pyright-langserver",
                args=["--stdio"],
                extension_to_language={".py": "python"},
                root_markers=(("pyproject.toml",),),
                workspace_hint_extension=".py",
            )
        }
    )
    manager = SessionManager(config, fallback_root=tmp_path, session_factory=FakeSession)

    session = manager.get_workspace_session(tmp_path)

    assert session.root == tmp_path


def test_manager_infers_workspace_backend_from_directory_root_markers(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    config = AppConfig(
        servers={
            "clangd": ServerConfig(
                command="clangd",
                args=["--background-index"],
                extension_to_language={".c": "c"},
            ),
            "pyright": ServerConfig(
                command="pyright-langserver",
                args=["--stdio"],
                extension_to_language={".py": "python"},
                root_markers=(("pyproject.toml",),),
                workspace_hint_extension=".py",
            ),
        }
    )
    manager = SessionManager(config, fallback_root=tmp_path, session_factory=FakeSession)

    session = manager.get_workspace_session(root)

    assert session.root == root
    assert session.server_config.command == "pyright-langserver"


def test_manager_uses_explicit_workspace_server_name_for_directory_hint(tmp_path):
    config = AppConfig(
        servers={
            "clangd": ServerConfig(
                command="clangd",
                args=["--background-index"],
                extension_to_language={".c": "c"},
            ),
            "pyright": ServerConfig(
                command="pyright-langserver",
                args=["--stdio"],
                extension_to_language={".py": "python"},
                root_markers=(("pyproject.toml",),),
                workspace_hint_extension=".py",
            ),
        }
    )
    manager = SessionManager(config, fallback_root=tmp_path, session_factory=FakeSession)

    session = manager.get_workspace_session(tmp_path, server_name="pyright")

    assert session.server_config.command == "pyright-langserver"


def test_manager_rejects_unknown_workspace_server_name(tmp_path):
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

    try:
        manager.get_workspace_session(tmp_path, server_name="pyright")
    except ValueError as exc:
        assert "unknown LSP server" in str(exc)
    else:
        raise AssertionError("unknown workspace server did not fail")


def test_manager_treats_missing_suffixed_workspace_hint_as_file(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    missing_file = root / "app.py"
    config = AppConfig(
        servers={
            "pyright": ServerConfig(
                command="pyright-langserver",
                args=["--stdio"],
                extension_to_language={".py": "python"},
                root_markers=(("pyproject.toml",),),
                workspace_hint_extension=".py",
            )
        }
    )
    manager = SessionManager(config, fallback_root=tmp_path, session_factory=FakeSession)

    session = manager.get_workspace_session(missing_file, server_name="pyright")

    assert session.root == root


def test_manager_treats_existing_dotted_workspace_hint_as_directory(tmp_path):
    root = tmp_path / "service.v2"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    config = AppConfig(
        servers={
            "pyright": ServerConfig(
                command="pyright-langserver",
                args=["--stdio"],
                extension_to_language={".py": "python"},
                root_markers=(("pyproject.toml",),),
                workspace_hint_extension=".py",
            )
        }
    )
    manager = SessionManager(config, fallback_root=tmp_path, session_factory=FakeSession)

    session = manager.get_workspace_session(root, server_name="pyright")

    assert session.root == root
    assert FakeSession.requested_roots[-1] == root


def test_manager_rejects_ambiguous_workspace_directory_backend(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    config = AppConfig(
        servers={
            "clangd": ServerConfig(
                command="clangd",
                args=["--background-index"],
                extension_to_language={".c": "c"},
                root_markers=((".git",),),
            ),
            "pyright": ServerConfig(
                command="pyright-langserver",
                args=["--stdio"],
                extension_to_language={".py": "python"},
                root_markers=((".git",),),
                workspace_hint_extension=".py",
            ),
        }
    )
    manager = SessionManager(config, fallback_root=tmp_path, session_factory=FakeSession)

    try:
        manager.get_workspace_session(root)
    except ValueError as exc:
        assert "ambiguous workspace LSP server" in str(exc)
    else:
        raise AssertionError("ambiguous workspace backend did not fail")
