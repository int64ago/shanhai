# Security Policy

## Reporting a Vulnerability

If you discover a security issue in **Shanhai World (https://shanhaiworld.org/)**, please report it privately via [GitHub Security Advisories](https://github.com/int64ago/shanhai/security/advisories/new) rather than opening a public issue.

## API Keys & Secrets

- **Never commit `.env` or `.env.local`**.
- `HYPER3D_API_KEY` is used only by local/CI offline asset generation scripts (`pipeline/rodin/generate.ts`) and is stripped from browser bundles via Vite's `envPrefix: 'VITE_'`.
- Cloudflare deployment credentials (`CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`) must be stored exclusively in GitHub Actions Repository Secrets.
