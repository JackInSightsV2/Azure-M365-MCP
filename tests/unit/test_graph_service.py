import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from azure.core.credentials import AccessToken

from unified_mcp.auth import DeviceCodeProfile, ServicePrincipalProfile, TokenBroker
from unified_mcp.config import Settings
from unified_mcp.services.graph_service import GraphService


@pytest.mark.asyncio
async def test_get_client_secret_missing(mock_token_broker):
    service = GraphService(
        Settings(
            GRAPH_APP_CLIENT_ID="id",
            GRAPH_APP_TENANT_ID="tenant",
            GRAPH_APP_CLIENT_SECRET=None,
        ),
        token_broker=mock_token_broker,
    )

    result = await service._get_client_secret()

    assert result["success"] is False
    assert result["auth_required"] is True
    assert result["auth_type"] == "client_secret"


@pytest.mark.asyncio
async def test_execute_command_success(mock_graph_service):
    response = MagicMock(status_code=200)
    response.json.return_value = {"value": [{"displayName": "User"}]}
    client = AsyncMock()
    client.request.return_value = response
    mock_graph_service._get_http_client = MagicMock(return_value=client)

    result = await mock_graph_service.execute_command("users")

    assert result["success"] is True
    assert result["data"]["value"][0]["displayName"] == "User"
    client.request.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_command_post(mock_graph_service):
    response = MagicMock(status_code=201)
    response.json.return_value = {"id": "new-id"}
    client = AsyncMock()
    client.request.return_value = response
    mock_graph_service._get_http_client = MagicMock(return_value=client)

    result = await mock_graph_service.execute_command(
        "users",
        method="POST",
        data={"displayName": "New User"},
    )

    assert result["success"] is True
    assert result["status_code"] == 201
    client.request.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_command_error(mock_graph_service):
    response = MagicMock(status_code=404)
    response.json.return_value = {"error": {"message": "User not found"}}
    client = AsyncMock()
    client.request.return_value = response
    mock_graph_service._get_http_client = MagicMock(return_value=client)

    result = await mock_graph_service.execute_command("users/invalid")

    assert result["success"] is False
    assert result["status_code"] == 404
    assert "User not found" in result["error"]


@pytest.mark.asyncio
async def test_auth_failure_handling(mock_graph_service, mock_token_broker):
    mock_token_broker.get_token.side_effect = Exception("Auth failed")

    result = await mock_graph_service.execute_command("me")

    assert result["success"] is False
    assert result["auth_required"] is True
    assert "Authentication failed" in result["error"]


@pytest.mark.asyncio
async def test_device_token_task_survives_prompt_timeout_and_is_shared():
    release = asyncio.Event()

    class SlowCredential:
        def __init__(self) -> None:
            self.calls = 0

        async def get_token(self, *_scopes: str) -> AccessToken:
            self.calls += 1
            await release.wait()
            return AccessToken("token", 4_102_444_800)

        async def close(self) -> None:
            return None

    credential = SlowCredential()
    callback = MagicMock()
    broker = TokenBroker(
        DeviceCodeProfile("common", "client", ("User.Read",)),
        callback,
        credential_factory=lambda _profile, _callback: credential,
    )

    with pytest.raises(asyncio.TimeoutError):
        await broker.get_token(prompt_timeout=0.01)
    assert credential.calls == 1

    release.set()
    first, second = await asyncio.gather(broker.get_token(), broker.get_token())

    assert first.token == second.token == "token"
    assert credential.calls == 1
    await broker.close()


@pytest.mark.asyncio
async def test_device_prompt_is_returned_while_token_continues():
    service: GraphService

    class PromptingBroker:
        is_application_identity = False

        async def get_token(self) -> AccessToken:
            service._device_code_callback(
                "https://microsoft.com/devicelogin",
                "ABCD-EFGH",
                datetime.now(timezone.utc) + timedelta(minutes=5),
            )
            raise asyncio.TimeoutError

        async def close(self) -> None:
            return None

    service = GraphService(Settings(), token_broker=PromptingBroker())  # type: ignore[arg-type]

    result = await service.execute_command("me")

    assert result["auth_required"] is True
    assert result["user_code"] == "ABCD-EFGH"


@pytest.mark.asyncio
async def test_cancelled_application_token_request_does_not_poison_broker():
    class RecoveringCredential:
        def __init__(self) -> None:
            self.calls = 0

        async def get_token(self, *_scopes: str) -> AccessToken:
            self.calls += 1
            if self.calls == 1:
                await asyncio.Event().wait()
            return AccessToken("recovered", 4_102_444_800)

        async def close(self) -> None:
            return None

    credential = RecoveringCredential()
    broker = TokenBroker(
        ServicePrincipalProfile("tenant", "client", "secret", (".default",)),
        MagicMock(),
        credential_factory=lambda _profile, _callback: credential,
    )

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(broker.get_token(), timeout=0.01)

    token = await broker.get_token()

    assert token.token == "recovered"
    assert credential.calls == 2
    await broker.close()
