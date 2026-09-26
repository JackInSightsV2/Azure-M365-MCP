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

Azure CLI commands also need the [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli). Without it, `azure_read` / `azure_write` use Azure Resource Manager REST instead.

## 2. Interactive sign-in

Call `microsoft365_read` with `command: "me"`.

- If it returns a device code and sign-in address, show both to the user exactly as given, ask them to complete sign-in in the browser, wait for them to confirm, then retry the same call.
- Microsoft Graph and Azure sign in separately. Expect a second device code for Azure in step 3.

**Tenant policy**: if a tool says sign-in was refused by Tenant policy, relay its message verbatim (it names the app and what an admin must approve) and stop. Do not suggest other apps, client IDs, tokens, or any other way around Tenant policy. The user's next step is to ask their tenant admin.

## 3. Verify

1. `microsoft365_read` with `command: "me"`: report `displayName` and `userPrincipalName`.
2. `azure_read` with `command: "az account show"`: report the subscription name, ID, and tenant ID. Complete a device code sign-in here too if one is returned, then retry.

If the user has no Azure subscription, the Azure check can fail while Microsoft 365 works. Say so and finish.

Tell the user setup is complete and which surfaces are connected. For writing correct calls, use the `microsoft-cloud` skill.

## Resource inventory (opt-in)

> Placeholder: arrives in #26. Do not offer or create a Resource inventory yet.
