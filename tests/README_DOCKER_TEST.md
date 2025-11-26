# Test Environment Setup

This directory contains configuration for running the Unified MCP Server in a test environment with all three modes (SSE, OpenAPI, Stdio) running simultaneously.

## Prerequisites

- Docker
- Docker Compose

## Quick Start

1. **Navigate to the tests directory:**
   ```bash
   cd tests
   ```

2. **Start the containers:**
   ```bash
   docker-compose -f docker-compose.test.yml --env-file .env.test up -d --build
   ```

3. **Verify running services:**
   ```bash
   docker ps
   ```
   You should see 3 containers: `mcp-test-sse`, `mcp-test-openapi`, and `mcp-test-stdio`.

## Access Points

| Service | Mode | Port | URL / Access |
|---------|------|------|--------------|
| **mcp-sse** | SSE (MCP over HTTP) | 8000 | `http://localhost:8000/sse` |
| **mcp-openapi** | OpenAPI (REST) | 8001 | `http://localhost:8001/docs` |
| **mcp-stdio** | Stdio (Stream) | 8002 | Access logs or attach: `docker attach mcp-test-stdio` |

## Stopping the Environment

To stop and remove the containers:
```bash
docker-compose -f docker-compose.test.yml down
```

