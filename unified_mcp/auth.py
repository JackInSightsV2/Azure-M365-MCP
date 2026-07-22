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
from azure.identity import DeviceCodeCredential
from azure.identity.aio import ClientSecretCredential, ManagedIdentityCredential


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
    """Delegated Microsoft Graph authentication using a device code."""

    tenant_id: str
    client_id: str
    scopes: tuple[str, ...]
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
            return DeviceCodeCredential(
                tenant_id=profile.tenant_id,
                client_id=profile.client_id,
                prompt_callback=callback,
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
            return cast(AccessToken, await get_token(*self.scopes))
        return cast(AccessToken, await asyncio.to_thread(get_token, *self.scopes))

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
