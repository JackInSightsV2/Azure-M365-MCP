---
name: microsoft-cloud
description: Reference for calling the microsoft365_read, microsoft365_write, azure_read, azure_write, and kubernetes_* tools correctly first time. Common Microsoft Graph v1.0 paths (users, groups, licences, mail, calendar, Teams, OneDrive/SharePoint files, Intune devices, sign-in and audit logs) and Azure CLI / ARM REST paths with api-versions (subscriptions, resource groups, resources, VMs, storage, role assignments, cost), and kubectl for AKS / Kubernetes (pods, deployments, namespaces, logs). Use whenever the user asks about their Microsoft 365, Entra ID (Azure AD), Azure tenant, or Kubernetes clusters.
---

# Microsoft cloud tools reference

Answer from the tools, not from memory. If a tool asks for sign-in (browser window or device code), run the `setup` skill's sign-in step. If Graph returns 403, relay its suggestion about the missing permission. If it reports a Tenant policy refusal, relay the message and stop.

## Which tool

| Need | Tool | Input |
| --- | --- | --- |
| Read Microsoft 365 / Entra ID | `microsoft365_read` | `command`: Graph v1.0 path (no `https://graph.microsoft.com/v1.0/` prefix). GET only |
| Change Microsoft 365 / Entra ID | `microsoft365_write` | `command`, `method` (POST/PUT/PATCH/DELETE), `data` (JSON body) |
| Read Azure | `azure_read` | `command`: `az ...` read action (`list`, `show`, `get`, `exists`, `check`, `find`, `query`, `what-if`, and `list-*` / `show-*` / `get-*` variants such as `list-locations`; not `get-credentials`) or ARM path with `api-version` (GET, or POST to Resource Graph / Cost Management query / What-if) |
| Change Azure | `azure_write` | `command`: any other `az ...`, or ARM path + `method` + `data` |
| Which subscription / resource group an Azure resource is in | `azure_find_resource` | `name`: all or part of the resource name |
| Connect kubectl to an AKS cluster (once per cluster) | `kubernetes_connect` | `subscription`, `resource_group`, `cluster`, optional `namespace` |
| Read Kubernetes | `kubernetes_read` | `command`: `kubectl get/describe/logs/top/events/...`; optional `context`, `namespace` |
| Change Kubernetes | `kubernetes_write` | `command`: any other `kubectl ...`; optional `context`, `namespace` |

- Read tools reject writes and Write tools reject reads; the error names the right tool.
- The server picks Azure CLI or ARM REST; ARM paths have no `https://management.azure.com/` prefix. A CLI command with no REST equivalent can't fall back when the CLI is blocked; retry with an ARM path.
- Prefer Graph (`microsoft365_*`) over `az ad ...` for Entra ID objects.
- Write tools run after the client asks the user. Say what will change before calling one.
- Given an Azure resource name but not its subscription or resource group, try `azure_find_resource` before searching subscriptions. If it says the Resource inventory is off, use the Resource Graph query below instead; mention the `setup` skill's Resource inventory step only if the user wants faster lookups.

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

**Query POSTs go through `azure_read`** (Resource Graph, Cost Management query, and deployment What-if only read, so the Read tool accepts them):
- Cost totals: POST `subscriptions/{sub}/providers/Microsoft.CostManagement/query?api-version=2023-11-01` with `{"type":"ActualCost","timeframe":"MonthToDate","dataset":{"granularity":"None","aggregation":{"totalCost":{"name":"Cost","function":"Sum"}},"grouping":[{"type":"Dimension","name":"ResourceGroupName"}]}}`
- Find a resource by name across subscriptions (when `azure_find_resource` is off): POST `providers/Microsoft.ResourceGraph/resources?api-version=2022-10-01` with `{"query":"Resources | where name =~ 'myvm' | project name, type, subscriptionId, resourceGroup, location, id"}`

**Common writes (`azure_write`)**
- `az group create -n {rg} -l uksouth` · PUT `subscriptions/{sub}/resourcegroups/{rg}?api-version=2021-04-01` `{"location":"uksouth"}`
- `az vm start|stop|deallocate|restart -g {rg} -n {vm}` · POST `.../virtualMachines/{vm}/deallocate?api-version=2024-07-01`
- `az role assignment create --assignee {upn} --role Reader --scope /subscriptions/{sub}/resourceGroups/{rg}`
- Deletes (`az group delete`, DELETE on a path) are irreversible: confirm the exact target with the user first.

## Kubernetes / AKS

Connect once with `kubernetes_connect` (it runs `az account set`, `az aks get-credentials --overwrite-existing`, `kubelogin convert-kubeconfig -l azurecli`, and sets the namespace). It reports the current context and namespace; the connection lasts in the user's kubeconfig, so don't reconnect before every command. The first call downloads `kubectl` and `kubelogin` when the user has none (via `az aks install-cli`); if that download fails, relay the manual install commands it gives. If it asks for Azure sign-in, wait for the user, then retry. Don't know the resource group? `azure_read` `az aks list -o table`.

Then pass a `command` beginning with `kubectl`. `context` and `namespace` are added as `--context` / `--namespace`; prefer them over editing the kubeconfig.

- **Read (`kubernetes_read`)**: `get`, `describe`, `logs`, `top`, `explain`, `events`, `diff`, `api-resources`, `api-versions`, `version`, `cluster-info`, `auth can-i`, `auth whoami`, `config view` / `get-contexts` / `current-context`.
  - `kubectl get pods -A -o wide` · `kubectl get pods --field-selector=status.phase!=Running -A`
  - `kubectl get deploy,svc,ingress` · `kubectl get nodes -o wide` · `kubectl get ns`
  - `kubectl describe pod {pod}` (events explain CrashLoopBackOff / Pending) · `kubectl events --types=Warning`
  - `kubectl logs {pod} --tail=200` · `kubectl logs deploy/{name} -c {container} --since=1h` · `kubectl logs {pod} --previous`
  - `kubectl top pods` · `kubectl top nodes` · `kubectl auth can-i delete pods`
- **Write (`kubernetes_write`)**: everything else.
  - `kubectl apply -f {file-or-url}` · `kubectl delete pod {pod}` · `kubectl rollout restart deploy/{name}` · `kubectl rollout status deploy/{name} --timeout=120s`
  - `kubectl scale deploy/{name} --replicas=3` · `kubectl set image deploy/{name} {container}={image}`
  - `kubectl exec {pod} -- {command}` (non-interactive) · `kubectl cordon {node}` · `kubectl config use-context {context}`
- Not supported: `-it` / `--stdin` / `--tty`, `edit`, `attach`, `port-forward`, `proxy`, `--watch`, `logs -f`, `-f -` (stdin), `config view --raw`. Use `--tail` / `--since` for logs and `kubectl patch` / `set` instead of `edit`.
- Say what will change before a `kubernetes_write` call; `delete` and `drain` are hard to undo.

## Verifier

The `tenant-verifier` agent is the Verifier. It has Read tools only and never makes changes.

- **Before** any `azure_write` call, and any `microsoft365_write` call that changes users, groups, or licences (create, update, delete, membership, `assignLicense`), invoke `tenant-verifier` with the exact planned call: tool, command or path, method, and body. It runs a What-if and returns target, current state, predicted change, risks, and a GO / CHECK verdict. Show the user the result; on CHECK, resolve what it flags with the user before calling the Write tool.
- **After** that write, invoke `tenant-verifier` again with the same call to re-read the target and confirm each intended field landed. Report any mismatch to the user.
- **Skip** it for mail, calendar events, Teams messages, files, and similar low-risk writes.
- Invoke it whenever the user asks to check a planned or completed change.
- If the Verifier reports a Tenant policy refusal, relay it; don't look for a way around it.
