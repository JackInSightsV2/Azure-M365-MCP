---
name: microsoft-cloud
description: Reference for calling the microsoft365_read, microsoft365_write, azure_read, and azure_write tools correctly first time. Common Microsoft Graph v1.0 paths (users, groups, licences, mail, calendar, Teams, OneDrive/SharePoint files, Intune devices, sign-in and audit logs) and Azure CLI / ARM REST paths with api-versions (subscriptions, resource groups, resources, VMs, storage, role assignments, cost). Use whenever the user asks about their Microsoft 365, Entra ID (Azure AD), or Azure tenant.
---

# Microsoft cloud tools reference

Answer from the tools, not from memory. If a tool returns a device code, run the `setup` skill's sign-in step. If it reports a Tenant policy refusal, relay the message and stop.

## Which tool

| Need | Tool | Input |
| --- | --- | --- |
| Read Microsoft 365 / Entra ID | `microsoft365_read` | `command`: Graph v1.0 path (no `https://graph.microsoft.com/v1.0/` prefix). GET only |
| Change Microsoft 365 / Entra ID | `microsoft365_write` | `command`, `method` (POST/PUT/PATCH/DELETE), `data` (JSON body) |
| Read Azure | `azure_read` | `command`: `az ...` read action (`list`, `show`, `get`, `exists`, `check`, `find`) or ARM path with `api-version` (GET) |
| Change Azure | `azure_write` | `command`: any other `az ...`, or ARM path + `method` + `data` |

- Read tools reject writes and Write tools reject reads; the error names the right tool.
- The server picks Azure CLI or ARM REST; ARM paths have no `https://management.azure.com/` prefix. A CLI command with no REST equivalent can't fall back when the CLI is blocked; retry with an ARM path.
- Prefer Graph (`microsoft365_*`) over `az ad ...` for Entra ID objects.
- Write tools run after the client asks the user. Say what will change before calling one.

## Microsoft Graph v1.0 (`microsoft365_read` unless noted)

Query tips: always `$select` the fields you need; `$top` (max 999 for users/groups, lower elsewhere); follow `@odata.nextLink` for more pages; quote strings in `$filter` with single quotes. The server does not send `ConsistencyLevel: eventual`, so advanced queries (`$search`, `$count`, `endsWith`, `ne`, `not`, filtering on `assignedLicenses`) fail. Use `eq` / `startswith` filters, or fetch and filter client-side.

**Users**
- `me` · `users/{id-or-upn}` · `users?$select=displayName,userPrincipalName,jobTitle,accountEnabled&$top=100`
- `users?$filter=startswith(displayName,'Sam')` · `users?$filter=mail eq 'a@contoso.com'`
- `users/{id}/memberOf?$select=displayName` · `users/{id}/manager` · `users/{id}/directReports`
- Write: PATCH `users/{id}` · POST `users` (needs `accountEnabled`, `displayName`, `mailNickname`, `userPrincipalName`, `passwordProfile`)

**Groups**
- `groups?$select=id,displayName,groupTypes,mailEnabled,securityEnabled` · `groups/{id}/members?$select=displayName,userPrincipalName` · `groups/{id}/owners`
- Write: POST `groups/{id}/members/$ref` `{"@odata.id":"https://graph.microsoft.com/v1.0/directoryObjects/{userId}"}` · DELETE `groups/{id}/members/{userId}/$ref`

**Licences**
- Tenant SKUs and counts: `subscribedSkus?$select=skuPartNumber,skuId,prepaidUnits,consumedUnits`
- A user's licences: `users/{id}/licenseDetails`
- Write: POST `users/{id}/assignLicense` `{"addLicenses":[{"skuId":"..."}],"removeLicenses":[]}` (user needs `usageLocation` set first)

**Mail** (signed-in user; use `users/{id}/...` for others where permitted)
- `me/messages?$select=subject,from,receivedDateTime&$top=10&$orderby=receivedDateTime desc`
- `me/mailFolders/inbox/messages?$filter=isRead eq false` · `me/messages/{id}`
- Write: POST `me/sendMail` `{"message":{"subject":"...","body":{"contentType":"Text","content":"..."},"toRecipients":[{"emailAddress":{"address":"..."}}]}}`

**Calendar**
- `me/calendarView?startDateTime=2026-01-01T00:00:00Z&endDateTime=2026-01-08T00:00:00Z&$select=subject,start,end,organizer` (expands recurrences; `me/events` does not)
- Write: POST `me/events` · PATCH/DELETE `me/events/{id}`

**Teams**
- `me/joinedTeams` · `teams/{team-id}/channels` · `teams/{team-id}/members`
- `teams/{team-id}/channels/{channel-id}/messages` (needs extra consent; may be refused)
- Write: POST `teams/{team-id}/channels/{channel-id}/messages` `{"body":{"content":"..."}}`

**Files (OneDrive / SharePoint)**
- `me/drive/root/children` · `me/drive/root:/Folder/Sub:/children` · `me/drive/items/{item-id}`
- `me/drive/root/search(q='budget')` · `me/drive/recent`
- `sites?search=marketing` · `sites/{site-id}/drives` · `drives/{drive-id}/root/children`

**Intune devices**
- `deviceManagement/managedDevices?$select=deviceName,operatingSystem,complianceState,userPrincipalName,lastSyncDateTime`
- `deviceManagement/managedDevices?$filter=userPrincipalName eq 'a@contoso.com'`
- Entra ID devices: `devices?$select=displayName,operatingSystem,trustType`

**Sign-in and audit logs** (need an Entra ID P1/P2 licence and a reports role)
- `auditLogs/signIns?$filter=userPrincipalName eq 'a@contoso.com'&$top=20`
- `auditLogs/signIns?$filter=createdDateTime ge 2026-01-01T00:00:00Z&$top=50` (check `status.errorCode`; 0 is success)
- `auditLogs/directoryAudits?$filter=activityDateTime ge 2026-01-01T00:00:00Z&$top=50`

**Tenant**: `organization?$select=displayName,verifiedDomains` · `domains`

## Azure (`azure_read` unless noted)

`{sub}` is a subscription ID, `{rg}` a resource group name. Add `-o table` for short CLI output, `--query` to trim JSON.

| What | Azure CLI | ARM REST path |
| --- | --- | --- |
| Current account / tenant | `az account show` | — |
| Subscriptions | `az account list` | `subscriptions?api-version=2022-12-01` |
| Resource groups | `az group list --subscription {sub}` | `subscriptions/{sub}/resourcegroups?api-version=2021-04-01` |
| Resources in a group | `az resource list -g {rg}` | `subscriptions/{sub}/resourceGroups/{rg}/resources?api-version=2021-04-01` |
| All resources of a type | `az resource list --resource-type Microsoft.Web/sites` | `subscriptions/{sub}/resources?$filter=resourceType eq 'Microsoft.Web/sites'&api-version=2021-04-01` |
| VMs | `az vm list -g {rg} -d` (`-d` adds power state and IPs) | `subscriptions/{sub}/providers/Microsoft.Compute/virtualMachines?api-version=2024-07-01` |
| VM power state | `az vm show -g {rg} -n {vm} -d` | `.../virtualMachines/{vm}/instanceView?api-version=2024-07-01` |
| Storage accounts | `az storage account list -g {rg}` | `subscriptions/{sub}/providers/Microsoft.Storage/storageAccounts?api-version=2023-05-01` |
| Role assignments | `az role assignment list --assignee {upn-or-id} --all` | `subscriptions/{sub}/providers/Microsoft.Authorization/roleAssignments?$filter=principalId eq '{objectId}'&api-version=2022-04-01` |
| Role definitions | `az role definition list --name Reader` | `subscriptions/{sub}/providers/Microsoft.Authorization/roleDefinitions?api-version=2022-04-01` |
| Usage / cost lines | `az consumption usage list --start-date 2026-01-01 --end-date 2026-01-31` | `subscriptions/{sub}/providers/Microsoft.Consumption/usageDetails?api-version=2023-05-01` |
| Budgets | `az consumption budget list` | `subscriptions/{sub}/providers/Microsoft.Consumption/budgets?api-version=2023-05-01` |

**POST reads go through `azure_write`** (the Read tool is GET-only; the client will ask first; nothing changes):
- Cost totals: POST `subscriptions/{sub}/providers/Microsoft.CostManagement/query?api-version=2023-11-01` with `{"type":"ActualCost","timeframe":"MonthToDate","dataset":{"granularity":"None","aggregation":{"totalCost":{"name":"Cost","function":"Sum"}},"grouping":[{"type":"Dimension","name":"ResourceGroupName"}]}}`
- Find a resource by name across subscriptions: POST `providers/Microsoft.ResourceGraph/resources?api-version=2022-10-01` with `{"query":"Resources | where name =~ 'myvm' | project name, type, subscriptionId, resourceGroup, location, id"}`

**Common writes (`azure_write`)**
- `az group create -n {rg} -l uksouth` · PUT `subscriptions/{sub}/resourcegroups/{rg}?api-version=2021-04-01` `{"location":"uksouth"}`
- `az vm start|stop|deallocate|restart -g {rg} -n {vm}` · POST `.../virtualMachines/{vm}/deallocate?api-version=2024-07-01`
- `az role assignment create --assignee {upn} --role Reader --scope /subscriptions/{sub}/resourceGroups/{rg}`
- Deletes (`az group delete`, DELETE on a path) are irreversible: confirm the exact target with the user first.

## Verifier

> Placeholder: arrives in #27 (`tenant-verifier` agent for What-if before, and confirmation after, significant writes).
