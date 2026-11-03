# NODIQ-X — Hosting Dashboard Configuration Required

Settings that must be configured **outside this repository**. Everything inside
the repo ships secure-by-default; the items below depend on the hosting
environment (provider unknown — provider-specific steps marked as such).

## 1. HTTPS / TLS termination

| | |
|---|---|
| SETTING | HTTPS enforcement + valid TLS certificate |
| WHERE | Reverse proxy / load balancer / platform dashboard (Cloudflare, Nginx, PaaS) |
| WHY | All auth traffic (passwords, tokens) must travel over TLS |
| VERIFY | `curl -I https://<host>/` → `200`; `http://` redirects to `https://` at the edge |

The app itself does **not** force a redirect (avoids loops behind proxies) and
does **not** trust `X-Forwarded-*` headers unless told to — see §2.

## 2. TRUST_PROXY

| | |
|---|---|
| SETTING | `TRUST_PROXY=true` — **only** if the proxy overwrites `X-Forwarded-For`/`X-Forwarded-Proto` (single trusted hop) |
| WHERE | Container environment (compose `environment:`, orchestrator env) |
| WHY | Enables correct client-IP logging/rate-limit keys and HSTS emission behind TLS termination |
| RISK | If set with a non-overwriting or spoofable chain, clients can forge IPs → per-IP rate limits bypassable. Leave `false` for direct exposure (current default) |
| VERIFY | Behind TLS: `curl -I https://<host>/` contains `Strict-Transport-Security` (only emitted when `TRUST_PROXY=true` **and** request is https) |

## 3. HSTS

| | |
|---|---|
| SETTING | `Strict-Transport-Security: max-age=31536000` |
| WHERE | App emits it automatically once §1+§2 are correct; alternatively set at the edge |
| WHY | Forces browsers to keep using HTTPS |
| ROLLBACK | HSTS is sticky in browsers for `max-age` — start with 1 year only after HTTPS is confirmed stable; do **not** enable `includeSubDomains` unless every subdomain is HTTPS; do **not** enable `preload` |
| VERIFY | Response header present on https responses, absent on plain http |

## 4. CORS origins (only if cross-origin access is ever needed)

| | |
|---|---|
| SETTING | `CORS_ORIGINS=https://app.example.com` (comma-separated) |
| WHERE | Container environment |
| WHY | Default is same-origin only (no CORS needed — Flask serves the SPA). Dev origins (`http://localhost:5173`, `http://127.0.0.1:5173`) are allowed only when `FLASK_DEBUG=1` |
| VERIFY | `curl -s -D- -o /dev/null -H "Origin: https://evil.example" https://<host>/api/health` → **no** `Access-Control-Allow-Origin` header |

## 5. Firebase authorized domains

| | |
|---|---|
| SETTING | Add the production domain under Firebase console → Authentication → Settings → Authorized domains |
| WHERE | Google Firebase console |
| WHY | Client-side Firebase authentication is domain-restricted |
| VERIFY | Sign-in works from the production domain |

## 6. Health check path

| | |
|---|---|
| SETTING | `GET /api/health` |
| WHERE | Orchestrator / load balancer health probe |
| WHY | Returns JSON with engine status; used as liveness/readiness signal |
| VERIFY | HTTP 200, `"status": "ok"` |

## 7. Credential rotation (one-time, manual)

See `docs/SECURITY_ROTATION.md` — Groq API keys and the Gmail app password
should be rotated at the provider dashboards since they may have appeared in
local plaintext config.

## 8. COOKIE_SECURE

| | |
|---|---|
| SETTING | `COOKIE_SECURE=true` (optional override) |
| WHERE | Container environment |
| WHY | Forces the `Secure` flag on the `nodiq_session` cookie regardless of request scheme. Default is `auto`: Secure is set automatically when the request arrives over https (with `TRUST_PROXY=true` behind a TLS proxy). Set it explicitly if the proxy terminates TLS but does not forward the proto header |
| VERIFY | `curl -s -D- -o /dev/null -X POST https://<host>/api/auth/login -H 'Content-Type: application/json' -d '{...}'` → `Set-Cookie` contains `Secure` |

## 9. Gunicorn workers & restart/redeploy

| | |
|---|---|
| SETTING | `gunicorn -w 1 --threads 4 -t 120 -b 0.0.0.0:8001 nodiq.api.server:app` (gthread worker, 120 s timeout) |
| WHERE | `deploy/Dockerfile` CMD (already configured) |
| WHY | 2-worker production topology; the shared-SQLite rate limiter is verified across both workers |
| REDEPLOY | `docker compose up -d --build` (rebuild + rolling restart); verify `GET /api/health` → 200 and 3 gunicorn processes (master + 2) via `/proc` |
| VERIFY | `GET /api/health` → 200 after each deploy; worker count via `docker exec nodiq-x sh -c 'for p in /proc/[0-9]*/cmdline; do grep -qa gunicorn $p && echo x; done | wc -l'` |

## 10. Production environment variables & secret storage

| | |
|---|---|
| SETTING | All secrets as provider environment variables (never baked into images): `JWT_SECRET`, `GROQ_API_KEY(+_2..6)`, `SMTP_*`, `FEEDBACK_TO_EMAIL` (required or feedback/reset/SPC emails are silently skipped), `AI_*`; plus `TRUST_PROXY`, `COOKIE_SECURE`, `CORS_ORIGINS` as applicable |
| WHERE | Hosting provider's secret manager / environment config — NOT committed, NOT in the image (`.dockerignore` excludes `.env`; compose bind-mounts it read-only only for the local single-host setup) |
| WHY | Secrets in image layers persist in registries and caches; env vars are rotatable without a rebuild |
| VERIFY | `docker export <container> | tar -t | grep -c '.env$'` → 0 (not in image filesystem) |

## 11. Restart / redeploy procedure

1. Merge/ship the release commit.
2. On the host: `git pull` (or your CI/CD checkout) → `docker compose up -d --build`.
3. Health gate: `GET /api/health` → 200 with engine `validated 1000/1000`.
4. Confirm `Strict-Transport-Security` appears (https + `TRUST_PROXY=true`).
5. Confirm the enforced CSP header is present on `GET /`.
6. Spot-check login → `/api/auth/me` → logout (cookie cleared) before opening traffic.

## 12. Render Blueprint deployment (current hosted setup)

| | |
|---|---|
| HOW | Render dashboard → **New +** → **Blueprint** → pick the GitHub repo; Render reads `render.yaml` and prompts once for the `sync: false` secrets (`GROQ_API_KEY`, six `VITE_FIREBASE_*` — copy values from the local `.env`) |
| WHAT | Single Docker web service, free plan: gunicorn serves `/api` **and** the built SPA same-origin; frontend is built inside the image (multi-stage Dockerfile), so no separate static host |
| BUILD DATA | The 1000-image sample dataset + `summary_1000_fixed.csv` are committed and baked into the image; Firebase config is injected at **build time** (changing a `VITE_FIREBASE_*` var triggers a rebuild) |
| RUNTIME | `TRUST_PROXY=true` (Render TLS proxy: Secure cookies + HSTS + real client IPs for rate limiting), `OFFLINE_MODE=false`, `GROQ_API_KEY` secret |
| HEALTH | `GET /api/health` → 200 `{status: ok, dataset_images: 1000}`; Render uses it as the deploy health gate |
| FREE-TIER | Ephemeral disk: accounts/analysis history reset on every restart/redeploy; spins down after ~15 min idle (cold start 30–60s); 512MB RAM (drop to 1 gunicorn worker if tight) |
| PERSISTENCE | To keep accounts/history across deploys later: add a Render Disk mounted at `/app/server_data` (paid plans) |
