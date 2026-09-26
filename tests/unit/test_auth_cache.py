import time

import pytest
from azure.core.credentials import AccessToken

from unified_mcp.auth import DeviceCodeProfile, ServicePrincipalProfile, TokenBroker


class RecordingCredential:
    """Credential that exposes an ``_auth_record`` like DeviceCodeCredential."""

    def __init__(self, record: object | None = "auth-record") -> None:
        self._auth_record = record

    def get_token(self, *_scopes: str) -> AccessToken:
        return AccessToken("token", int(time.time()) + 3600)


@pytest.mark.asyncio
async def test_device_profile_persists_auth_record_once(tmp_path):
    path = str(tmp_path / "arm.json")
    saved: list[tuple[str | None, object]] = []
    profile = DeviceCodeProfile("t", "c", ("s",), auth_record_path=path)
    broker = TokenBroker(
        profile,
        lambda *_a: None,
        credential_factory=lambda _p, _c: RecordingCredential(),
    )

    import unified_mcp.auth as auth_module

    original = auth_module.save_auth_record
    auth_module.save_auth_record = lambda p, r: saved.append((p, r))
    try:
        await broker.get_token()
        # A second acquisition (forced) must not persist again.
        broker._cached_token = None
        await broker.get_token()
    finally:
        auth_module.save_auth_record = original

    assert saved == [(path, "auth-record")]


@pytest.mark.asyncio
async def test_cache_disabled_skips_persistence(tmp_path):
    saved: list = []
    profile = DeviceCodeProfile(
        "t", "c", ("s",), cache_enabled=False, auth_record_path=str(tmp_path / "x.json")
    )
    broker = TokenBroker(
        profile,
        lambda *_a: None,
        credential_factory=lambda _p, _c: RecordingCredential(),
    )

    import unified_mcp.auth as auth_module

    original = auth_module.save_auth_record
    auth_module.save_auth_record = lambda p, r: saved.append((p, r))
    try:
        await broker.get_token()
    finally:
        auth_module.save_auth_record = original

    assert saved == []


@pytest.mark.asyncio
async def test_non_device_profile_skips_persistence():
    saved: list = []
    profile = ServicePrincipalProfile("t", "c", "secret", scopes=("s",))
    broker = TokenBroker(
        profile,
        lambda *_a: None,
        credential_factory=lambda _p, _c: RecordingCredential(),
    )

    import unified_mcp.auth as auth_module

    original = auth_module.save_auth_record
    auth_module.save_auth_record = lambda p, r: saved.append((p, r))
    try:
        await broker.get_token()
    finally:
        auth_module.save_auth_record = original

    assert saved == []


def test_browser_flow_is_default_for_user_sign_in(monkeypatch):
    from unified_mcp.auth import DeviceCodeProfile, TokenBroker
    from unified_mcp.config import Settings

    monkeypatch.delenv("SIGN_IN_FLOW", raising=False)
    settings = Settings()
    for profile in (settings.get_graph_auth_profile(), settings.get_arm_auth_profile()):
        assert isinstance(profile, DeviceCodeProfile)
        assert profile.use_browser is True
        credential = TokenBroker(profile, lambda *_: None)._create_credential(
            profile, lambda *_: None
        )
        assert type(credential).__name__ == "InteractiveBrowserCredential"


def test_device_code_flow_is_selectable(monkeypatch):
    from unified_mcp.config import Settings

    settings = Settings(SIGN_IN_FLOW="device_code")
    assert settings.get_graph_auth_profile().use_browser is False
    assert settings.get_arm_auth_profile().use_browser is False


def test_pending_browser_sign_in_says_to_finish_in_browser():
    from unified_mcp.auth import DeviceCodeProfile, pending_sign_in_response

    profile = DeviceCodeProfile("organizations", "client", ("scope",), use_browser=True)
    response = pending_sign_in_response(profile)
    assert response is not None and "browser window" in response["instructions"]
    assert pending_sign_in_response(DeviceCodeProfile("t", "c", ("s",))) is None
