"""Typed authentication profiles and Microsoft Graph token lifecycle management."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, TypeAlias, cast

from azure.core.credentials import AccessToken
from azure.identity import (
    DeviceCodeCredential,
    InteractiveBrowserCredential,
    TokenCachePersistenceOptions,
)
from azure.identity.aio import ClientSecretCredential, ManagedIdentityCredential

from unified_mcp.token_cache import load_auth_record, save_auth_record

# Shared name for the on-disk MSAL token cache. Device-code profiles for different
# client ids (for example Graph and Azure Resource Manager) coexist in one cache as
# separate accounts, so a single name is correct.
TOKEN_CACHE_NAME = "unified-microsoft-mcp.cache"


def pending_sign_in_response(profile: object) -> dict[str, Any] | None:
    """Tell the user to finish a browser sign-in that is still in progress."""
    if not getattr(profile, "use_browser", False):
        return None
    return {
        "success": False,
        "error": "Browser sign-in required",
        "auth_required": True,
        "instructions": (
            "A browser window has opened for Microsoft sign-in. Complete sign-in there, "
            "then retry the request."
        ),
    }


@dataclass(frozen=True)
class InteractiveAzureProfile:
    """Azure CLI profile that uses the user's existing cache or device login."""

    kind: str = "interactive"


@dataclass(frozen=True)
class ServicePrincipalProfile:
    """Application identity authenticated by tenant, client ID, and secret."""

    tenant_id: str
    client_id: str
    client_secret: str
    scopes: tuple[str, ...] = ()
    kind: str = "service_principal"


@dataclass(frozen=True)
class ManagedIdentityProfile:
    """System- or user-assigned Azure managed identity."""

    client_id: str | None = None
    scopes: tuple[str, ...] = ()
    kind: str = "managed_identity"


@dataclass(frozen=True)
class DeviceCodeProfile:
    """Delegated (user) authentication by Interactive sign-in.

    ``use_browser`` opens a browser window with a localhost redirect, the same flow as
    ``az login`` and ``Connect-AzAccount``; otherwise a device code is shown, for hosts
    without a browser. When ``cache_enabled`` is set and ``auth_record_path`` points to
    a writable location, the sign-in is persisted so subsequent runs refresh silently
    instead of prompting again.
    """

    tenant_id: str
    client_id: str
    scopes: tuple[str, ...]
    cache_enabled: bool = True
    auth_record_path: str | None = None
    use_browser: bool = False
    kind: str = "device_code"


AzureAuthProfile: TypeAlias = (
    InteractiveAzureProfile | ServicePrincipalProfile | ManagedIdentityProfile
)
GraphAuthProfile: TypeAlias = DeviceCodeProfile | ServicePrincipalProfile | ManagedIdentityProfile


class TokenCredential(Protocol):
    """Small credential seam used by the token broker and its tests."""

    def get_token(self, *scopes: str) -> AccessToken: ...


class AsyncTokenCredential(Protocol):
    """Asynchronous credential seam used by managed and application identities."""

    async def get_token(self, *scopes: str) -> AccessToken: ...


CredentialFactory = Callable[[GraphAuthProfile, Callable[[str, str, datetime], None]], Any]


class TokenBroker:
    """Own one credential and one in-flight token request for a Graph service."""

    def __init__(
        self,
        profile: GraphAuthProfile,
        device_code_callback: Callable[[str, str, datetime], None],
        credential_factory: CredentialFactory | None = None,
    ) -> None:
        self.profile = profile
        self._device_code_callback = device_code_callback
        self._credential_factory = credential_factory or self._create_credential
        self._credential: Any | None = None
        self._token_task: asyncio.Task[AccessToken] | None = None
        self._cached_token: AccessToken | None = None
        self._auth_record_saved = False
        self._lock = asyncio.Lock()

    @property
    def scopes(self) -> Sequence[str]:
        """Return the immutable scopes associated with the profile."""
        return self.profile.scopes

    @property
    def is_application_identity(self) -> bool:
        """Whether the token represents an application rather than a user."""
        return not isinstance(self.profile, DeviceCodeProfile)

    def _create_credential(
        self,
        profile: GraphAuthProfile,
        callback: Callable[[str, str, datetime], None],
    ) -> Any:
        if isinstance(profile, DeviceCodeProfile):
            options: dict[str, Any] = {}
            if profile.cache_enabled:
                options["cache_persistence_options"] = TokenCachePersistenceOptions(
                    name=TOKEN_CACHE_NAME,
                    allow_unencrypted_storage=True,
                )
                record = load_auth_record(profile.auth_record_path)
                if record is not None:
                    options["authentication_record"] = record
            if profile.use_browser:
                return InteractiveBrowserCredential(
                    tenant_id=profile.tenant_id,
                    client_id=profile.client_id,
                    **options,
                )
            return DeviceCodeCredential(
                tenant_id=profile.tenant_id,
                client_id=profile.client_id,
                prompt_callback=callback,
                **options,
            )
        if isinstance(profile, ServicePrincipalProfile):
            return ClientSecretCredential(
                tenant_id=profile.tenant_id,
                client_id=profile.client_id,
                client_secret=profile.client_secret,
            )
        return ManagedIdentityCredential(client_id=profile.client_id)

    async def _acquire_token(self) -> AccessToken:
        if self._credential is None:
            self._credential = self._credential_factory(
                self.profile,
                self._device_code_callback,
            )
        get_token = self._credential.get_token
        if inspect.iscoroutinefunction(get_token):
            token = cast(AccessToken, await get_token(*self.scopes))
        else:
            token = cast(AccessToken, await asyncio.to_thread(get_token, *self.scopes))
        self._persist_auth_record()
        return token

    def _persist_auth_record(self) -> None:
        """Persist the device-code authentication record once, enabling silent refresh."""
        profile = self.profile
        if (
            self._auth_record_saved
            or not isinstance(profile, DeviceCodeProfile)
            or not profile.cache_enabled
            or profile.auth_record_path is None
        ):
            return
        record = getattr(self._credential, "_auth_record", None)
        if record is None:
            return
        save_auth_record(profile.auth_record_path, record)
        self._auth_record_saved = True

    async def get_token(self, prompt_timeout: float = 3.0) -> AccessToken:
        """Get a token, preserving device authentication after the prompt is returned."""
        async with self._lock:
            if self._cached_token is not None and self._cached_token.expires_on > time.time() + 60:
                return self._cached_token
            if self._token_task is None:
                self._token_task = asyncio.create_task(self._acquire_token())
            task = self._token_task

        try:
            if isinstance(self.profile, DeviceCodeProfile):
                token = await asyncio.wait_for(asyncio.shield(task), timeout=prompt_timeout)
            else:
                token = await task
        except asyncio.TimeoutError:
            # Shielding is intentional: the user can complete the same device flow and retry.
            raise
        except asyncio.CancelledError:
            # Application credential tasks are cancelled with their caller. Device-code tasks
            # are shielded and must remain available for the user's in-progress sign-in.
            if task.cancelled():
                async with self._lock:
                    if self._token_task is task:
                        self._token_task = None
            raise
        except Exception:
            async with self._lock:
                if self._token_task is task:
                    self._token_task = None
            raise
        else:
            # Reuse valid tokens; ask the credential to refresh once the safety window is reached.
            async with self._lock:
                self._cached_token = token
                if self._token_task is task:
                    self._token_task = None
            return token

    async def close(self) -> None:
        """Cancel pending work and release credential resources."""
        task = self._token_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._token_task = None
        self._cached_token = None

        credential = self._credential
        self._credential = None
        if credential is not None and hasattr(credential, "close"):
            result = credential.close()
            if inspect.isawaitable(result):
                await result
