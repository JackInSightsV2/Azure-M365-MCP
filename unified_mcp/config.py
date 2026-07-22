"""Configuration management for Unified Microsoft MCP Server."""

import json
from typing import Any, Dict, Optional

from pydantic import Field, SecretStr, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from unified_mcp.auth import (
    AzureAuthProfile,
    DeviceCodeProfile,
    GraphAuthProfile,
    InteractiveAzureProfile,
    ManagedIdentityProfile,
    ServicePrincipalProfile,
)
from unified_mcp.execution_policy import ExecutionPolicy, ExecutionPolicyMode


class Settings(BaseSettings):
    """Application settings using Pydantic for both Azure CLI and Graph services."""

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
        frozen=True,  # Make settings immutable
        env_prefix="",
    )

    # Application settings
    app_name: str = "unified-microsoft-mcp"

    # Shared App Registration
    share_app_registration: bool = Field(default=False, alias="SHARE_APP_REGISTRATION")
    use_managed_identity: bool = Field(default=False, alias="USE_MANAGED_IDENTITY")
    managed_identity_client_id: Optional[str] = Field(
        default=None, alias="MANAGED_IDENTITY_CLIENT_ID"
    )

    # =============================================================================
    # AZURE CLI SETTINGS
    # =============================================================================

    # Azure CLI credentials (for service principal authentication)
    azure_tenant_id: Optional[str] = Field(default=None, alias="AZURE_APP_TENANT_ID")
    azure_client_id: Optional[str] = Field(default=None, alias="AZURE_APP_CLIENT_ID")
    azure_client_secret: Optional[SecretStr] = Field(default=None, alias="AZURE_APP_CLIENT_SECRET")
    azure_subscription_id: Optional[str] = Field(default=None, alias="AZURE_SUBSCRIPTION_ID")

    # Command execution settings
    command_timeout: int = Field(default=300, ge=1, le=3600, alias="COMMAND_TIMEOUT")
    max_concurrent_commands: int = Field(default=5, ge=1, le=50, alias="MAX_CONCURRENT_COMMANDS")

    # Tool execution authorization. The compatibility default preserves existing behavior.
    execution_policy: ExecutionPolicyMode = Field(
        default=ExecutionPolicyMode.UNRESTRICTED,
        alias="EXECUTION_POLICY",
    )
    azure_command_allowlist: list[str] = Field(
        default=[],
        alias="AZURE_COMMAND_ALLOWLIST",
    )
    graph_request_allowlist: list[str] = Field(
        default=[],
        alias="GRAPH_REQUEST_ALLOWLIST",
    )

    # =============================================================================
    # MICROSOFT GRAPH SETTINGS
    # =============================================================================

    # Microsoft Graph settings for user authentication (read-only mode)
    graph_tenant_id: Optional[str] = Field(default=None, alias="GRAPH_TENANT_ID")
    graph_client_id: str = Field(
        default="14d82eec-204b-4c2f-b7e8-296a70dab67e",  # Microsoft Graph PowerShell public client
        alias="GRAPH_CLIENT_ID",
    )

    # Custom app registration settings (optional - enables read/write mode)
    custom_client_id: Optional[str] = Field(default=None, alias="GRAPH_APP_CLIENT_ID")
    custom_tenant_id: Optional[str] = Field(default=None, alias="GRAPH_APP_TENANT_ID")
    custom_client_secret: Optional[SecretStr] = Field(default=None, alias="GRAPH_APP_CLIENT_SECRET")

    # Alternative environment variable names for MCP configuration
    use_app_reg_clientid: Optional[str] = Field(default=None, alias="USE_APP_REG_CLIENTID")
    tenantid: Optional[str] = Field(default=None, alias="TENANTID")
    client_secret: Optional[SecretStr] = Field(default=None, alias="CLIENT_SECRET")

    # Legacy naming (for backward compatibility)
    graph_client_secret: Optional[SecretStr] = Field(default=None, alias="GRAPH_CLIENT_SECRET")

    # Microsoft Graph delegated scopes. Custom applications use their configured
    # application permissions through the .default scope.
    graph_scopes: list[str] = Field(
        default=[
            "https://graph.microsoft.com/User.Read",
            "https://graph.microsoft.com/Mail.Read",
            "https://graph.microsoft.com/Calendars.Read",
            "https://graph.microsoft.com/Files.Read",
            "https://graph.microsoft.com/Sites.Read.All",
            "https://graph.microsoft.com/Team.ReadBasic.All",
            "https://graph.microsoft.com/Channel.ReadBasic.All",
            "https://graph.microsoft.com/User.ReadBasic.All",
            "https://graph.microsoft.com/Group.Read.All",
            "https://graph.microsoft.com/DeviceManagementManagedDevices.Read.All",
            "https://graph.microsoft.com/DeviceManagementConfiguration.Read.All",
            "https://graph.microsoft.com/DeviceManagementApps.Read.All",
            "https://graph.microsoft.com/SecurityEvents.Read.All",
        ],
        alias="GRAPH_SCOPES",
    )

    # Operation execution settings
    operation_timeout: int = Field(default=300, ge=1, le=3600, alias="OPERATION_TIMEOUT")
    max_concurrent_operations: int = Field(
        default=5, ge=1, le=50, alias="MAX_CONCURRENT_OPERATIONS"
    )

    # =============================================================================
    # GENERAL MCP SETTINGS
    # =============================================================================

    # MCP settings
    mcp_server_enabled: bool = True
    mcp_transport: str = Field(default="stdio", alias="MCP_TRANSPORT")
    mcp_host: str = Field(default="127.0.0.1", alias="MCP_HOST")
    mcp_port: int = Field(default=8001, alias="MCP_PORT")
    mcp_api_key: Optional[SecretStr] = Field(default=None, alias="MCP_API_KEY")
    cors_allowed_origins: list[str] = Field(
        default=["http://127.0.0.1:8001", "http://localhost:8001"],
        alias="CORS_ALLOWED_ORIGINS",
    )
    mcp_server_name: str = "unified-microsoft-mcp"

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_file: str = Field(default="unified_mcp.log", alias="LOG_FILE")

    # Mock Mode for Testing
    mock_mode: bool = Field(default=False, alias="MOCK_MODE")

    # =============================================================================
    # VALIDATORS
    # =============================================================================

    @field_validator("mock_mode", mode="before")
    @classmethod
    def validate_mock_mode(cls, v: Any) -> bool:
        """Validate and parse mock mode from string or boolean."""
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            v_lower = v.lower().strip()
            if v_lower in ("true", "1", "yes", "on"):
                return True
            if v_lower in ("false", "0", "no", "off", ""):
                return False
        return bool(v)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            return "INFO"  # Default to INFO for invalid values
        return v.upper()

    @field_validator("mcp_transport")
    @classmethod
    def validate_mcp_transport(cls, v: str) -> str:
        """Validate MCP transport mode."""
        valid_transports = ["stdio", "streamable-http", "sse", "openapi"]
        v_lower = v.lower().replace("_", "-")
        if v_lower not in valid_transports:
            raise ValueError(
                f"Invalid MCP transport mode: '{v}'. Must be one of: {', '.join(valid_transports)}"
            )
        return v_lower

    @field_validator("graph_scopes")
    @classmethod
    def validate_graph_scopes(cls, v: Any) -> list[str]:
        """Validate Microsoft Graph scopes."""
        if isinstance(v, str):
            # If it's a string, split by comma
            return [scope.strip() for scope in v.split(",")]
        if isinstance(v, (list, tuple, set)):
            return [str(scope) for scope in v]
        raise ValueError("GRAPH_SCOPES must be a list or comma-separated string")

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def validate_cors_allowed_origins(cls, v: Any) -> list[str]:
        """Parse a comma-separated browser origin allowlist."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        if isinstance(v, (list, tuple, set)):
            return [str(origin) for origin in v]
        raise ValueError("CORS_ALLOWED_ORIGINS must be a list or comma-separated string")

    @field_validator("azure_command_allowlist", "graph_request_allowlist", mode="before")
    @classmethod
    def validate_allowlist(cls, v: Any) -> list[str]:
        """Parse comma-separated policy entries."""
        if isinstance(v, str):
            return [entry.strip() for entry in v.split(",") if entry.strip()]
        if isinstance(v, (list, tuple, set)):
            return [str(entry).strip() for entry in v if str(entry).strip()]
        raise ValueError("Execution allowlists must be lists or comma-separated strings")

    # =============================================================================
    # AZURE CLI METHODS
    # =============================================================================

    @computed_field(repr=False)
    def azure_credentials(self) -> Optional[Dict[str, Optional[str]]]:
        """Get Azure CLI credentials as a dictionary."""
        if self.has_azure_credentials():
            return {
                "tenant_id": self.azure_tenant_id,
                "client_id": self.azure_client_id,
                "client_secret": (
                    self.azure_client_secret.get_secret_value()
                    if self.azure_client_secret is not None
                    else None
                ),
            }
        return None

    def has_azure_credentials(self) -> bool:
        """Check if all required Azure CLI credentials are present."""
        return all([self.azure_tenant_id, self.azure_client_id, self.azure_client_secret])

    def get_azure_credentials_json(self) -> Optional[str]:
        """Get Azure CLI credentials as JSON string for Azure CLI authentication."""
        if self.has_azure_credentials():
            credentials = {
                "tenantId": self.azure_tenant_id,
                "clientId": self.azure_client_id,
                "clientSecret": (
                    self.azure_client_secret.get_secret_value()
                    if self.azure_client_secret is not None
                    else None
                ),
            }
            if self.azure_subscription_id:
                credentials["subscriptionId"] = self.azure_subscription_id
            return json.dumps(credentials)
        return None

    def get_azure_auth_profile(self) -> AzureAuthProfile:
        """Resolve legacy environment variables into a typed Azure authentication profile."""
        if self.use_managed_identity:
            return ManagedIdentityProfile(client_id=self.managed_identity_client_id)
        if self.has_azure_credentials():
            assert self.azure_tenant_id is not None
            assert self.azure_client_id is not None
            assert self.azure_client_secret is not None
            return ServicePrincipalProfile(
                tenant_id=self.azure_tenant_id,
                client_id=self.azure_client_id,
                client_secret=self.azure_client_secret.get_secret_value(),
            )
        return InteractiveAzureProfile()

    # =============================================================================
    # MICROSOFT GRAPH METHODS
    # =============================================================================

    def get_graph_auth_config(self) -> Dict[str, Any]:
        """Get Microsoft Graph authentication configuration."""
        if self.use_managed_identity:
            return {
                "mode": "managed_identity",
                "client_id": self.managed_identity_client_id,
                "tenant_id": None,
                "scopes": ["https://graph.microsoft.com/.default"],
            }

        # Check for new clean configuration first (GRAPH_APP_*)
        client_id = self.custom_client_id or self.use_app_reg_clientid
        tenant_id = self.custom_tenant_id or self.tenantid

        # If sharing credentials and graph creds are missing, try to use Azure creds
        if self.share_app_registration:
            if not client_id and self.azure_client_id:
                client_id = self.azure_client_id
            if not tenant_id and self.azure_tenant_id:
                tenant_id = self.azure_tenant_id

        # Check if custom app registration is configured
        if client_id and tenant_id:
            # Custom app registration mode (read/write)
            config = {
                "mode": "custom",
                "client_id": client_id,
                "tenant_id": tenant_id,
                "auth_mode": "client_secret",  # Always use client secret for custom apps
                "scopes": ["https://graph.microsoft.com/.default"],  # Use .default for custom apps
            }
        else:
            # Default read-only mode using Microsoft Graph PowerShell public client
            config = {
                "mode": "default",
                "client_id": self.graph_client_id,
                "tenant_id": self.graph_tenant_id or "common",
                "auth_mode": "device_code",
                "scopes": self.graph_scopes,
            }

        return config

    def get_graph_client_secret(self) -> Optional[str]:
        """Get Microsoft Graph client secret from environment variables."""
        secret = self.client_secret or self.custom_client_secret or self.graph_client_secret

        # If sharing credentials and graph secret is missing, try to use Azure secret
        if self.share_app_registration and not secret and self.azure_client_secret:
            return self.azure_client_secret.get_secret_value()

        return secret.get_secret_value() if secret is not None else None

    def get_graph_auth_profile(self) -> GraphAuthProfile:
        """Resolve Graph settings into a typed authentication profile."""
        config = self.get_graph_auth_config()
        scopes = tuple(str(scope) for scope in config["scopes"])
        if config["mode"] == "managed_identity":
            return ManagedIdentityProfile(client_id=config["client_id"], scopes=scopes)
        if config["mode"] == "custom":
            secret = self.get_graph_client_secret()
            if secret is None:
                # Keep the profile typed while allowing the service to return its guided error.
                secret = ""
            return ServicePrincipalProfile(
                tenant_id=str(config["tenant_id"]),
                client_id=str(config["client_id"]),
                client_secret=secret,
                scopes=scopes,
            )
        return DeviceCodeProfile(
            tenant_id=str(config["tenant_id"]),
            client_id=str(config["client_id"]),
            scopes=scopes,
        )

    def build_execution_policy(self) -> ExecutionPolicy:
        """Build the immutable policy shared by both execution services."""
        return ExecutionPolicy(
            mode=self.execution_policy,
            azure_allowlist=tuple(self.azure_command_allowlist),
            graph_allowlist=tuple(self.graph_request_allowlist),
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_graph_read_only_mode(self) -> bool:
        """Check if running Microsoft Graph in read-only mode."""
        if self.use_managed_identity:
            return False
        client_id = self.use_app_reg_clientid or self.custom_client_id
        tenant_id = self.tenantid or self.custom_tenant_id

        # If sharing credentials, check if we have Azure creds
        if self.share_app_registration:
            if not client_id and self.azure_client_id:
                client_id = self.azure_client_id
            if not tenant_id and self.azure_tenant_id:
                tenant_id = self.azure_tenant_id

        return not (client_id and tenant_id)
