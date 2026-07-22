# Docker test environment

The test Compose stack runs three mock-mode services without Azure credentials:

| Service | Transport | Access |
| --- | --- | --- |
| `mcp-test-http` | Streamable HTTP | `http://127.0.0.1:18080/mcp` |
| `mcp-test-openapi` | OpenAPI | `http://127.0.0.1:18081/docs` |
| `mcp-test-stdio` | stdio | container streams |

Start and inspect the stack:

```bash
cd tests
docker compose -f docker-compose.test.yml up -d --build
docker compose -f docker-compose.test.yml ps
curl http://127.0.0.1:18080/health
curl http://127.0.0.1:18081/health
```

Stop it with:

```bash
docker compose -f docker-compose.test.yml down
```
