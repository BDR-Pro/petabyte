# Canonical domain — kill the duplicate sites

**This is the highest-value fix on the site right now, and it is not a design change.**
Today a visitor can type `www.petabyte.market` or `space.petabyte.market` and land on an
older Petabyte with a different visual system and **broken login (502)**. That reads as a
dead or abandoned company. Nothing about typography matters next to this.

Canonical host: **`https://petabyte.market`** (apex, no `www`).

---

## 1. DNS (do this first)

At your DNS provider:

| Record | Name | Value |
|---|---|---|
| A | `@` | `<droplet IP>` |
| CNAME | `www` | `petabyte.market` |
| CNAME | `space` | `petabyte.market` |

Do **not** point `www`/`space` at the old boxes. If old droplets are still serving those
names, take them out of DNS *before* anything else — a 301 you control is fine, a stale
server you forgot about is not.

## 2. TLS certs for every name

```bash
sudo certbot --nginx -d petabyte.market -d www.petabyte.market -d space.petabyte.market
```

## 3. nginx — one canonical server, everything else 301s to it

`/etc/nginx/sites-available/petabyte`:

```nginx
# --- redirect every non-canonical name to the apex, preserving the path ---
server {
    listen 80;
    listen 443 ssl;
    server_name www.petabyte.market space.petabyte.market;

    ssl_certificate     /etc/letsencrypt/live/petabyte.market/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/petabyte.market/privkey.pem;

    # 301 = permanent. Browsers and Google will stop asking.
    return 301 https://petabyte.market$request_uri;
}

# --- plain http on the apex -> https ---
server {
    listen 80;
    server_name petabyte.market;
    return 301 https://petabyte.market$request_uri;
}

# --- the one real site ---
server {
    listen 443 ssl http2;
    server_name petabyte.market;

    ssl_certificate     /etc/letsencrypt/live/petabyte.market/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/petabyte.market/privkey.pem;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;

    client_max_body_size 25m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

## 4. Verify (all four must be 301 -> apex, then 200)

```bash
curl -sI https://www.petabyte.market            | head -1   # 301
curl -sI https://www.petabyte.market/login      | head -1   # 301 (path preserved)
curl -sI https://space.petabyte.market/anything | head -1   # 301
curl -sI https://petabyte.market                | head -1   # 200
curl -sI https://petabyte.market/login          | head -1   # 200, NOT 502
```

## 5. Decommission the old app

Once the redirects are green, **stop the old services** so nothing can serve the old site
again (a redirect in front of a live old app is one nginx mistake away from resurfacing):

```bash
# on whatever box served the old www/space site
sudo systemctl disable --now <old-service>
```

Keep a snapshot of the old box for a week, then delete it.

## 6. If Spaces comes back

Do not resurrect it on its own subdomain with its own look. It belongs inside the product
as **Deployments** (`petabyte.market/deployments`), sharing this navigation, this session,
and this design system — one company, one site.
