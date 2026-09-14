# Security policy

## Supported versions

Workforce OS has no supported public release yet.

## Reporting a vulnerability

Do not disclose suspected vulnerabilities, leaked tokens or private Notion data in a public issue. GitHub private vulnerability reporting or a dedicated private security contact must be configured before v1.0.

Include the affected version/commit, reproduction steps, impact and sanitized evidence. Never include a real Notion token or any other credential.

## Security model

- Secrets stay outside the repository and Notion.
- Workers receive only explicitly granted domain context.
- External, destructive and irreversible actions require approval.
- Removing a worker must revoke its integrations without deleting user data.
