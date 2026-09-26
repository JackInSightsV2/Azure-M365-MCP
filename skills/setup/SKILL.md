---
name: setup
description: Connect this AI client to the user's Microsoft cloud (Microsoft 365, Entra ID, Azure). Installs the azure-m365 MCP server, completes an Interactive sign-in, and verifies with a "who am I" read. Use when the user asks to set up, install, connect, or sign in to Microsoft 365, Entra ID, or Azure, or when the microsoft365_* / azure_* tools are missing or not signed in.
---

# Set up the Microsoft cloud connection

Goal: an Out-of-the-box setup. Install the server, sign in, verify. Do each step in order and stop at the first failure you cannot fix.

## 1. Install

- **Claude Code with this plugin**: nothing to install. The plugin already provides the `azure-m365` server. If the `microsoft365_read` tool is not available, ask the user to run `/plugin` and check that `azure-m365` is enabled, or restart Claude Code.
- **Any other client** (or Claude Code without the plugin): run the installer from the project directory, choosing the client:

  ```bash
  uvx --from git+https://github.com/JackInSightsV2/Azure-M365-MCP unified-microsoft-mcp install --client <claude-code|vscode|cursor|codex|claude-desktop>
  ```

  It needs [uv](https://docs.astral.sh/uv/). It merges an `azure-m365` entry into the client's config, keeps other servers, and is safe to re-run. Add `--scope user` for every project, or `--launch docker` to run the container instead. Then tell the user to restart the client and re-run this skill.

Nothing else needs installing: the server includes the Azure CLI (an `az` on the user's `PATH` is used first). The first start downloads it with the server (about 350 MB), so the tools can take a minute to appear.

## 2. Interactive sign-in

Call `microsoft365_read` with `command: "me"`.

- If it says browser sign-in is required, a browser window has opened: ask the user to complete sign-in there, wait for them to confirm, then retry the same call.
- If it returns a device code and sign-in address instead (hosts without a browser), show both to the user exactly as given, wait for them to confirm, then retry.
- Microsoft Graph and Azure sign in separately. Expect a second sign-in for Azure in step 3.
- A "Permissions requested" consent screen means a permission not yet granted in the Tenant was asked for. The user accepts only if allowed; otherwise they cancel and ask an admin.

**Tenant policy**: if a tool says sign-in was refused by Tenant policy, relay its message verbatim (it names the app and what an admin must approve) and stop. Do not suggest other apps, client IDs, tokens, or any other way around Tenant policy. The user's next step is to ask their tenant admin.

## 3. Verify

1. `microsoft365_read` with `command: "me"`: report `displayName` and `userPrincipalName`.
2. `azure_read` with `command: "az account show"`: report the subscription name, ID, and tenant ID. Complete the sign-in here too if one is requested, then retry.

If the user has no Azure subscription, the Azure check can fail while Microsoft 365 works. Say so and finish.

Tell the user setup is complete and which surfaces are connected. For writing correct calls, use the `microsoft-cloud` skill.

## Kubernetes / AKS (optional)

Offer this only if the user works with Azure Kubernetes Service (AKS). It needs the server running on their desktop (not Docker) and nothing installed: `kubectl` and `kubelogin` on the user's `PATH` are used, otherwise the first `kubernetes_connect` downloads them once with Microsoft's `az aks install-cli`.

1. Ask for the subscription, resource group, cluster name, and optionally a namespace (or find the cluster with `azure_find_resource` / `azure_read` `az aks list -o table`).
2. Call `kubernetes_connect` with them. The first call may take a minute while it downloads `kubectl` and `kubelogin`. If it asks for Azure sign-in, a browser window has opened: wait for the user to finish, then retry. If the download fails, relay the manual install commands it gives, wait for the user, then retry.
3. Verify with `kubernetes_read` `command: "kubectl get nodes"` and report the context and namespace.

## Resource inventory (opt-in)

After a successful Azure check, offer the Resource inventory. It makes `azure_find_resource` work: one lookup that says which subscription and resource group a named Azure resource is in.

State the risk plainly before asking, covering all of this:

- It is a file on this machine listing the name, type, subscription, resource group, location, and ID of every Azure resource the user's account can see. No tags, no properties, nothing from Microsoft 365.
- It is a map of their whole Azure estate. Only their user account can read it, but anything running as them (malware, backups, other AI tools) could.
- It refreshes itself every 24 hours. They can withdraw at any time, which deletes it.

Then ask: "Do you want me to turn on the Resource inventory?" Turn it on only after an explicit yes. Anything else (no, unsure, no answer, a question) means leave it off and finish.

**Turn on** (explicit yes only), using the same launcher as the server:

- uvx (plugin, or the installer default): `uvx --from git+https://github.com/JackInSightsV2/Azure-M365-MCP unified-microsoft-mcp resource-inventory on`
- Docker: `docker run --rm -v unified-microsoft-mcp-identity:/home/app/.IdentityService ghcr.io/jackinsightsv2/azure-m365-mcp:latest unified-microsoft-mcp resource-inventory on`

If the server's config sets `TOKEN_CACHE_DIR`, run the command with the same value in its environment. No restart is needed. Confirm by calling `azure_find_resource` with the name of any Azure resource the user knows (resources only; resource groups and subscriptions are not in it).

**Withdraw**: run the same command with `off` instead of `on`. It removes consent and deletes the Resource inventory file. `status` shows whether it is on. If the client's MCP config sets `RESOURCE_INVENTORY=true`, remove that as well.
