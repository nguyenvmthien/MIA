# Public Demo Deployment

This project can run locally as before, or be exposed through a domain for a short public demo.

## Local

Use the normal compose file:

```bash
docker compose up --build
```

Open:

- Web UI: `http://localhost:3001`
- API docs: `http://localhost:8000/docs`
- Grafana: `http://localhost:3000`
- pgAdmin: `http://localhost:5050`

## Public Demo With A Domain

Use the same compose command:

```bash
docker compose up --build
```

Set these values in `.env`:

```env
AUTH_URL=https://mia.minhthien.click
PUBLIC_URL=https://mia.minhthien.click
FRONTEND_URL=https://mia.minhthien.click
WEB_PORT=3001
AUTH_TRUST_HOST=true
```

Google OAuth redirect URI:

```text
https://mia.minhthien.click/api/auth/callback/google
```

For local testing, use:

```env
AUTH_URL=http://localhost:3001
PUBLIC_URL=http://localhost:3001
FRONTEND_URL=http://localhost:3001
WEB_PORT=3001
```

Google OAuth redirect URI:

```text
http://localhost:3001/api/auth/callback/google
```

## DNS / HTTPS

Recommended free setup:

1. Point `mia.minhthien.click` to the machine running Docker.
2. Use Cloudflare DNS and Cloudflare Tunnel for HTTPS.
3. Configure the tunnel target to `http://localhost:3001`.

If using router port forwarding instead, forward external port `80` to the host
port configured by `WEB_PORT`. HTTPS then requires a reverse proxy such as Caddy,
Traefik, or Nginx with certificates.
