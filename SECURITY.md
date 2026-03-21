# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in DeskFlow, please report it responsibly.

**Do not open a public issue.** Instead, email the maintainer directly or use [GitHub's private vulnerability reporting](https://github.com/BryanBaluyut/DeskFlow/security/advisories/new).

Please include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

You can expect an initial response within 48 hours.

## Supported Versions

| Version | Supported |
|---------|-----------|
| Latest  | Yes       |

## Security Best Practices for Deployment

- Always change `SECRET_KEY` from the default value
- Use HTTPS in production (set `APP_URL` accordingly)
- Keep Docker images updated
- Restrict network access to the application port
- Rotate Entra ID client secrets periodically
- Use strong IMAP/SMTP credentials
