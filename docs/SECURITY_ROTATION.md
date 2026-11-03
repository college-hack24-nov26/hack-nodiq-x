# Credential Rotation — Production Checklist

**Status: MANUAL PROVIDER ROTATION REQUIRED** (Groq §A + Gmail §B —
dashboard-only actions; no provider CLI is configured here)

**JWT signing secret §C: RESOLVED 2026-09-20** (rotated + verified in the
live deployment; see §C).

No credentials were auto-revoked: no provider API/CLI is configured in this
repo, and inventing or auto-deleting production credentials is out of scope.

Real credentials live **only** in the gitignored `.env`. They are not in the
working tree source, tests, build output, Docker context, or git history
(verified by full pickaxe scans). Rotation is still required because the
`.env` has existed outside git control on a workstation.

---

## A. GROQ API keys (Copilot provider)

| | |
|---|---|
| Where they live | `.env` → `GROQ_API_KEY`, `GROQ_API_KEY_2..6` (rotation spares) |
| Where to rotate | https://console.groq.com → API Keys |

Checklist:

1. Log in to the Groq console and **revoke every key on the list** (primary +
   all spares — they are all potentially exposed together).
2. Create the replacements (same count as before) and paste the new values
   directly into `.env` on the **hosting provider's environment variables**
   (or the `.env` the deployment actually loads). Never in chat, tickets,
   screenshots, or source code.
3. Restart / redeploy the application.
   - `ai/config.py` hot-reloads `.env` within ~5 s, but a restart also
     re-reads everything cleanly.
4. Verify Copilot still works: log in → New Analysis → pick a dataset
   micrograph → open Copilot → ask "Explain this analysis" → the status line
   must show `Online — groq` and the reply must reference the real analysis.
5. Verify the frontend never carries a Groq key: `npm run build`, then grep
   `apps/web/dist` for `gsk_` — there must be zero hits (keys are server-only).

## B. Gmail App Password (SMTP: feedback + alerts)

| | |
|---|---|
| Where it lives | `.env` → `SMTP_PASS` (with `SMTP_USER`) |
| Where to rotate | Google Account → Security → 2-Step Verification → App passwords |

Checklist:

1. Revoke the existing App Password (delete it in the App passwords list).
2. Create a new App Password for the mailer.
3. Update `SMTP_PASS` in the hosting provider's environment variables.
4. Restart the backend (`services/mailer.py` reads SMTP config at import).
5. Test the password-reset email: use "Forgot password" for a test account
   and confirm the reset link arrives.
6. Test the contact/feedback form delivery.

## C. JWT / session signing secret

| | |
|---|---|
| Where it lives | `server_data/secret.key` — auto-generated 64-hex-char file, chmod 600. (There is **no** `JWT_SECRET` env var in this codebase; the file is the single source of truth.) |
| Where to rotate | Locally: `python -c "import secrets; pathlib.Path('server_data/secret.key.new').write_bytes(secrets.token_hex(32).encode())"` |

Checklist — **do this only during an intentional deployment window**:

1. ⚠️ **Rotating the signing secret invalidates every existing session
   immediately** — all users are logged out and every outstanding reset link
   dies. This is by design (that is what makes rotation effective).
2. Generate the new secret to `server_data/secret.key.new` (never print it).
3. Deploy it into the running deployment's `server_data/` volume, swap it
   over `secret.key` (keep the old file as `secret.key.bak-<date>` for one
   rollback window, then delete), and restart Gunicorn (`docker compose
   restart`).
4. Verify: capture a pre-rotation session cookie → it must be rejected (401)
   after restart; a fresh login must succeed and return a new
   `nodiq_session` cookie; `GET /api/health` → 200.
5. Sync the local `server_data/secret.key` with the deployed one.

**Status: RESOLVED 2026-09-20** — rotated in the live Docker deployment
(pre-rotation cookie → 401 verified; fresh login + new cookie verified;
health green; old sessions and old reset links invalidated as designed;
`bak-20260920` retained for the rollback window).

When to rotate again: after any suspected server compromise, after a
developer with server access leaves the project, or on a scheduled
quarterly basis.

## D. Firebase

| | |
|---|---|
| Public Web configuration | `apps/web/src/firebase.js` + `VITE_FIREBASE_*` in `.env` — **public by design** (identifies the Firebase project to browsers; not a secret) |
| Server-side secret | Service-account key, if ever used for Admin SDK — must live in `.env`/hosting env only, never in the frontend |
| Where to configure | Firebase Console → Authentication → Settings → **Authorized domains** |

Checklist:

1. Add the production domain under **Authorized domains** (Google sign-in
   popups and phone auth are domain-restricted).
2. Keep `VITE_FIREBASE_*` values public-facing only; they identify the
   project and cannot by themselves authenticate anyone.
3. If a **service-account private key** was ever generated and shared, revoke
   it in Google Cloud IAM → Service Accounts → Keys and create a new one.
4. Verify Google sign-in and phone sign-in from the production domain.

---

## After rotation

- Verify the AI provider comes up and SMTP sends (steps in §A/§B).
- Update this file: change the status line to `RESOLVED <date>`.

## Verification scans (no history rewrite required)

Full pickaxe scans over all history found **no real credentials**:

```bash
git log --all -S"gsk_" --oneline        # empty
git log --all -S"AIzaSy" --oneline      # empty
git log --all -S"SMTP_PASS=" --oneline  # only .env.example placeholders
git log --all -- .env                   # .env was never committed
```

Do **not** rewrite history or force-push; there is nothing to purge.

## Post-rotation hardening follow-ups (not secrets)

- **CSP enforcement**: RESOLVED 2026-09-20 — the app ships an enforcing
  `Content-Security-Policy` (verified by a violation-free browser
  walk-through of every page: landing, login, signup, dashboard, analysis,
  copilot, reports, settings, 404, logout).
- **TRUST_PROXY**: if you deploy behind a reverse proxy that *overwrites*
  `X-Forwarded-For`, set `TRUST_PROXY=true` in `.env` so rate limiting keys
  on real client IPs instead of the proxy's IP.
- **CORS_ORIGINS**: production frontend on a different host? Set
  `CORS_ORIGINS=https://your-frontend-host` in `.env`.
