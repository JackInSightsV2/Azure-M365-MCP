#!/usr/bin/env python3
"""Composition root for the Unified Microsoft MCP Server."""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from unified_mcp.application import ToolApplication, process_tool_call
from unified_mcp.config import Settings
from unified_mcp.services.azure_cli_service import AzureCliService
from unified_mcp.services.graph_service import GraphService
from unified_mcp.transports import create_mcp_server, run_transport

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

__all__ = ["main", "process_tool_call", "run"]


def configure_logging(settings: Settings) -> None:
    """Configure one stderr and one optional file handler."""
    log_level = getattr(logging, settings.log_level, logging.INFO)
    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers = [
        handler for handler in root.handlers if not isinstance(handler, logging.FileHandler)
    ]

    log_directory = os.path.dirname(settings.log_file)
    if log_directory:
        os.makedirs(log_directory, exist_ok=True)
    file_handler = logging.FileHandler(settings.log_file)
    file_handler.setLevel(log_level)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    root.addHandler(file_handler)

    stderr_handlers = [
        handler
        for handler in root.handlers
        if isinstance(handler, logging.StreamHandler) and handler.stream == sys.stderr
    ]
    if not stderr_handlers:
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(log_level)
        stderr_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        root.addHandler(stderr_handler)
    for handler in stderr_handlers:
        handler.setLevel(log_level)


def build_application(settings: Settings) -> ToolApplication:
    """Compose real adapters, or explicit fakes for requested test mode."""
    if settings.mock_mode:
        from unified_mcp.testing import FakeAzureCliService, FakeGraphService

        logger.warning("MOCK_MODE enabled: using deterministic test adapters")
        return ToolApplication(FakeAzureCliService(), FakeGraphService())

    policy = settings.build_execution_policy()
    return ToolApplication(
        AzureCliService(settings, policy=policy),
        GraphService(settings, policy=policy),
    )


def log_runtime_configuration(settings: Settings) -> None:
    """Log transport security and non-interactive authentication risks consistently."""
    logger.info("MCP transport: %s", settings.mcp_transport)
    logger.info("Execution policy: %s", settings.execution_policy.value)
    if settings.mcp_transport == "stdio":
        return
    if settings.mcp_api_key is None:
        logger.warning(
            "HTTP transport has no MCP_API_KEY; bind only to loopback or a trusted network"
        )
    if not settings.use_managed_identity and not settings.has_azure_credentials():
        logger.warning(
            "Azure CLI has no non-interactive identity; remote calls may require device login"
        )
    if settings.is_graph_read_only_mode:
        logger.warning(
            "Microsoft Graph uses device authentication; configure an application identity "
            "for unattended HTTP deployment"
        )


async def main() -> None:
    """Build the application, run its transport, and close every owned resource."""
    settings = Settings()
    configure_logging(settings)
    application = build_application(settings)
    server = create_mcp_server(settings, application)
    log_runtime_configuration(settings)
    try:
        await run_transport(settings, server, application)
    finally:
        await application.close()


def run() -> None:
    """Run the asynchronous server from console-script and module entry points."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")


if __name__ == "__main__":
    run()
