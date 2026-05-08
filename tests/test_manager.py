from codex_lsp_mcp.config import AppConfig, ServerConfig, default_config
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


def test_manager_get_session_falls_back_to_root_hint_without_markers(tmp_path):
    workspace = tmp_path / "workspace"
    source_dir = workspace / "src"
    fallback = tmp_path / "server"
    source_dir.mkdir(parents=True)
    fallback.mkdir()
    path = source_dir / "main.c"
    path.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    config = AppConfig(
        servers={
            "clangd": ServerConfig(
                command="clangd",
                args=["--background-index"],
                extension_to_language={".c": "c"},
            )
        }
    )
    manager = SessionManager(config, fallback_root=fallback, session_factory=FakeSession)

    session = manager.get_session(path, root_hint=workspace)

    assert session.root == workspace.resolve()


def test_manager_get_session_rejects_missing_root_hint(tmp_path):
    workspace = tmp_path / "workspace"
    source_dir = workspace / "src"
    fallback = tmp_path / "server"
    source_dir.mkdir(parents=True)
    fallback.mkdir()
    path = source_dir / "main.c"
    path.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    config = AppConfig(
        servers={
            "clangd": ServerConfig(
                command="clangd",
                args=["--background-index"],
                extension_to_language={".c": "c"},
            )
        }
    )
    manager = SessionManager(config, fallback_root=fallback, session_factory=FakeSession)

    try:
        manager.get_session(path, root_hint=tmp_path / "missing")
    except FileNotFoundError as exc:
        assert exc.args == ((tmp_path / "missing").resolve(),)
    else:
        raise AssertionError("missing root hint did not fail")


def test_manager_get_session_prefers_marker_root_over_root_hint(tmp_path):
    workspace = tmp_path / "workspace"
    package = workspace / "packages" / "native"
    source_dir = package / "src"
    fallback = tmp_path / "server"
    source_dir.mkdir(parents=True)
    fallback.mkdir()
    (package / "compile_commands.json").write_text("[]", encoding="utf-8")
    path = source_dir / "main.c"
    path.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    config = AppConfig(
        servers={
            "clangd": ServerConfig(
                command="clangd",
                args=["--background-index"],
                extension_to_language={".c": "c"},
            )
        }
    )
    manager = SessionManager(config, fallback_root=fallback, session_factory=FakeSession)

    session = manager.get_session(path, root_hint=workspace)

    assert session.root == package.resolve()


def test_manager_root_hint_preserves_backend_specific_markers(tmp_path):
    workspace = tmp_path / "workspace"
    native = workspace / "native"
    python = workspace / "python"
    native_src = native / "src"
    python_src = python / "src"
    native_src.mkdir(parents=True)
    python_src.mkdir(parents=True)
    (native / "compile_commands.json").write_text("[]", encoding="utf-8")
    (python / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\n",
        encoding="utf-8",
    )
    c_file = native_src / "main.c"
    py_file = python_src / "app.py"
    c_file.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    py_file.write_text("def main():\n    return 0\n", encoding="utf-8")
    manager = SessionManager(
        default_config(),
        fallback_root=tmp_path / "server",
        session_factory=FakeSession,
    )

    c_session = manager.get_session(c_file, root_hint=workspace)
    py_session = manager.get_session(py_file, root_hint=workspace)

    assert c_session.root == native.resolve()
    assert c_session.server_config.command == "clangd"
    assert py_session.root == python.resolve()
    assert py_session.server_config.command == "pyright-langserver"


def test_manager_default_config_routes_python_files_to_pyright(tmp_path):
    root = tmp_path / "repo"
    src = root / "src"
    src.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    path = src / "app.py"
    path.write_text("def main():\n    return 0\n", encoding="utf-8")
    manager = SessionManager(
        default_config(),
        fallback_root=tmp_path,
        session_factory=FakeSession,
    )

    server_name, language_id = manager.language_for(path)
    session = manager.get_session(path)

    assert (server_name, language_id) == ("pyright", "python")
    assert session.root == root
    assert session.server_config.command == "pyright-langserver"
    assert session.server_config.args == ["--stdio"]


def test_manager_default_pyright_prefers_pyrightconfig_root_over_repo_root(tmp_path):
    repo = tmp_path / "repo"
    package = repo / "packages" / "python"
    src = package / "src"
    src.mkdir(parents=True)
    (repo / ".git").mkdir()
    (package / "pyrightconfig.json").write_text("{}\n", encoding="utf-8")
    path = src / "app.py"
    path.write_text("def main():\n    return 0\n", encoding="utf-8")
    manager = SessionManager(
        default_config(),
        fallback_root=tmp_path,
        session_factory=FakeSession,
    )

    session = manager.get_session(path)

    assert session.root == package
    assert session.server_config.command == "pyright-langserver"


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
