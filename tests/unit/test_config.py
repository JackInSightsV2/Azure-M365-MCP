import pytest

from unified_mcp.config import Settings


def test_settings_defaults():
    """Test default settings values."""
    # Temporarily clear env vars to test defaults
    with pytest.MonkeyPatch.context() as m:
        m.delenv("AZURE_APP_TENANT_ID", raising=False)
        m.delenv("AZURE_APP_CLIENT_ID", raising=False)
        m.delenv("AZURE_APP_CLIENT_SECRET", raising=False)

        settings = Settings()
        assert settings.app_name == "unified-microsoft-mcp"
        assert settings.log_level == "INFO"
        assert settings.mcp_transport == "stdio"
        assert not settings.has_azure_credentials()


def test_settings_validation_log_level():
    """Test log level validation."""
    settings = Settings(LOG_LEVEL="debug")
    assert settings.log_level == "DEBUG"

    # Invalid log level should default to INFO
    settings = Settings(LOG_LEVEL="INVALID")
    assert settings.log_level == "INFO"


def test_http_security_settings_are_parsed():
    settings = Settings(
        MCP_TRANSPORT="streamable_http",
        MCP_API_KEY="secret-value",
        CORS_ALLOWED_ORIGINS="http://localhost:8001,https://example.com",
    )

    assert settings.mcp_transport == "streamable-http"
    assert settings.mcp_api_key is not None
    assert settings.mcp_api_key.get_secret_value() == "secret-value"
    assert settings.cors_allowed_origins == [
        "http://localhost:8001",
        "https://example.com",
    ]


def test_azure_credentials(monkeypatch):
    """Test Azure credential properties."""
    monkeypatch.setenv("AZURE_APP_TENANT_ID", "tenant-123")
    monkeypatch.setenv("AZURE_APP_CLIENT_ID", "client-123")
    monkeypatch.setenv("AZURE_APP_CLIENT_SECRET", "secret-123")

    settings = Settings()
    assert settings.has_azure_credentials()
    assert settings.azure_credentials == {
        "tenant_id": "tenant-123",
        "client_id": "client-123",
        "client_secret": "secret-123",
    }

    creds_json = settings.get_azure_credentials_json()
    assert '"tenantId": "tenant-123"' in creds_json
    assert '"clientId": "client-123"' in creds_json
    assert "secret-123" not in repr(settings)


def test_graph_auth_config_default(monkeypatch):
    """Test default Graph auth config (read-only)."""
    monkeypatch.delenv("GRAPH_APP_CLIENT_ID", raising=False)
    monkeypatch.delenv("GRAPH_APP_TENANT_ID", raising=False)

    settings = Settings()
    config = settings.get_graph_auth_config()

    assert config["mode"] == "default"
    assert config["auth_mode"] == "device_code"
    assert (
        "User.Read" in config["scopes"][0]
        if len(config["scopes"]) > 1
        else ".default" in config["scopes"][0]
    )


def test_graph_auth_config_custom(monkeypatch):
    """Test custom Graph auth config (read-write)."""
    monkeypatch.setenv("GRAPH_APP_CLIENT_ID", "custom-client")
    monkeypatch.setenv("GRAPH_APP_TENANT_ID", "custom-tenant")
    monkeypatch.setenv("GRAPH_APP_CLIENT_SECRET", "custom-secret")

    settings = Settings()
    config = settings.get_graph_auth_config()

    assert config["mode"] == "custom"
    assert config["client_id"] == "custom-client"
    assert config["tenant_id"] == "custom-tenant"
    assert config["auth_mode"] == "client_secret"


def test_managed_identity_auth_config():
    """Managed identity applies to Azure CLI and Microsoft Graph."""
    settings = Settings(
        USE_MANAGED_IDENTITY=True,
        MANAGED_IDENTITY_CLIENT_ID="managed-client",
    )

    config = settings.get_graph_auth_config()

    assert config == {
        "mode": "managed_identity",
        "client_id": "managed-client",
        "tenant_id": None,
        "scopes": ["https://graph.microsoft.com/.default"],
    }
    assert settings.is_graph_read_only_mode is False


def test_arm_auth_profile_defaults_to_device_code(monkeypatch):
    """Without credentials, ARM signs in via device code using the configured client."""
    for name in ("AZURE_APP_TENANT_ID", "AZURE_APP_CLIENT_ID", "AZURE_APP_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)

    profile = Settings().get_arm_auth_profile()

    assert profile.kind == "device_code"
    assert profile.client_id == "1950a258-227b-4e31-a9cf-717495945fc2"
    assert profile.scopes == ("https://management.azure.com/.default",)
    assert profile.auth_record_path.endswith("arm.auth-record.json")


def test_arm_auth_profile_uses_service_principal(monkeypatch):
    """Configured Azure credentials produce an application identity for ARM."""
    settings = Settings(
        AZURE_APP_TENANT_ID="tenant",
        AZURE_APP_CLIENT_ID="client",
        AZURE_APP_CLIENT_SECRET="secret",
    )

    profile = settings.get_arm_auth_profile()

    assert profile.kind == "service_principal"
    assert profile.scopes == ("https://management.azure.com/.default",)


def test_arm_client_id_is_configurable():
    settings = Settings(AZURE_ARM_CLIENT_ID="04b07795-8ddb-461a-bbee-02f9e1bf7b46")
    assert settings.get_arm_auth_profile().client_id == "04b07795-8ddb-461a-bbee-02f9e1bf7b46"


def test_graph_device_profile_carries_cache_settings(monkeypatch):
    for name in ("GRAPH_APP_CLIENT_ID", "GRAPH_APP_TENANT_ID", "USE_APP_REG_CLIENTID", "TENANTID"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(GRAPH_TOKEN_CACHE=False)

    profile = settings.get_graph_auth_profile()

    assert profile.kind == "device_code"
    assert profile.cache_enabled is False
    assert profile.auth_record_path.endswith("graph.auth-record.json")


def test_graph_default_scope_uses_existing_tenant_grants(monkeypatch):
    monkeypatch.delenv("GRAPH_SCOPES", raising=False)

    assert Settings().graph_scopes == ["https://graph.microsoft.com/.default"]
    assert Settings(GRAPH_SCOPES="https://graph.microsoft.com/Mail.Read").graph_scopes == [
        "https://graph.microsoft.com/Mail.Read"
    ]


def test_graph_scopes_env_accepts_comma_separated(monkeypatch):
    monkeypatch.setenv(
        "GRAPH_SCOPES",
        "https://graph.microsoft.com/User.Read,https://graph.microsoft.com/Mail.Read",
    )

    assert Settings().graph_scopes == [
        "https://graph.microsoft.com/User.Read",
        "https://graph.microsoft.com/Mail.Read",
    ]
