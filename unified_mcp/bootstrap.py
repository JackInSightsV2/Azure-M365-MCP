"""One-time helper that provisions a service principal from an interactive sign-in.

Run this in a terminal (not through the AI client) so the generated secret is printed
only to your own screen. It converts an existing ``az login`` session into a headless
identity you can hand to the MCP server via ``AZURE_APP_*`` environment variables.

Requirements and caveats, stated plainly:

* You must be signed in with rights to create app registrations (Application
  Administrator or higher) and to assign the requested role on the target scope
  (Owner or User Access Administrator).
* ``az ad sp create-for-rbac`` grants **Azure Resource Manager** RBAC only. Microsoft
  Graph *application* permissions are separate and require admin consent; this script
  does not grant them.
* The printed secret is long-lived and bypasses MFA. Store it in a secret manager,
  scope the role tightly, and rotate it. Prefer a managed identity where possible.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Optional

from unified_mcp.cli_tools import ToolLocator
from unified_mcp.config import Settings


def _run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    # az on PATH first, else the Azure CLI installed with this package.
    arguments, env = ToolLocator(Settings().tools_directory()).prepare(arguments)
    return subprocess.run(arguments, capture_output=True, text=True, check=False, env=env)


def _current_subscription() -> Optional[dict]:
    result = _run(["az", "account", "show", "-o", "json"])
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _ensure_login() -> Optional[dict]:
    account = _current_subscription()
    if account is not None:
        return account
    print("No active Azure session. Starting device-code sign-in...\n", file=sys.stderr)
    login = _run(["az", "login", "--use-device-code"])
    if login.returncode != 0:
        print(f"Sign-in failed:\n{login.stderr or login.stdout}", file=sys.stderr)
        return None
    return _current_subscription()


def _create_service_principal(name: str, role: str, scope: str, years: int) -> Optional[dict]:
    print(
        f"Creating service principal '{name}' with role '{role}' on {scope}...",
        file=sys.stderr,
    )
    result = _run(
        [
            "az",
            "ad",
            "sp",
            "create-for-rbac",
            "--name",
            name,
            "--role",
            role,
            "--scopes",
            scope,
            "--years",
            str(years),
            "-o",
            "json",
        ]
    )
    if result.returncode != 0:
        print(
            f"Failed to create service principal:\n{result.stderr or result.stdout}",
            file=sys.stderr,
        )
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"Unexpected output from Azure CLI:\n{result.stdout}", file=sys.stderr)
        return None
    return data if isinstance(data, dict) else None


def _print_env_block(credentials: dict, subscription_id: str) -> None:
    tenant = credentials.get("tenant", "")
    client_id = credentials.get("appId", "")
    secret = credentials.get("password", "")
    print("\n" + "=" * 70)
    print("Service principal created. Set these in the MCP server environment:")
    print("=" * 70)
    print(f"AZURE_APP_TENANT_ID={tenant}")
    print(f"AZURE_APP_CLIENT_ID={client_id}")
    print(f"AZURE_APP_CLIENT_SECRET={secret}")
    print(f"AZURE_SUBSCRIPTION_ID={subscription_id}")
    print("=" * 70)
    print(
        "\nTo reuse this identity for Microsoft Graph, also set SHARE_APP_REGISTRATION=true "
        "AFTER granting the app the required Graph application permissions and admin consent "
        "in Microsoft Entra ID. RBAC alone does not grant Graph access."
    )
    print(
        "\nThe secret above is shown only once and bypasses MFA. Store it in a secret "
        "manager, keep the role tightly scoped, and rotate it before it expires."
    )


def main() -> int:
    """Entry point for the ``unified-microsoft-mcp-bootstrap-spn`` console script."""
    parser = argparse.ArgumentParser(
        prog="unified-microsoft-mcp-bootstrap-spn",
        description="Provision a service principal from an interactive Azure sign-in.",
    )
    parser.add_argument(
        "--name",
        default="unified-microsoft-mcp",
        help="Display name for the app registration (default: unified-microsoft-mcp).",
    )
    parser.add_argument(
        "--role",
        default="Reader",
        help="RBAC role to assign (default: Reader). Use a tightly scoped role.",
    )
    parser.add_argument(
        "--scope",
        default=None,
        help="Resource scope for the role. Defaults to the current subscription.",
    )
    parser.add_argument(
        "--years",
        type=int,
        default=1,
        help="Secret lifetime in years (default: 1).",
    )
    arguments = parser.parse_args()

    account = _ensure_login()
    if account is None:
        return 1

    subscription_id = account.get("id", "")
    scope = arguments.scope or f"/subscriptions/{subscription_id}"

    credentials = _create_service_principal(arguments.name, arguments.role, scope, arguments.years)
    if credentials is None:
        return 1

    _print_env_block(credentials, subscription_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
