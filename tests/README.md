# Test suite

Tests cover configuration, Azure CLI execution, Graph authentication and HTTP behavior, HTTP security, MCP handlers, startup modes, and the HTTP transports.

Install the development dependencies and run the suite:

```bash
python -m pip install -e ".[dev]"
pytest
```

Run all static checks:

```bash
black --check unified_mcp tests
ruff check unified_mcp tests
mypy unified_mcp
```
