# Test suite

Tests cover configuration, Azure CLI execution, Graph authentication and HTTP behavior, HTTP security, MCP handlers, startup modes, and the container stack.

Install the development dependencies and run the normal suite:

```bash
python -m pip install -e ".[dev]"
pytest -m "not docker"
```

Run all static checks:

```bash
black --check unified_mcp tests
ruff check unified_mcp tests
mypy unified_mcp
```

Docker tests build four mock-mode containers, so Azure credentials are not required:

```bash
pytest -m docker
```

The stack publishes Streamable HTTP on port 18080, OpenAPI on port 18081, SSE on port 18082, and also exercises stdio. See [README_DOCKER_TEST.md](README_DOCKER_TEST.md) for direct Compose commands.
