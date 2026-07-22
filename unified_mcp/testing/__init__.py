"""Explicit test adapters selected only when MOCK_MODE is enabled."""

from unified_mcp.testing.fakes import FakeAzureCliService, FakeGraphService

__all__ = ["FakeAzureCliService", "FakeGraphService"]
