# Security Policy

## Reporting Vulnerabilities

If you discover a security vulnerability, please report it responsibly:

1. **Preferred:** Use [GitHub Security Advisories](https://github.com/jennis0/scene-atlas/security/advisories/new) to report privately.
2. **Alternative:** Email the maintainer directly (see the repository's profile).

Please do **not** open a public issue for security vulnerabilities.

## Supported Versions

Only the latest release is supported with security updates.

## Security Model

Scene Atlas is designed for **trusted networks** — personal use or small groups behind a reverse proxy. It does not include built-in authentication. See [design/security.md](design/security.md) for the full security evaluation.

Key points:
- Rate limiting on expensive and destructive endpoints
- Security headers (X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy)
- Path traversal prevention via UUID-based staging
- CI security scanning (pip-audit, Bandit, npm audit)
- CORS configuration for multi-origin deployments

## Deployment Recommendations

- Always run behind a reverse proxy (nginx, Caddy) with HTTPS
- Configure `SCENE_ATLAS_CORS_ORIGINS` to match your actual frontend URL
- Do not expose the backend port (8000) directly to the internet
- Use firewall rules to restrict access to trusted IPs
