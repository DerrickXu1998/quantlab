# Security posture

What this application defends against, how, and — at length — what it does not.

The authentication design described here is specified by
[`docs/CONTRACT_V2.md`](CONTRACT_V2.md) §1. **The backend half is not
implemented.** There are no `users` or `sessions` tables in
`backend/src/quantlab/storage/db.py`, no `owner_id` column on
`experiment_runs`, and no `/api/v1/auth/*` routes in
`backend/src/quantlab/api/routes.py`. The frontend half exists —
`frontend/src/auth/` has the login screen, the provider, the route gate and the
token store — so the UI is ready for an API that does not yet answer.

Until the backend lands, the API is exactly what §1 of the contract calls "the
security hole this section closes": one global table, every caller able to list,
rename and delete every other caller's work.

Deploy accordingly. §6 is the checklist.

---

## 1. The threat model

**What this is.** A research tool. It holds market data derived from free public
sources, strategy definitions, and backtest results. A small number of known
users, each of whom cares that their work is theirs.

**What is actually worth protecting, in order:**

1. **A user's strategies.** The only genuinely sensitive content here. A working
   rule set is the output of someone's research time, and it is directly
   valuable to anyone who reads it.
2. **Account credentials.** Not because a QuantLab account is worth much, but
   because people reuse passwords. A password database leak from a research tool
   is a credential-stuffing attack on the user's bank, and that is the real
   consequence.
3. **Availability and cost.** The backtester is CPU-bound and takes an arbitrary
   symbol list and date range from the request body. An unauthenticated caller
   with a loop is a bill.
4. **Integrity of results.** Someone quietly altering another user's stored run
   is worse than deleting it, because the deletion is noticed.

**What this is not.** It is not a broker, a custodian, an execution venue or a
payment system. There is no order routing, no money movement, no account
linkage, no PII beyond an email address, and no regulated data. Nothing here is
a path to a trade — see [EXECUTION_MODEL.md](EXECUTION_MODEL.md) §9. That bounds
the blast radius considerably and it is worth saying so rather than implying a
seriousness the system does not have.

**Explicitly out of scope:**

- A malicious or compromised operator. Anyone with database or VM access reads
  everything. There is no envelope encryption, no per-user key, no attempt at
  it.
- A hostile insider with deploy rights. CI pushes images and restarts Compose;
  someone who can merge to `main` can run code on the VM.
- Nation-state or targeted attack. Not defended against, not pretended to be.
- Denial of service beyond what a reverse proxy absorbs.
- The data's *licensing* exposure, which is legal rather than technical and is
  in §5.

---

## 2. The authentication design, and why each choice

### Opaque bearer tokens, not JWTs

A session is a row in the database. `POST /auth/logout` deletes it and the token
is dead on the next request.

A signed stateless token cannot be withdrawn before it expires. Every JWT
deployment eventually grows a revocation list, at which point it is doing a
database lookup per request and has the operational cost of a session table
without the simplicity. The usual justification for JWTs — horizontal scale
without shared state — does not apply: this is one VM with one database, and
that database is already on the path of every request that does anything useful.

The contract picks the thing that can be revoked. Logout that does not log you
out is the kind of feature that looks fine until an incident.

Tokens are 32 bytes from `secrets.token_urlsafe` — a CSPRNG, not `random`.

### SHA-256 of the token at rest

The `sessions` table stores `sha256(token)`, never the token.

The property this buys: **a database read does not yield a usable credential.**
Backup on a laptop, log line that captured a row, SQL injection that reads a
table, support engineer running `SELECT *` — none of them gets a token that can
be presented to the API. Lookup still works, because the server hashes the
presented token and compares.

A fast hash is the right choice here and a slow one would be wrong. The input is
256 bits of CSPRNG output; there is no dictionary to run against it and no
plausible brute force. PBKDF2 over a token would cost real latency on every
authenticated request to defend against an attack that cannot happen. The
threat models for "a secret a human chose" and "a secret a CSPRNG chose" are not
the same, and using the same tool for both is cargo cult.

Use a constant-time comparison on the digest.

### PBKDF2-HMAC-SHA256 for passwords

Passwords are the opposite case: low entropy, human-chosen, reused elsewhere.
They need a deliberately slow, salted KDF so that a stolen table is expensive to
crack rather than free.

**Why PBKDF2 rather than argon2 or bcrypt.** Argon2id is a better KDF. It is
memory-hard, which defeats GPU and ASIC parallelism in a way PBKDF2 does not.
If this were a consumer product holding a large password database, argon2id
would be the answer.

It is not, and the constitution requires justifying new dependencies:

> Dependencies: new third-party libraries must be justified against the plugin
> and adapter contracts; heavy or license-restricted dependencies require
> explicit approval.

PBKDF2-HMAC-SHA256 is in `hashlib`. It ships with Python, it is FIPS-approved,
it has no native build step, no wheel to go missing on a platform, no C
extension to CVE, and no supply-chain surface at all. `argon2-cffi` means a new
runtime dependency with a compiled extension, in an image that currently has
none, on a project whose entire password corpus is a handful of researchers'
accounts.

The honest summary: **PBKDF2 at a high iteration count is adequate for this
threat model, and argon2id would be better.** If this ever holds more than a
few dozen accounts, or if registration is opened to the public, revisit it — and
the migration path is the standard one (rehash on next successful login, keep
the algorithm identifier in the stored hash so both can coexist).

**The contract does not specify the iteration count, the salt length, or the
hash encoding.** That is a gap someone has to close before implementation, not
a detail to leave to whoever writes the function. Pin it explicitly, store the
algorithm and parameters alongside the hash so they can be raised later without
invalidating existing accounts, and choose a count calibrated on the deployment
hardware rather than copied from a blog post.

### Uniform 401s on login

> `login` answers `401` with the same message and the same timing whether the
> email is unknown or the password is wrong, so the endpoint is not an account
> enumeration oracle.

An endpoint that distinguishes "no such user" from "wrong password" is a
membership oracle: feed it a breach list and learn who has an account here.
Same status, same body, same timing.

"Same timing" is the part that gets lost in implementation. The naive code
returns early when the email is not found — skipping the KDF — and that missing
20-100ms is measurable over enough samples. **The unknown-email path must still
perform a KDF call**, against a fixed dummy hash, before returning the identical
401.

Note that `register` remains an enumeration oracle by design: it must answer
`409` when an email is already registered. That is unavoidable if users are to
be told why registration failed, and it is the standard trade. If enumeration
resistance matters more than that message, registration has to move to an
email-confirmation flow where the response is identical either way — which is
the same work item as §5's email verification.

### Per-user row scoping, and 404 rather than 403

> Reading another user's run is `404`, never `403`: a `403` confirms the row
> exists.

`403 Forbidden` on someone else's run leaks the run's existence. Iterate
identifiers and you learn how many runs exist and when they were created; with
sequential or guessable identifiers you learn considerably more. `404` makes
"not yours" and "not there" indistinguishable.

The rule this implies for implementation: **scope in the query, not after it.**
`WHERE id = ? AND owner_id = ?` returning zero rows, which then 404s, cannot
leak. Fetch-then-check can, because the fetched row is in memory and one
careless log line or error message puts it in front of the wrong user. It also
fails open when someone adds a new endpoint and forgets the check; the scoped
query fails closed.

### Single-user mode

`QUANTLAB_AUTH_REQUIRED=false` binds every request to a built-in `local` user.
Ownership columns are still populated, so the two modes do not diverge in shape
and the auth-off path is not a separate, untested code path.

**This is a local demo setting.** It is not a deployment mode. See §6.

The default matters: auth is enforced when the variable is *unset* or true. A
deployment that forgets to configure it gets the safe behaviour. This mirrors
the existing stance on `QUANTLAB_CORS_ORIGINS`, which deliberately has no
wildcard fallback because, in `app.py`'s words, defaulting to `"*"` would mean a
deployment that forgot to configure it "is open to every origin, and would look
identical to one that was configured".

### Rate limiting on login

`429` after too many failed attempts for one email, per the contract's status
code table. That is credential-stuffing defence for a single account.
Registration is throttled separately, per client IP — see §3.

Per-user quotas beyond that (runs, requests) remain open. See §5.

---

## 3. What the transport and deployment already do

`[live]` — this part exists.

- **TLS terminated at Caddy** (`deploy/Caddyfile`). Given a hostname in
  `QUANTLAB_SITE_ADDRESS`, Caddy obtains and renews a Let's Encrypt certificate
  automatically and redirects HTTP to HTTPS. Given the `:80` default it serves
  plain HTTP, which the file itself calls out as "NOT a usable production
  state".
- **Caddy is the only public port.** Postgres and ClickHouse bind to
  `127.0.0.1` and are not reachable from the internet
  ([DEPLOY.md](DEPLOY.md)).
- **CORS is an explicit allow-list with no wildcard fallback**
  (`api/app.py: resolve_cors_origins`), and only `content-type` is in
  `allow_headers`. **That list will need `authorization` added** when bearer
  tokens land, or every authenticated cross-origin call from the SPA fails
  preflight.
- **No key material in CI.** GitHub Actions authenticates to GCP by OIDC through
  Workload Identity Federation, and reaches the VM over an IAP SSH tunnel. There
  is no long-lived service-account key to leak.
- **The serving image is runtime-only and unprivileged.** The backend
  Dockerfile's default stage installs no dev dependencies and runs as a
  non-root user; the test-capable `dev` stage is built only by the local
  compose file. The dev compose also binds ClickHouse, Postgres and Redpanda
  to `127.0.0.1`, matching the prod posture.
- **Interactive API docs are off in production posture.** `/docs`, `/redoc`
  and `/openapi.json` are served only when auth is disabled (the local demo)
  or `QUANTLAB_API_DOCS=on` is set explicitly, so a deployed API does not
  publish its full surface to unauthenticated callers.
- **Replay streams are bounded.** Both SSE endpoints require auth, cap pacing
  and event counts, end after 15 minutes, and each user may hold at most
  three concurrent streams (`429` with `Retry-After` past that) — one account
  cannot pin every threadpool worker.
- **Registration is rate-limited** to 10 per hour per client IP, alongside
  the per-email login limiter. Deployments behind a proxy need trusted-proxy
  config for client IPs to be meaningful.
- **Structured logging** across ingestion and computation (Constitution VI).
  This is observability, not audit — see §5.

---

## 4. What is not a vulnerability here, and why

Worth stating so nobody spends a week on the wrong thing.

- **No CSRF exposure today.** Credentials travel in an `Authorization` header,
  which a browser does not attach automatically to a cross-site request. There
  is nothing for a forged request to ride on. This holds *only* while no cookie
  is involved — see §5.
- **No SQL injection surface in the query layer**, which is parameterised
  throughout. The SQL that is string-built is DDL in `db.py` with no
  user-controlled input.
- **No template injection**: the API returns JSON, and the SPA renders through
  React rather than string-assembled HTML.
- **The synthetic demo dataset is not sensitive.** Every symbol is prefixed `ZZ`
  and checked against a real-ticker denylist (`config.py`). Leaking it costs
  nothing.

---

## 5. Known gaps

Everything a real production deployment still needs and does not have. This list
is the point of the document.

### Account lifecycle

- **No email verification.** Registration accepts any string that parses as an
  email. Nobody has proven they control it, which means the address is unusable
  for recovery or for notifications, and someone can register under an address
  belonging to another person.
- **No password reset.** Forget your password and the account is gone. There is
  no recovery flow, and adding one is not trivial — a reset flow is a second
  authentication path and is historically where account-takeover bugs live
  (tokens that do not expire, tokens that leak in a `Referer`, reset links that
  do not invalidate existing sessions).
- **No MFA.** Password alone. TOTP is the proportionate answer for a tool like
  this; WebAuthn is better and is more work.
- **No session management surface.** A user cannot list their active sessions or
  revoke one from another device. `logout` revokes only the calling session, so
  a stolen token stays valid until it expires.
- **Session lifetime is unspecified.** The contract's example shows
  `expires_at` thirty days after issue, which implies a 30-day TTL but does not
  state one. Nor is there an idle timeout, a refresh mechanism, or rotation on
  privilege change. Pin the TTL explicitly.
- **Password policy is unspecified.** `422` is reserved for "password fails
  policy" and the policy itself is not written down anywhere. Write it down —
  and prefer a length floor plus a breached-password check over composition
  rules, which mostly produce `Password1!`.

### Session handling in the browser

- **The token is in `localStorage`.** `frontend/src/auth/session.ts` holds it
  under `quantlab.auth.token`, with every access wrapped in try/catch because a
  private window throws rather than returning null. The trade-off is the
  standard one and it was made in favour of usability: `localStorage` is
  readable by any script on the origin, so **an XSS on the SPA origin is a
  permanent credential theft**, whereas an in-memory token dies on every page
  refresh. Given that, a CSP on the SPA origin is the control that actually
  matters here, and there is not one — see below. Session expiry is the only
  thing currently bounding a stolen token's usefulness.
- **CSRF, if cookies are ever introduced.** The moment a token moves into a
  cookie, §4's exemption is void and the following become mandatory:
  `SameSite=Lax` at minimum (`Strict` if the flows allow), `HttpOnly`,
  `Secure`, plus a synchroniser token or double-submit on every state-changing
  request, plus an `Origin` header check. Cookies also reintroduce the
  cross-origin split-deployment problem that the bearer header sidesteps
  entirely. The current design is CSRF-free by construction; keep it that way
  unless there is a strong reason not to.

### Operations

- **No secrets management.** Database URLs and credentials arrive as environment
  variables from a `.env` file on the VM (`.env.example`). They are on disk in
  plaintext, visible in `docker inspect` and in the process environment, and
  there is no rotation story. Secret Manager with a startup fetch is the
  proportionate fix on GCP.
- **HSTS is not set.** Caddy obtains a certificate and redirects HTTP to HTTPS,
  but it does not emit `Strict-Transport-Security` on its own and the Caddyfile
  does not add one. Without it the first request of a session is downgradeable.
  Add a `header` directive once the hostname is stable and you are confident you
  will not need plain HTTP — HSTS is difficult to walk back.
- **No other security headers.** No CSP, no `X-Content-Type-Options`, no
  `Referrer-Policy`, no `X-Frame-Options`. For a JSON API the practical impact
  is small; for the SPA origin on Vercel a CSP is worth having, and it is the
  one control that meaningfully limits an XSS.
- **No audit log.** Structured application logging exists; an audit trail does
  not. There is no tamper-evident record of who logged in, from where, what they
  read, what they deleted. After an incident you would be reconstructing events
  from application logs that were designed for debugging and are not retained
  with that in mind.
- **No per-user rate limits or quotas.** The contract rate-limits failed logins
  for one email and nothing else. `POST /runs` accepts an arbitrary symbol list
  and date range, bounded only by `MAX_SELECTION_INSTRUMENT_DAYS = 2_000_000`
  in `runner.py` — a *per-request* cap, so N requests cost N times that. Runs
  execute synchronously in the request. One authenticated user with a loop
  saturates the VM. Needed: a per-user concurrent-run limit, a request rate
  limit, and a total instrument-days budget over a rolling window.
- **No account lockout.** Login is rate-limited per email and registration is
  throttled to 10/hour per client IP, but there is no account-level lockout
  after sustained failures, and the per-IP registration limit is only as good
  as the attacker's address pool.
- **No backup encryption or tested restore.** Not addressed anywhere.
- **Dependency scanning is not wired into CI.** No `pip-audit`, no Dependabot
  configuration in the repository.

### Legal, not technical

**Market data licensing is the largest unmitigated exposure, and no code change
fixes it.** Constitution III:

> Stooq and Yahoo are unofficial sources with no redistribution rights. Their
> use is permitted for development and internal research only; before any
> redistribution, publication, or production deployment serving third parties,
> the UK side MUST move to a properly licensed feed.

Read that against what a deployment actually is. Putting this behind a public
hostname and giving accounts to people outside your organisation is *serving
third parties*. The technical controls in this document are then working
correctly while the deployment is non-compliant, and no security review catches
it because it is not a security problem.

The README puts the cost at roughly $30–80/month for the UK half. That is the
price of the exposure, and it is cheap relative to the alternative.

Two related items: there is no terms-of-service or privacy notice, and storing
an email address engages GDPR (lawful basis, subject access, erasure) with no
mechanism for any of it.

---

## 6. Deployment checklist

Before this is reachable from the internet. Not aspirational — every item is a
genuine "do not skip".

**Must be set:**

- [ ] `QUANTLAB_AUTH_REQUIRED` unset or `true`. **Never `false` on a public
      host.** `false` binds every request to the built-in `local` user, which
      means every visitor shares one account and can delete each other's work.
- [ ] `QUANTLAB_SITE_ADDRESS` set to a real hostname, not `:80` and not the
      VM's IP. No CA issues for a bare address, and Caddy cannot get a
      certificate without a name.
- [ ] `QUANTLAB_CORS_ORIGINS` set to the exact SPA origin. No wildcard. Include
      `authorization` in `allow_headers` once auth ships, or every
      authenticated cross-origin call fails preflight.
- [ ] Database credentials changed from the `quantlab:quantlab` defaults in
      `.env.example`, and the `.env` file `chmod 600` and owned by the deploy
      user.
- [ ] Postgres and ClickHouse confirmed bound to `127.0.0.1`. Verify from
      outside; do not assume.
- [ ] Firewall: 80 and 443 only. SSH via IAP, not a public port 22.
- [ ] PBKDF2 iteration count pinned explicitly, calibrated on the deployment
      hardware, with the algorithm and parameters stored alongside each hash.
- [ ] Session TTL pinned explicitly rather than left implicit.
- [ ] Password policy written down and enforced, returning `422`.

**Should be set before anyone else uses it:**

- [ ] HSTS header on the Caddy site block, once the hostname is settled.
- [ ] Per-user rate limits and a run quota. Without these one account can
      consume the whole VM.
- [ ] Registration throttled, or closed entirely and accounts provisioned by
      hand. For a small research group, closed registration removes several
      gaps in §5 at once and costs almost nothing.
- [ ] Log retention configured, with a documented retention period.
- [ ] Backups running, and a restore actually tested.
- [ ] Verify the login timing is uniform for known and unknown emails. Measure
      it; the early return is easy to reintroduce and invisible in review.

**Before serving anyone outside your own organisation:**

- [ ] A licensed UK market-data feed. See §5. This one is not optional and not
      technical.
- [ ] Terms of service and a privacy notice.
- [ ] Email verification and a password reset flow, because support requests
      for locked-out accounts start on day one.

---

## 7. Reporting

There is no security contact configured for this repository and no disclosure
policy. If this is deployed for anyone other than its authors, add both — a
`SECURITY.md` at the repository root with an address, and a stated response
time. The absence of a reporting path is itself a gap; someone who finds a
problem and cannot tell you will tell someone else.
