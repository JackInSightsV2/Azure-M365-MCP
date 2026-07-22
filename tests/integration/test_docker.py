import asyncio
import shutil
import subprocess
import time

import httpx
import pytest

pytestmark = pytest.mark.docker


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
    if (
        shutil.which("docker")
        and subprocess.run(
            ["docker", "compose", "version"], capture_output=True, check=False
        ).returncode
        == 0
    ):
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
    # Build docker compose command
    compose_args = compose_cmd + ["-f", "tests/docker-compose.test.yml", "up", "-d", "--build"]

    # Start docker-compose
    result = subprocess.run(compose_args, check=False, capture_output=True, text=True)

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
        capture_output=True,
    )


@pytest.mark.asyncio
async def test_openapi_container_health(docker_compose_env):
    """Test the OpenAPI container is running and healthy."""
    # The healthcheck endpoint is typically /docs or /health (if implemented)
    # Using /docs as configured in healthcheck
    url = "http://localhost:18081/health"
    is_ready = await wait_for_service(url)
    assert is_ready, "OpenAPI container did not become ready"


@pytest.mark.asyncio
async def test_openapi_azure_cli_mock(docker_compose_env):
    """Test Azure CLI mock endpoint on the running container."""
    url = "http://localhost:18081/execute-azure-cli"
    payload = {"command": "az account list"}

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)

        assert (
            response.status_code == 200
        ), f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "result" in data, f"Response missing 'result' key: {data}"

        result = data["result"]
        assert isinstance(result, list)
        assert result[0]["name"] == "Fake Subscription"


@pytest.mark.asyncio
async def test_openapi_graph_mock(docker_compose_env):
    """Test Graph API mock endpoint on the running container."""
    url = "http://localhost:18081/execute-graph-command"
    payload = {"command": "me", "method": "GET"}

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)

        assert (
            response.status_code == 200
        ), f"Expected 200, got {response.status_code}: {response.text}"
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
        assert (
            data["data"].get("displayName") == "Mock User"
        ), f"Expected displayName='Mock User', got: {data.get('data', {})}"


@pytest.mark.asyncio
async def test_streamable_http_container_health(docker_compose_env):
    """Test the Streamable HTTP container is accessible."""
    assert await wait_for_service("http://localhost:18080/health")
