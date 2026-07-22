"""Small ASGI security boundary shared by the HTTP transports."""

import hmac

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class HttpSecurityMiddleware:
    """Validate browser origins and, when configured, a bearer API key."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        api_key: str | None,
        allowed_origins: list[str],
        public_paths: set[str] | None = None,
    ) -> None:
        self.app = app
        self.api_key = api_key
        self.allowed_origins = set(allowed_origins)
        self.public_paths = public_paths or set()

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        path = scope.get("path")
        if path == "/health":
            await JSONResponse({"status": "ok"})(scope, receive, send)
            return

        if path in self.public_paths:
            await self.app(scope, receive, send)
            return

        origin = headers.get(b"origin")
        if origin is not None and origin.decode("latin-1") not in self.allowed_origins:
            await JSONResponse({"detail": "Origin not allowed"}, status_code=403)(
                scope, receive, send
            )
            return

        if self.api_key:
            authorization = headers.get(b"authorization", b"").decode("latin-1")
            expected = f"Bearer {self.api_key}"
            if not hmac.compare_digest(authorization, expected):
                await JSONResponse(
                    {"detail": "Missing or invalid bearer token"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )(scope, receive, send)
                return

        await self.app(scope, receive, send)
