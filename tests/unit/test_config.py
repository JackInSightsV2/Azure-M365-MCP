import os
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
        "client_secret": "secret-123"
    }
    
    creds_json = settings.get_azure_credentials_json()
    assert '"tenantId": "tenant-123"' in creds_json
    assert '"clientId": "client-123"' in creds_json

def test_graph_auth_config_default(monkeypatch):
    """Test default Graph auth config (read-only)."""
    monkeypatch.delenv("GRAPH_APP_CLIENT_ID", raising=False)
    monkeypatch.delenv("GRAPH_APP_TENANT_ID", raising=False)
    
    settings = Settings()
    config = settings.get_graph_auth_config()
    
    assert config["mode"] == "default"
    assert config["auth_mode"] == "device_code"
    assert "User.Read" in config["scopes"][0] if len(config["scopes"]) > 1 else ".default" in config["scopes"][0]

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

