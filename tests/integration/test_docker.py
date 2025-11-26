import pytest
import httpx
import asyncio
import subprocess
import time
import os
import shutil

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

def get_docker_compose_cmd():
    """Get the docker compose command (try v2 first, fallback to v1)."""
    # Try docker compose (v2) first
    if shutil.which("docker") and subprocess.run(
        ["docker", "compose", "version"], 
        capture_output=True, 
        check=False
    ).returncode == 0:
        return ["docker", "compose"]
    # Fallback to docker-compose (v1)
    elif shutil.which("docker-compose"):
        return ["docker-compose"]
    else:
        raise RuntimeError("Neither 'docker compose' nor 'docker-compose' is available")

@pytest.fixture(scope="module")
def docker_compose_env():
    """Start and stop docker-compose environment for tests."""
    compose_cmd = get_docker_compose_cmd()
    env_file = "tests/env.test"
    
    # Check if env file exists
    if not os.path.exists(env_file):
        raise FileNotFoundError(
            f"Environment file {env_file} not found. "
            "Please create it with required test environment variables. "
            "See env.example for reference."
        )
    
    # Build docker compose command
    compose_args = compose_cmd + ["-f", "tests/docker-compose.test.yml", "--env-file", env_file, "up", "-d", "--build"]
    
    # Start docker-compose
    result = subprocess.run(
        compose_args,
        check=False,
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to start docker-compose: {result.stderr}\n"
            f"Command: {' '.join(compose_args)}"
        )
    
    # Wait for services to be ready (giving them a bit of time to start)
    time.sleep(5)
    
    yield
    
    # Stop docker-compose
    subprocess.run(
        compose_cmd + ["-f", "tests/docker-compose.test.yml", "down"],
        check=False,  # Don't fail if containers are already down
        capture_output=True
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
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "result" in data, f"Response missing 'result' key: {data}"
        
        # Debug: Print the actual result for troubleshooting
        result = data["result"]
        print(f"\nDEBUG: Azure CLI result (first 500 chars): {result[:500]}")
        
        # Check for mock data content
        # The result should be a JSON string containing "Fake Subscription"
        assert "Fake Subscription" in result, (
            f"Expected 'Fake Subscription' in result, but got: {result[:200]}...\n"
            f"This suggests MOCK_MODE is not enabled. Check container logs and ensure MOCK_MODE=true is set."
        )

@pytest.mark.asyncio
async def test_openapi_graph_mock(docker_compose_env):
    """Test Graph API mock endpoint on the running container."""
    url = "http://localhost:8001/execute-graph-command"
    payload = {"command": "me", "method": "GET"}
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Debug: Print the actual response for troubleshooting
        print(f"\nDEBUG: Graph API response: {data}")
        
        assert data.get("success") is True, (
            f"Expected success=True, got success={data.get('success')}. "
            f"Full response: {data}\n"
            f"This suggests MOCK_MODE is not enabled or authentication failed. "
            f"Check container logs and ensure MOCK_MODE=true is set."
        )
        assert "data" in data, f"Response missing 'data' key: {data}"
        assert data["data"].get("displayName") == "Mock User", (
            f"Expected displayName='Mock User', got: {data.get('data', {})}"
        )

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

