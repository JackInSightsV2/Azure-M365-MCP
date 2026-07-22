from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from unified_mcp.security import HttpSecurityMiddleware


async def protected_endpoint(request):
    return JSONResponse({"status": "protected"})


def make_client(api_key: str | None = "test-key") -> TestClient:
    app = Starlette(routes=[Route("/protected", protected_endpoint)])
    secured_app = HttpSecurityMiddleware(
        app,
        api_key=api_key,
        allowed_origins=["http://localhost:8001"],
    )
    return TestClient(secured_app)


def test_health_is_public() -> None:
    response = make_client().get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_explicit_public_path_reaches_application() -> None:
    app = Starlette(routes=[Route("/docs", lambda _request: PlainTextResponse("docs"))])
    secured_app = HttpSecurityMiddleware(
        app,
        api_key="test-key",
        allowed_origins=["https://allowed.example"],
        public_paths={"/docs"},
    )

    response = TestClient(secured_app).get("/docs")

    assert response.status_code == 200
    assert response.text == "docs"


def test_bearer_token_is_required_when_configured() -> None:
    client = make_client()
    assert client.get("/protected").status_code == 401
    response = client.get("/protected", headers={"Authorization": "Bearer test-key"})
    assert response.status_code == 200


def test_untrusted_browser_origin_is_rejected() -> None:
    response = make_client(api_key=None).get(
        "/protected", headers={"Origin": "https://attacker.example"}
    )
    assert response.status_code == 403


def test_allowed_browser_origin_is_accepted() -> None:
    response = make_client(api_key=None).get(
        "/protected", headers={"Origin": "http://localhost:8001"}
    )
    assert response.status_code == 200
