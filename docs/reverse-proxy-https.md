# HTTPS via a reverse proxy (Caddy / Traefik / nginx)

Applicant's baseline posture is **private LAN/VPN over plain HTTP** (see
[overview.md](overview.md) — single operator, not exposed to the public
internet). If you want TLS anyway — a house requirement, a shared network you
don't fully trust, or remote access without a VPN — put a reverse proxy in
front of the front-door port and terminate HTTPS there. Only the front door
(`applicant-ui`, `${APP_PORT}` → container 7000) is ever published; the engine
and the other stack services stay on the internal Compose network either way.

Two things happen automatically once the proxy forwards the right header:

- **Secure session cookies.** When the proxy sets `X-Forwarded-Proto: https`,
  the app marks its session cookie `Secure` on its own — no configuration
  needed. To force the flag explicitly either way, set the `SECURE_COOKIES`
  env var (`true`/`false`); the explicit setting always wins.
- **Scheme-aware URLs.** Anything the app derives from the request scheme
  follows the forwarded value.

All three proxies below do that header forwarding by default (Caddy, Traefik)
or with one line (nginx).

## Caddy (recommended: two lines, automatic certificates)

With a public DNS name pointing at the box, Caddy obtains and renews
Let's Encrypt certificates automatically:

```caddyfile
applicant.example.com {
    reverse_proxy 127.0.0.1:7000
}
```

For a LAN-only name (no public DNS), use Caddy's internal CA instead —
browsers on your devices then need the Caddy root certificate installed once:

```caddyfile
applicant.lan {
    tls internal
    reverse_proxy 127.0.0.1:7000
}
```

## Traefik (Compose labels)

If you already run Traefik as your edge, attach the front door with labels —
add these to the `applicant-ui` service (adjust the certresolver name to
yours) and put both services on a shared external network:

```yaml
services:
  applicant-ui:
    # ... existing service definition ...
    labels:
      - traefik.enable=true
      - traefik.http.routers.applicant.rule=Host(`applicant.example.com`)
      - traefik.http.routers.applicant.entrypoints=websecure
      - traefik.http.routers.applicant.tls.certresolver=letsencrypt
      - traefik.http.services.applicant.loadbalancer.server.port=7000
```

Traefik sends `X-Forwarded-Proto` on its own; no extra middleware needed.

## nginx

```nginx
server {
    listen 443 ssl;
    server_name applicant.example.com;

    ssl_certificate     /etc/ssl/applicant/fullchain.pem;
    ssl_certificate_key /etc/ssl/applicant/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:7000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        # Live sessions / streaming surfaces use long-lived connections:
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
    }
}
```

## Checklist after enabling TLS

1. Log in over `https://…` and confirm the session survives a reload (if it
   does not, the proxy is not forwarding `X-Forwarded-Proto` — fix that or
   set `SECURE_COOKIES=true`).
2. Keep the app's own port (`${APP_PORT}`) firewalled from anything that
   isn't the proxy — TLS at the edge does nothing if the plain-HTTP port
   stays reachable.
3. The rest of the app door is already hardened independent of TLS: strong
   passwords are enforced server-side wherever one is set, login attempts
   are rate-limited per client, and TOTP two-factor auth is available in
   **Settings → Security** (QR enrollment + backup codes).
