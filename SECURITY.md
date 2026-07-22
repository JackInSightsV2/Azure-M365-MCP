# Security policy

## Reporting a vulnerability

Please report vulnerabilities through GitHub's private security advisory feature rather than a
public issue. Include affected versions, reproduction steps, and the potential impact when
possible.

## Operational guidance

The stdio transport is the safest default for local use. Keep HTTP transports bound to loopback
when possible. Any remote deployment should use `MCP_API_KEY`, TLS, and network access controls;
the API key is not a replacement for either TLS or a firewall. Grant the Azure identity and
Microsoft Graph application only the permissions required for the intended tools.
