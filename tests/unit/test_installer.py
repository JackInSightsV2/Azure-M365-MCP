import json
import tomllib

import pytest

from unified_mcp.installer import (
    CLIENTS,
    REPOSITORY_URL,
    SERVER_NAME,
    InstallError,
    Launch,
    Scope,
    install,
    main,
)

UVX_COMMAND = "uvx"
UVX_ARGS = ["--from", f"git+{REPOSITORY_URL}", "unified-microsoft-mcp"]


def _read(path):
    text = path.read_text(encoding="utf-8")
    return tomllib.loads(text) if path.suffix == ".toml" else json.loads(text)


def test_claude_code_project_writes_mcp_json(tmp_path):
    result = install("claude-code", tmp_path)

    assert result.path == tmp_path / ".mcp.json"
    assert result.scope is Scope.PROJECT
    assert _read(result.path) == {
        "mcpServers": {SERVER_NAME: {"type": "stdio", "command": UVX_COMMAND, "args": UVX_ARGS}}
    }


def test_claude_code_user_writes_claude_json(tmp_path):
    result = install("claude-code", tmp_path, Scope.USER)

    assert result.path == tmp_path / ".claude.json"
    assert _read(result.path)["mcpServers"][SERVER_NAME]["command"] == UVX_COMMAND


def test_vscode_project_uses_servers_key(tmp_path):
    result = install("vscode", tmp_path)

    assert result.path == tmp_path / ".vscode" / "mcp.json"
    assert _read(result.path) == {
        "servers": {SERVER_NAME: {"type": "stdio", "command": UVX_COMMAND, "args": UVX_ARGS}}
    }


def test_vscode_user_scope_uses_profile_directory(tmp_path):
    result = install("vscode", tmp_path, Scope.USER, platform="darwin")

    assert result.path == tmp_path / "Library/Application Support/Code/User/mcp.json"
    assert SERVER_NAME in _read(result.path)["servers"]


@pytest.mark.parametrize("scope", [Scope.PROJECT, Scope.USER])
def test_cursor_writes_cursor_mcp_json(tmp_path, scope):
    result = install("cursor", tmp_path, scope)

    assert result.path == tmp_path / ".cursor" / "mcp.json"
    assert _read(result.path) == {
        "mcpServers": {SERVER_NAME: {"command": UVX_COMMAND, "args": UVX_ARGS}}
    }


def test_codex_writes_mcp_servers_table(tmp_path):
    result = install("codex", tmp_path)

    assert result.path == tmp_path / ".codex" / "config.toml"
    assert result.scope is Scope.USER
    assert _read(result.path) == {
        "mcp_servers": {SERVER_NAME: {"command": UVX_COMMAND, "args": UVX_ARGS}}
    }
    assert f"[mcp_servers.{SERVER_NAME}]" in result.path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("platform", "relative"),
    [
        ("darwin", "Library/Application Support/Claude/claude_desktop_config.json"),
        ("win32", "AppData/Roaming/Claude/claude_desktop_config.json"),
        ("linux", ".config/Claude/claude_desktop_config.json"),
    ],
)
def test_claude_desktop_uses_per_os_path(tmp_path, platform, relative):
    result = install("claude-desktop", tmp_path, platform=platform)

    assert result.path == tmp_path / relative
    assert _read(result.path) == {
        "mcpServers": {SERVER_NAME: {"command": UVX_COMMAND, "args": UVX_ARGS}}
    }


def test_claude_desktop_rejects_project_scope(tmp_path):
    with pytest.raises(InstallError):
        install("claude-desktop", tmp_path, Scope.PROJECT)


def test_unknown_client_is_rejected(tmp_path):
    with pytest.raises(InstallError):
        install("notepad", tmp_path)


@pytest.mark.parametrize("client", CLIENTS)
def test_install_is_idempotent(tmp_path, client):
    first = install(client, tmp_path, platform="linux")
    content = first.path.read_bytes()

    second = install(client, tmp_path, platform="linux")

    assert first.changed is True
    assert second.changed is False
    assert second.path.read_bytes() == content


@pytest.mark.parametrize("client", ["claude-code", "cursor", "claude-desktop"])
def test_json_install_preserves_other_servers_and_settings(tmp_path, client):
    path = install(client, tmp_path, platform="linux").path
    path.write_text(
        json.dumps(
            {
                "theme": "dark",
                "mcpServers": {"other": {"command": "other-server", "args": ["--flag"]}},
            }
        ),
        encoding="utf-8",
    )

    install(client, tmp_path, platform="linux")

    document = _read(path)
    assert document["theme"] == "dark"
    assert document["mcpServers"]["other"] == {"command": "other-server", "args": ["--flag"]}
    assert document["mcpServers"][SERVER_NAME]["command"] == UVX_COMMAND


def test_vscode_install_preserves_inputs_and_other_servers(tmp_path):
    path = tmp_path / ".vscode" / "mcp.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps({"inputs": [{"id": "token"}], "servers": {"other": {"command": "x"}}}),
        encoding="utf-8",
    )

    install("vscode", tmp_path)

    document = _read(path)
    assert document["inputs"] == [{"id": "token"}]
    assert set(document["servers"]) == {"other", SERVER_NAME}


def test_codex_install_preserves_other_settings_and_comments(tmp_path):
    path = tmp_path / ".codex" / "config.toml"
    path.parent.mkdir()
    path.write_text(
        '# my settings\nmodel = "gpt-5"\n\n'
        '[mcp_servers.other]\ncommand = "other-server"\nargs = ["--flag"]\n',
        encoding="utf-8",
    )

    install("codex", tmp_path)

    text = path.read_text(encoding="utf-8")
    document = tomllib.loads(text)
    assert "# my settings" in text
    assert document["model"] == "gpt-5"
    assert document["mcp_servers"]["other"] == {"command": "other-server", "args": ["--flag"]}
    assert document["mcp_servers"][SERVER_NAME] == {"command": UVX_COMMAND, "args": UVX_ARGS}


@pytest.mark.parametrize("client", ["cursor", "codex"])
def test_install_replaces_a_stale_entry(tmp_path, client):
    install(client, tmp_path, launch=Launch.DOCKER)

    result = install(client, tmp_path)

    assert result.changed is True
    servers = _read(result.path)["mcpServers" if client == "cursor" else "mcp_servers"]
    assert servers == {SERVER_NAME: {"command": UVX_COMMAND, "args": UVX_ARGS}}


def test_docker_launch_writes_docker_command(tmp_path):
    result = install("cursor", tmp_path, launch=Launch.DOCKER)

    entry = _read(result.path)["mcpServers"][SERVER_NAME]
    assert entry["command"] == "docker"
    assert entry["args"][-1] == "ghcr.io/jackinsightsv2/azure-m365-mcp:latest"


def test_invalid_json_is_not_overwritten(tmp_path):
    path = tmp_path / ".cursor" / "mcp.json"
    path.parent.mkdir()
    path.write_text("{ // comment\n}", encoding="utf-8")

    with pytest.raises(InstallError):
        install("cursor", tmp_path)

    assert path.read_text(encoding="utf-8") == "{ // comment\n}"


def test_main_writes_config_and_reports_path(tmp_path, capsys):
    assert main(["--client", "cursor", "--dir", str(tmp_path)]) == 0
    assert main(["--client", "cursor", "--dir", str(tmp_path)]) == 0

    output = capsys.readouterr().out
    assert str(tmp_path / ".cursor" / "mcp.json") in output
    assert "already up to date" in output


def test_main_reports_install_errors(tmp_path, capsys):
    exit_code = main(["--client", "claude-desktop", "--scope", "project", "--dir", str(tmp_path)])

    assert exit_code == 1
    assert "Install failed" in capsys.readouterr().err
