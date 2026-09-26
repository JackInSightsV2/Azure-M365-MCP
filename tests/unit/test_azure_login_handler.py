import asyncio

import pytest

from unified_mcp.config import Settings
from unified_mcp.services.azure_cli_service import AzureCliService
from unified_mcp.services.azure_login_handler import BROWSER_LOGIN_MESSAGE, AzureLoginHandler


class FakeLoginProcess:
    """A stand-in ``az login`` process: prints ``lines``, then runs until stopped or exits."""

    def __init__(self, lines, exit_code=None):
        self.stdout = asyncio.StreamReader()
        for line in lines:
            self.stdout.feed_data(f"{line}\n".encode())
        self.exit_code = exit_code
        self.returncode = None
        self._stopped = asyncio.Event()
        if exit_code is not None:
            self.stdout.feed_eof()

    async def wait(self):
        if self.exit_code is None:
            await self._stopped.wait()
        else:
            self.returncode = self.exit_code
        return self.returncode

    def terminate(self):
        self.returncode = -15
        self._stopped.set()

    kill = terminate


@pytest.fixture
def spawned(monkeypatch):
    """Capture the arguments of every spawned process and return the scripted process."""
    calls = []
    script = {"process": None}

    async def create_subprocess_exec(*arguments, **kwargs):
        calls.append(list(arguments))
        return script["process"]

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_subprocess_exec)
    return calls, script


@pytest.mark.asyncio
async def test_browser_flow_runs_plain_az_login_in_the_background(spawned):
    calls, script = spawned
    script["process"] = FakeLoginProcess(["A web browser has been opened at https://login..."])
    handler = AzureLoginHandler(sign_in_flow="browser", browser_wait=0.05)

    message = await handler.handle_az_login_command("az login --use-device-code")

    assert calls == [["az", "login"]]
    assert message == BROWSER_LOGIN_MESSAGE
    assert "browser" in message and "retry" in message
    assert handler.current_process is script["process"]
    await handler.close()
    assert handler.current_process is None


@pytest.mark.asyncio
async def test_browser_flow_returns_promptly_while_sign_in_is_pending(spawned):
    _, script = spawned
    script["process"] = FakeLoginProcess([])
    handler = AzureLoginHandler(sign_in_flow="browser", browser_wait=0.05)

    message = await asyncio.wait_for(handler.handle_az_login_command("az login"), timeout=2)

    assert message == BROWSER_LOGIN_MESSAGE
    await handler.close()


@pytest.mark.asyncio
async def test_browser_flow_reports_an_immediate_failure(spawned):
    _, script = spawned
    script["process"] = FakeLoginProcess(["ERROR: unrecognized arguments"], exit_code=2)
    handler = AzureLoginHandler(sign_in_flow="browser", browser_wait=1.0)

    message = await handler.handle_az_login_command("az login --bogus")

    assert message.startswith("Error: Azure sign-in failed")
    assert "unrecognized arguments" in message
    assert handler.last_login_error == "ERROR: unrecognized arguments"


@pytest.mark.asyncio
async def test_device_code_flow_adds_use_device_code_and_returns_the_prompt(spawned):
    calls, script = spawned
    prompt = (
        "To sign in, use a web browser to open the page https://microsoft.com/devicelogin "
        "and enter the code ABC123 to authenticate."
    )
    script["process"] = FakeLoginProcess([prompt])
    handler = AzureLoginHandler(sign_in_flow="device_code")

    message = await handler.handle_az_login_command("az login")

    assert calls == [["az", "login", "--use-device-code"]]
    assert message == prompt
    await handler.close()


@pytest.mark.parametrize(
    ("flow", "expected"),
    [
        ("browser", ["az", "login"]),
        ("device_code", ["az", "login", "--use-device-code"]),
    ],
)
def test_login_arguments_follow_sign_in_flow_and_drop_credentials(flow, expected):
    handler = AzureLoginHandler(sign_in_flow=flow)

    arguments = handler._login_arguments(
        "az login --use-device-code --service-principal --username u --password p --tenant t"
    )

    assert arguments == expected


@pytest.mark.parametrize("flow", ["browser", "device_code"])
def test_azure_cli_service_passes_sign_in_flow_to_the_login_handler(monkeypatch, flow):
    for name in ("AZURE_APP_TENANT_ID", "AZURE_APP_CLIENT_ID", "AZURE_APP_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)

    service = AzureCliService(Settings(SIGN_IN_FLOW=flow))

    assert service.login_handler.sign_in_flow == flow


def test_browser_is_the_default_sign_in_flow(monkeypatch):
    monkeypatch.delenv("SIGN_IN_FLOW", raising=False)

    assert AzureLoginHandler().sign_in_flow == "browser"
    assert Settings(_env_file=None).sign_in_flow == "browser"
