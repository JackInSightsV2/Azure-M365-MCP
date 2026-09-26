"""Explicit test adapters selected only when MOCK_MODE is enabled."""

from unified_mcp.testing.fakes import (
    FakeAzureCliService,
    FakeAzureRestService,
    FakeGraphService,
    FakeProcessRunner,
)

__all__ = ["FakeAzureCliService", "FakeAzureRestService", "FakeGraphService", "FakeProcessRunner"]
