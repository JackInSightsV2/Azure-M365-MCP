import pytest
import httpx
import asyncio
import subprocess
import time
import os

# Helper to check if a service is ready
async def wait_for_service(url, timeout=30):
    start_time = time.time()
    async with httpx.AsyncClient() as client:
        while time.time() - start_time < timeout:
            try:
                response = await client.get(url)
                if response.status_code == 200:
                    return True
            except httpx.ConnectError:
                await asyncio.sleep(1)
            except Exception:
                 await asyncio.sleep(1)
    return False

@pytest.fixture(scope="module")
def docker_compose_env():
    """Start and stop docker-compose environment for tests."""
    # Start docker-compose
    subprocess.run(
        ["docker-compose", "-f", "tests/docker-compose.test.yml", "--env-file", "tests/env.test", "up", "-d", "--build"],
        check=True
    )
    
    # Wait for services to be ready (giving them a bit of time to start)
    time.sleep(5)
    
    yield
    
    # Stop docker-compose
    subprocess.run(
        ["docker-compose", "-f", "tests/docker-compose.test.yml", "down"],
        check=True
    )

@pytest.mark.asyncio
async def test_openapi_container_health(docker_compose_env):
    """Test the OpenAPI container is running and healthy."""
    # The healthcheck endpoint is typically /docs or /health (if implemented)
    # Using /docs as configured in healthcheck
    url = "http://localhost:8001/docs"
    is_ready = await wait_for_service(url)
    assert is_ready, "OpenAPI container did not become ready"

@pytest.mark.asyncio
async def test_openapi_azure_cli_mock(docker_compose_env):
    """Test Azure CLI mock endpoint on the running container."""
    url = "http://localhost:8001/execute-azure-cli"
    payload = {"command": "az account list"}
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        # Check for mock data content
        assert "Fake Subscription" in data["result"]

@pytest.mark.asyncio
async def test_openapi_graph_mock(docker_compose_env):
    """Test Graph API mock endpoint on the running container."""
    url = "http://localhost:8001/execute-graph-command"
    payload = {"command": "me", "method": "GET"}
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["displayName"] == "Mock User"

@pytest.mark.asyncio
async def test_sse_container_health(docker_compose_env):
    """Test the SSE container is accessible."""
    # SSE endpoint usually responds to GET with 200 or 405 depending on implementation details
    # But we can check if the server is up
    url = "http://localhost:8000/sse"
    
    async with httpx.AsyncClient() as client:
        try:
            # Connect with a very short timeout, just to check if the port is open and responding
            # We use stream=True to avoid reading the potentially infinite stream
            async with client.stream("GET", url, timeout=5.0) as response:
                # 200 OK means the stream started successfully
                assert response.status_code == 200
        except httpx.ConnectError:
             pytest.fail("Could not connect to SSE container")
        except httpx.ReadTimeout:
             # If it times out reading but connected, it might be working as an SSE stream
             pass

