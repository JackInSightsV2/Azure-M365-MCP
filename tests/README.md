# Unified Microsoft MCP Server - Test Suite

This directory contains the comprehensive test suite for the Unified Microsoft MCP Server. The tests cover unit functionality for services and integration tests for server operations and startup modes.

## Directory Structure

```text
tests/
├── unit/                       # Unit tests for individual components
│   ├── test_config.py          # Configuration and environment variable tests
│   ├── test_azure_cli_service.py # Azure CLI command validation and execution
│   └── test_graph_service.py   # Microsoft Graph API interaction and auth
├── integration/                # Integration tests for server behavior
│   ├── test_server.py          # MCP tool handler tests (mocked services)
│   └── test_startup.py         # Server startup mode tests (stdio, sse, openapi)
├── docker-compose.test.yml     # Docker Compose setup for integration testing
├── env.test                    # Environment variables for Docker tests
└── conftest.py                 # Shared Pytest fixtures and mocks
```

## Running Tests

Ensure you have installed the development dependencies:

```bash
pip install -r requirements.txt
```

Run the full test suite:

```bash
pytest
```

Run verbose output to see individual test names:

```bash
pytest -v
```

## Docker Integration Testing

You can run the full application stack in "Mock Mode" using Docker Compose. This allows you to test the server, API, and transport layers (SSE, OpenAPI) without requiring real Azure credentials or external connectivity.

### How Mock Mode Works

When `MOCK_MODE=true` is set (via `env.test`):
*   **Azure CLI Service**: Bypasses authentication and returns predefined JSON responses for common commands (`az login`, `az account list`, `az group list`).
*   **Graph Service**: Bypasses Azure Identity authentication and returns predefined JSON responses for common endpoints (`me`, `users`).

### Starting the Test Stack

```bash
cd tests
docker-compose -f docker-compose.test.yml --env-file env.test up --build
```

This will start 3 containers:
1.  **mcp-test-sse**: Running in SSE mode (Port 8000)
2.  **mcp-test-openapi**: Running in OpenAPI/REST mode (Port 8001)
3.  **mcp-test-stdio**: Running in Stdio mode (for interactive attachment)

You can verify they are running:
```bash
curl http://localhost:8001/docs
```

## Test Coverage

### 1. Configuration (`tests/unit/test_config.py`)
*   **Settings Defaults**: Verifies safe default values (INFO logging, stdio transport).
*   **Validation**: checks log level validation and fallback logic.
*   **Azure Credentials**: Parses `AZURE_APP_*` environment variables into credential objects.
*   **Graph Auth Config**: Tests automatic switching between **Read-Only** (Device Code) and **Read/Write** (Client Secret) modes based on configuration.

### 2. Azure CLI Service (`tests/unit/test_azure_cli_service.py`)
*   **Command Validation**: Security check ensuring only `az` commands are allowed.
*   **Sanitization**: Verifies dangerous shell characters (`;`, `&`, `|`) are stripped.
*   **Execution**: Mocks subprocess calls to test successful output and error handling for non-zero exit codes.

### 3. Graph Service (`tests/unit/test_graph_service.py`)
*   **Authentication**: Tests handling of missing client secrets and token acquisition failures.
*   **HTTP Methods**: Verifies `GET` and `POST` requests are constructed correctly.
*   **Error Handling**: Ensures API errors (e.g., 404, 401) are caught and formatted as readable responses.

### 4. Integration Tests (`tests/integration/`)
*   **Server Handlers (`test_server.py`)**: Tests the `execute_azure_cli_command` and `graph_command` tool handlers directly, verifying that arguments are correctly passed to the underlying services.
*   **Startup Modes (`test_startup.py`)**: Verifies the application initializes correctly in all three transport modes:
    *   **Stdio**: Default mode for local MCP clients.
    *   **SSE**: Server-Sent Events mode for remote connections.
    *   **OpenAPI**: HTTP API mode for direct REST access.

## Mocks and Fixtures

*   **`conftest.py`**: Provides shared mocks for `Settings`, `AzureCliService`, and `GraphService` to isolate tests from the production environment.
*   **Service Mocking**: The tests use `unittest.mock` (including `AsyncMock`) to simulate network calls (Azure API, Graph API) and system operations (subprocess), ensuring tests are fast and reliable without requiring real credentials.
