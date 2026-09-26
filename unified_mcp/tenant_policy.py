"""Recognise sign-in refusals caused by Tenant policy and describe them plainly.

Microsoft Entra ID reports consent, app-approval, and Conditional Access refusals with
``AADSTS`` error codes. This module maps those codes to a message naming the refused
app (client ID) and what a tenant admin must approve. It only explains the refusal; it
never retries, switches app, or otherwise works around the policy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict

# Public client used by ``az login``; named when the Azure CLI's sign-in is refused.
AZURE_CLI_CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"

# AADSTS code -> (what the tenant refused, what to ask a tenant admin for).
_CONSENT = "grant admin consent for this app in Microsoft Entra ID"
_CONDITIONAL_ACCESS = (
    "review the Conditional Access policy that blocked this sign-in and allow it for "
    "this app, or confirm it is intentionally blocked"
)
POLICY_ERROR_CODES: dict[str, tuple[str, str]] = {
    "AADSTS65001": ("the app has not been granted consent in this tenant", _CONSENT),
    "AADSTS65004": ("consent to the app was declined", _CONSENT),
    "AADSTS90094": ("the app requires admin consent", _CONSENT),
    "AADSTS90095": ("the app requires admin consent", _CONSENT),
    "AADSTS900941": ("the app requires admin consent", _CONSENT),
    "AADSTS50105": (
        "your account is not assigned to the app",
        "assign your account to this app in Microsoft Entra ID (Enterprise applications)",
    ),
    "AADSTS7000112": (
        "the app is disabled in this tenant",
        "enable this app in Microsoft Entra ID (Enterprise applications)",
    ),
    "AADSTS53000": ("Conditional Access requires a compliant device", _CONDITIONAL_ACCESS),
    "AADSTS53001": ("Conditional Access requires a domain-joined device", _CONDITIONAL_ACCESS),
    "AADSTS53002": ("Conditional Access requires an approved client app", _CONDITIONAL_ACCESS),
    "AADSTS53003": ("Conditional Access blocked the sign-in", _CONDITIONAL_ACCESS),
    "AADSTS530032": ("a tenant security policy blocked the sign-in", _CONDITIONAL_ACCESS),
}

_CODE_PATTERN = re.compile(r"\bAADSTS\d+\b")
_GUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_CLIENT_ID_PATTERN = re.compile(
    r"(?:app(?:lication)?(?:[ _]?id)?|client[ _]?id)(?:\s+with\s+id)?[\s:=]*['\"]?(" + _GUID + ")",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TenantPolicyRefusal:
    """A sign-in refused by Tenant policy, with what an admin must approve."""

    code: str
    reason: str
    admin_action: str
    client_id: str | None

    @property
    def app_label(self) -> str:
        return f"app (client ID {self.client_id})" if self.client_id else "app"

    @property
    def message(self) -> str:
        return (
            f"Sign-in was refused by your organisation's Tenant policy ({self.code}): "
            f"{self.reason}. Refused {self.app_label}. Ask a tenant admin to "
            f"{self.admin_action}, then retry."
        )


def detect_tenant_policy_refusal(
    error: BaseException | str | None,
    client_id: str | None = None,
) -> TenantPolicyRefusal | None:
    """Return the refusal described by ``error``, or ``None`` for other failures.

    The client ID reported in the error text wins over ``client_id`` (the configured
    app), because it names the app Entra ID actually refused.
    """
    if error is None:
        return None
    text = str(error)
    for match in _CODE_PATTERN.finditer(text):
        entry = POLICY_ERROR_CODES.get(match.group(0))
        if entry is None:
            continue
        reported = _CLIENT_ID_PATTERN.search(text)
        return TenantPolicyRefusal(
            code=match.group(0),
            reason=entry[0],
            admin_action=entry[1],
            client_id=reported.group(1) if reported else client_id,
        )
    return None


def tenant_policy_response(refusal: TenantPolicyRefusal, details: str) -> Dict[str, Any]:
    """Build the structured failure returned by REST-style services."""
    return {
        "success": False,
        "error": refusal.message,
        "auth_required": True,
        "tenant_policy": True,
        "error_code": refusal.code,
        "client_id": refusal.client_id,
        "instructions": (
            f"Ask a tenant admin to {refusal.admin_action}. Sign-in will keep failing "
            "until they do."
        ),
        "error_details": details,
    }
