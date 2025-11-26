"""Configuration management for Unified Microsoft MCP Server."""

import json
import os
from typing import Any, Dict, Optional

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings using Pydantic for both Azure CLI and Graph services."""

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
        frozen=True,  # Make settings immutable
        env_prefix="",
    )

    def __init__(self, **kwargs):
        """Initialize settings with debug logging."""
        import logging
        
        # Set up basic logging for debugging
        logging.basicConfig(level=logging.INFO)
        logger = logging.getLogger(__name__)
        
        # Debug: Show relevant environment variables
        logger.info("=== Unified MCP Environment Variables Debug ===")
        logger.info(f"AZURE_APP_TENANT_ID: {os.getenv('AZURE_APP_TENANT_ID', 'NOT SET')}")
        logger.info(f"AZURE_APP_CLIENT_ID: {os.getenv('AZURE_APP_CLIENT_ID', 'NOT SET')}")
        azure_secret_set = bool(os.getenv('AZURE_APP_CLIENT_SECRET'))
        logger.info(f"AZURE_APP_CLIENT_SECRET: {'SET' if azure_secret_set else 'NOT SET'}")
        logger.info(f"AZURE_SUBSCRIPTION_ID: {os.getenv('AZURE_SUBSCRIPTION_ID', 'NOT SET')}")
        
        # Graph-specific settings
        logger.info(f"GRAPH_TENANT_ID: {os.getenv('GRAPH_TENANT_ID', 'NOT SET')}")
        logger.info(f"GRAPH_CLIENT_ID: {os.getenv('GRAPH_CLIENT_ID', 'NOT SET')}")
        logger.info(f"GRAPH_APP_CLIENT_ID: {os.getenv('GRAPH_APP_CLIENT_ID', 'NOT SET')}")
        logger.info(f"GRAPH_APP_TENANT_ID: {os.getenv('GRAPH_APP_TENANT_ID', 'NOT SET')}")
        graph_secret_set = bool(os.getenv('GRAPH_APP_CLIENT_SECRET') or os.getenv('CLIENT_SECRET') or os.getenv('GRAPH_CLIENT_SECRET'))
        logger.info(f"GRAPH_APP_CLIENT_SECRET: {'SET' if graph_secret_set else 'NOT SET'}")
        
        # Shared App Registration
        share_app_reg = os.getenv('SHARE_APP_REGISTRATION', 'false').lower() == 'true'
        logger.info(f"SHARE_APP_REGISTRATION: {share_app_reg}")
        
        logger.info("===============================================")
        
        super().__init__(**kwargs)

    # Application settings
    app_name: str = "unified-microsoft-mcp"
    
    # Shared App Registration
    share_app_registration: bool = Field(default=False, alias="SHARE_APP_REGISTRATION")

    # =============================================================================
    # AZURE CLI SETTINGS
    # =============================================================================
    
    # Azure CLI credentials (for service principal authentication)
    azure_tenant_id: Optional[str] = Field(default=None, alias="AZURE_APP_TENANT_ID")
    azure_client_id: Optional[str] = Field(default=None, alias="AZURE_APP_CLIENT_ID")
    azure_client_secret: Optional[str] = Field(default=None, alias="AZURE_APP_CLIENT_SECRET")
    azure_subscription_id: Optional[str] = Field(default=None, alias="AZURE_SUBSCRIPTION_ID")

    # Command execution settings
    command_timeout: int = Field(default=300, ge=1, le=3600, alias="COMMAND_TIMEOUT")
    max_concurrent_commands: int = Field(default=5, ge=1, le=50, alias="MAX_CONCURRENT_COMMANDS")

    # =============================================================================
    # MICROSOFT GRAPH SETTINGS
    # =============================================================================
    
    # Microsoft Graph settings for user authentication (read-only mode)
    graph_tenant_id: Optional[str] = Field(default=None, alias="GRAPH_TENANT_ID")
    graph_client_id: str = Field(
        default="14d82eec-204b-4c2f-b7e8-296a70dab67e",  # Microsoft Graph PowerShell public client
        alias="GRAPH_CLIENT_ID"
    )
    
    # Custom app registration settings (optional - enables read/write mode)
    custom_client_id: Optional[str] = Field(default=None, alias="GRAPH_APP_CLIENT_ID")
    custom_tenant_id: Optional[str] = Field(default=None, alias="GRAPH_APP_TENANT_ID")
    custom_client_secret: Optional[str] = Field(default=None, alias="GRAPH_APP_CLIENT_SECRET")
    
    # Alternative environment variable names for MCP configuration
    use_app_reg_clientid: Optional[str] = Field(default=None, alias="USE_APP_REG_CLIENTID")
    tenantid: Optional[str] = Field(default=None, alias="TENANTID")
    client_secret: Optional[str] = Field(default=None, alias="CLIENT_SECRET")
    
    # Legacy naming (for backward compatibility)
    graph_client_secret: Optional[str] = Field(default=None, alias="GRAPH_CLIENT_SECRET")
    
    # Authentication mode for Graph API
    graph_auth_mode: str = Field(default="device_code", alias="GRAPH_AUTH_MODE")  # "device_code" or "client_secret"

    # Microsoft Graph scopes for broad access
    graph_scopes: list[str] = Field(
        default=[
            "https://graph.microsoft.com/User.Read",
            "https://graph.microsoft.com/Mail.ReadWrite",
            "https://graph.microsoft.com/Calendars.ReadWrite",
            "https://graph.microsoft.com/Files.ReadWrite",
            "https://graph.microsoft.com/Sites.ReadWrite.All",
            "https://graph.microsoft.com/Team.ReadBasic.All",
            "https://graph.microsoft.com/Channel.ReadBasic.All",
            "https://graph.microsoft.com/ChatMessage.Send",
            "https://graph.microsoft.com/User.ReadBasic.All",
            "https://graph.microsoft.com/Group.Read.All",
            "https://graph.microsoft.com/DeviceManagementManagedDevices.ReadWrite.All",
            "https://graph.microsoft.com/DeviceManagementConfiguration.ReadWrite.All",
            "https://graph.microsoft.com/DeviceManagementApps.ReadWrite.All",
            "https://graph.microsoft.com/SecurityEvents.Read.All",
        ],
        alias="GRAPH_SCOPES"
    )

    # Operation execution settings
    operation_timeout: int = Field(default=300, ge=1, le=3600, alias="OPERATION_TIMEOUT")
    max_concurrent_operations: int = Field(default=5, ge=1, le=50, alias="MAX_CONCURRENT_OPERATIONS")

    # =============================================================================
    # GENERAL MCP SETTINGS
    # =============================================================================
    
    # MCP settings
    mcp_server_enabled: bool = True
    mcp_transport: str = Field(default="stdio", alias="MCP_TRANSPORT")  # "stdio" or "sse"
    mcp_port: int = Field(default=8001, alias="MCP_PORT")
    mcp_server_name: str = "unified-microsoft-mcp"

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_file: str = Field(default="unified_mcp.log", alias="LOG_FILE")
    
    # Mock Mode for Testing
    mock_mode: bool = Field(default=False, alias="MOCK_MODE")

    # =============================================================================
    # VALIDATORS
    # =============================================================================

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
        valid_transports = ["stdio", "sse", "openapi"]
        v_lower = v.lower()
        if v_lower not in valid_transports:
            raise ValueError(
                f"Invalid MCP transport mode: '{v}'. Must be one of: {', '.join(valid_transports)}"
            )
        return v_lower

    @field_validator("graph_scopes")
    @classmethod
    def validate_graph_scopes(cls, v: list[str]) -> list[str]:
        """Validate Microsoft Graph scopes."""
        if isinstance(v, str):
            # If it's a string, split by comma
            return [scope.strip() for scope in v.split(",")]
        return v

    # =============================================================================
    # AZURE CLI METHODS
    # =============================================================================

    @computed_field
    def azure_credentials(self) -> Optional[Dict[str, Optional[str]]]:
        """Get Azure CLI credentials as a dictionary."""
        if self.has_azure_credentials():
            return {
                "tenant_id": self.azure_tenant_id,
                "client_id": self.azure_client_id,
                "client_secret": self.azure_client_secret,
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
                "clientSecret": self.azure_client_secret,
            }
            if self.azure_subscription_id:
                credentials["subscriptionId"] = self.azure_subscription_id
            return json.dumps(credentials)
        return None

    # =============================================================================
    # MICROSOFT GRAPH METHODS
    # =============================================================================

    def get_graph_auth_config(self) -> Dict[str, Any]:
        """Get Microsoft Graph authentication configuration."""
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
                "scopes": ["https://graph.microsoft.com/.default"],  # Read-only permissions
            }
        
        return config
    
    def get_graph_client_secret(self) -> Optional[str]:
        """Get Microsoft Graph client secret from environment variables."""
        secret = self.client_secret or self.custom_client_secret or self.graph_client_secret
        
        # If sharing credentials and graph secret is missing, try to use Azure secret
        if self.share_app_registration and not secret and self.azure_client_secret:
            return self.azure_client_secret
            
        return secret
    
    @computed_field
    @property
    def is_graph_read_only_mode(self) -> bool:
        """Check if running Microsoft Graph in read-only mode."""
        client_id = self.use_app_reg_clientid or self.custom_client_id
        tenant_id = self.tenantid or self.custom_tenant_id
        
        # If sharing credentials, check if we have Azure creds
        if self.share_app_registration:
            if not client_id and self.azure_client_id:
                client_id = self.azure_client_id
            if not tenant_id and self.azure_tenant_id:
                tenant_id = self.azure_tenant_id
            
        return not (client_id and tenant_id)


# Global settings instance
settings = Settings()
