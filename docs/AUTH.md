# Authentication

QuantLab is a single-node research tool. Auth exists so that several people can share one
deployment without reading or overwriting each other's experiment runs — not to defend against
a hostile network. The model below is sized to that scope.

## The model

- **Accounts.** `users(id, username, password_hash, created_at, is_admin)` in the same store
  as experiment runs: the Postgres catalog on the warehouse (migration `006_auth.sql`), the
  SQLite demo file otherwise. Usernames are case-insensitive (`COLLATE NOCASE` on SQLite, a
  `lower(username)` unique index on Postgres). Passwords are PBKDF2-SHA256, 600,000
  iterations, per-user salt, compared with `hmac.compare_digest` — stdlib only, so the
  backend image gains no dependencies.
- **Sessions.** `POST /auth/login` issues an opaque `secrets.token_urlsafe` token in a
  `quantlab_session` cookie (`HttpOnly; SameSite=Lax`; `Secure` only when
  `QUANTLAB_AUTH_COOKIE_SECURE` is set, since local dev is plain http). The store keeps only
  the token's SHA-256, so a leaked database does not hand out usable sessions. Expiry is
  14 days, rolling: every authenticated request renews the session.
- **Enforcement.** A `require_session` FastAPI dependency guards every `/api/v1` route
  except `GET /health`, `POST /auth/login`, and the bootstrap-gated `POST /auth/register`.
  No valid cookie → 401.
- **Run isolation.** `experiment_runs.user_id` records the owner; every ExperimentStore
  method scopes by the authenticated user, so another user's run id reads as 404. Runs
  recorded before accounts existed have `user_id NULL` and stay visible to everyone —
  reassigning them to whoever registered first would be a silent, wrong guess.
- **Rate limiting.** Failed logins are capped per client IP (5 per minute, in-memory). This
  blunts online password guessing; it is not distributed abuse infrastructure.

## Bootstrapping the first user

`POST /auth/register` is public only while zero users exist, and that first user becomes
`is_admin: true`. From then on, registration requires an admin session and creates non-admin
users. On a fresh deployment:

```bash
curl -c cookies.txt -X POST localhost:8000/api/v1/auth/register \
  -H 'content-type: application/json' \
  -d '{"username": "alice", "password": "pick-a-long-password"}'
```

There is no email reset — there is no mailer. An admin resets a forgotten password by
updating the row directly:

```bash
# warehouse
docker compose exec postgres psql -U quantlab -c \
  "UPDATE users SET password_hash = '<new pbkdf2 record>' WHERE username = 'alice'"
# demo
sqlite3 /data/quantlab.db \
  "UPDATE users SET password_hash = '<new pbkdf2 record>' WHERE username = 'alice'"
```

Generate the record with the same helper the API uses:

```bash
python -c "from quantlab.api.auth import hash_password; print(hash_password('new-password'))"
```

## Turning auth off

`QUANTLAB_AUTH=off` disables the feature entirely: `require_session` is a no-op, run
scoping disappears, and the four `/auth/*` routes answer 404. Behavior is byte-for-byte
what it was before auth existed, which is also how the pre-auth test suite runs (the
dedicated auth tests turn it back on per app via `create_app(..., auth_enabled=True)`).

## Threat scope

In scope: shared deployments where users should not see each other's runs; casual credential
guessing; database leaks (no plaintext passwords, no usable tokens). Out of scope: anything
requiring TLS termination, CSRF tokens beyond `SameSite=Lax`, refresh-token rotation, SSO,
or multi-node rate limiting. Terminate TLS in front (the production Caddyfile does) and set
`QUANTLAB_AUTH_COOKIE_SECURE=1`.
