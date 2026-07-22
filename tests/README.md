# Test suite

Tests cover configuration, Azure CLI execution, Graph authentication and HTTP behavior, HTTP security, MCP handlers, startup modes, and the container stack.

Install the locked development environment and run the normal suite:

```bash
poetry install
poetry run pytest -m "not docker"
```

Run all static checks:

```bash
poetry run black --check unified_mcp tests
poetry run ruff check unified_mcp tests
poetry run mypy unified_mcp
```

Docker tests build three mock-mode containers, so Azure credentials are not required:

```bash
poetry run pytest -m docker
```

The stack publishes Streamable HTTP on port 18080, OpenAPI on port 18081, and also exercises stdio. See [README_DOCKER_TEST.md](README_DOCKER_TEST.md) for direct Compose commands.
