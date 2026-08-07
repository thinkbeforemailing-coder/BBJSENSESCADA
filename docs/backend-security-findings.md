# BBJ Sense Backend — Security Findings

**Date:** 2026-08-06
**Scope:** Backend API at `http://34.131.199.29:8000` (FastAPI service backing the BBJ Sense gateway/SCADA platform)
**Found while:** Rotating the BBJ Windows Gateway's API key and auditing `bbj-sense-gateway` (the Windows gateway agent codebase)
**Reported by:** Gateway-side cleanup session, not a dedicated pentest — treat as a starting list, not exhaustive

---

## Summary

| # | Finding | Severity | Status |
|---|---------|----------|--------|
| 1 | `/gateway/config` and `/gateway/health` require no authentication | High | Fixed 2026-08-07 |
| 2 | No way to revoke/rotate an existing gateway credential | Medium | Fixed 2026-08-07 |
| 3 | Default `admin` / `admin123` credentials, role `super_admin` | Critical | Fixed 2026-08-07 |
| 4 | No password-change capability for existing users | High | Fixed 2026-08-07 |
| 5 | API served over plain HTTP, no TLS | Medium | Fixed 2026-08-07 |

**2026-08-07 update:** all 5 findings fixed. #1–#4 fixed directly on the backend (`/home/jsctennis80/bbj-sense/backend`, GCP VM `bbj-sense-app`): `PATCH /users/{id}/password` (closes #3/#4), `DELETE /gateway/auth/{gateway_id}` (closes #2, used to revoke the leaked `BBJ-GW-001` key), and `Depends(verify_gateway_access)` added to all `/gateway/config` and `/gateway/health` endpoints (closes #1). The #1 fix required updating this gateway repo first (commit `4d9f22d`, sends `X-Gateway-Key` on config/health calls) and deploying that ahead of the backend change, to avoid breaking live polling.

**#5 (TLS) closed same day:** `bbjsense.com` / `www.bbjsense.com` DNS pointed at the server, Caddy installed as a reverse proxy in front of uvicorn with automatic Let's Encrypt certs (`/etc/caddy/Caddyfile`, proxies to `localhost:8000`). Gateway repo updated (commit `7067341`) to use `https://www.bbjsense.com` as the default `BBJ_API_BASE_URL`. Direct plaintext access on port 8000 was then closed off entirely at the GCP firewall (three redundant `0.0.0.0/0 tcp:8000` rules — `allow-bbj-api`, `allow-bbj-fastapi`, `allow-fastapi-8000` — deleted), so the only way to reach the API now is through Caddy/TLS.

---

## 1. Unauthenticated config and health endpoints (High)

`GET /gateway/config` and `POST /gateway/health` accept requests with **no credential of any kind** — no API key header, no bearer token. Confirmed by reading the current gateway client code (it sends no `Authorization`/`X-Gateway-Key` header on either call) and reproducing directly against the API.

By contrast, `POST /gateway/telemetry/` **does** require `X-Gateway-Key`.

**Impact:**
- `/gateway/config` returns full device and tag configuration (device names, Modbus register maps, poll intervals) to any caller who can reach the host — no gateway identity required.
- `/gateway/health` accepts a health report for *any* `gateway_id` string in the POST body, from anyone. A caller can impersonate any gateway's health status (e.g., report `BBJ-GW-001` as online while it's actually down, or flood fake health records).

**Recommendation:** Require the same `X-Gateway-Key` (or a config-scoped variant) on both endpoints that `/gateway/telemetry/` already enforces.

---

## 2. No credential revocation/rotation path (Medium)

`POST /gateway/auth/create?gateway_id=...&gateway_name=...` is the only gateway-credential endpoint in the API (confirmed via the full `/openapi.json` route list — no `DELETE`, `PUT`, or regenerate route exists for gateway credentials). It:
- Requires an authenticated admin (`OAuth2PasswordBearer`)
- Returns `409 Gateway already exists` if called again with an existing `gateway_id`
- Has no counterpart to invalidate a previously issued key

**Impact:** The original key issued to `gateway_id=BBJ-GW-001` had been committed in plaintext to the gateway's local git history. Because there is no revoke path, we could not invalidate it — we worked around this by registering a new identity (`BBJ-GW-001-v2`) and pointing the gateway at that instead. **The original `BBJ-GW-001` credential is still valid and accepted by the backend today.** Whoever has DB access needs to manually invalidate it.

**Recommendation:** Add a `DELETE /gateway/auth/{gateway_id}` (or similar) endpoint, and/or make `POST /gateway/auth/create` support explicit rotation (invalidate + reissue) for an existing `gateway_id` rather than erroring out.

---

## 3. Default admin credentials with full privileges (Critical)

Login as `admin` / `admin123` succeeds and returns a JWT with `role: super_admin` and the full permission set: `dashboard.view, device.view, device.create, device.update, device.delete, device.configure, telemetry.view, telemetry.export, alarm.view, alarm.acknowledge, alarm.configure, report.view, report.generate, report.schedule, user.view, user.manage, gateway.view, gateway.configure, settings.manage, audit.view`.

**Impact:** Full administrative control over the platform (device config, users, settings, audit log) is protected by a trivially guessable default password. This is the most urgent item on this list.

**Recommendation:** Change the password immediately (see #4 for why this isn't currently possible through the API) and confirm no other accounts use default/weak passwords.

---

## 4. No working password-change endpoint (High — blocks fixing #3)

`PUT /users/{user_id}` accepts a generic JSON body (`additionalProperties: true` in the OpenAPI schema) and successfully updates `email`, `role`, `active` — but explicitly rejects a `password` field:

```
PUT /users/1  {"password": "..."}
→ 422 {"detail": "Unsupported fields: password"}
```

No other endpoint in the API (checked the full route list) offers password reset/change for an *existing* user. `POST /auth/register` only creates new users.

**Impact:** There is currently no way to change `admin`'s password without either (a) a backend code fix, or (b) direct database access to update the password hash. We deliberately did **not** attempt to delete and recreate the `admin` user via the API to work around this — with only one `super_admin` account on the system, that path risked permanently losing admin access if role assignment on re-registration didn't behave as expected.

**Recommendation:** Add a proper `PATCH /users/{user_id}/password` (or similar) endpoint that accepts the new password, hashes it server-side, and updates it — ideally requiring the current password or an admin-initiated reset flow.

---

## 5. Plain HTTP, no TLS (Medium)

The entire API (`http://34.131.199.29:8000`) is served over unencrypted HTTP. All traffic — including the `X-Gateway-Key` header, the JWT bearer token from `/auth/login`, and the `admin`/`admin123` login request body — is sent in cleartext.

**Recommendation:** Put the API behind TLS (e.g., a reverse proxy with a cert, or a managed load balancer) and redirect HTTP to HTTPS.

---

## Suggested priority order

1. **#3 + #4 together** — the password gap is what's blocking the credential fix, so they should land in the same effort.
2. **#1** — unauthenticated config/health endpoints are an easy, high-value fix (reuse the existing key-check logic from `/gateway/telemetry/`).
3. **#2** — needed to fully close out the exposed-key incident (revoke `BBJ-GW-001`).
4. **#5** — larger infra change, but should be on the roadmap.

---

*Note: this covers what surfaced incidentally while working on the gateway client. It is not a systematic security review of the backend — a proper audit of auth flows, input validation, and the remaining ~50 routes in the API is still worth doing separately.*
