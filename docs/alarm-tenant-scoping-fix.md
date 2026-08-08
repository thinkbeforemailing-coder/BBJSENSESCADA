# Alarm System Tenant Scoping — Fixed (2026-08-08)

**Status:** Fixed and verified live. Backend commit `0a29b39`.

## What was wrong

`alarm_rules` and `alarm_events` — the core, device-level alarm system (not the separate `gateway_alarm_events`/`notification_history` gap fixed earlier the same day) — had no `tenant_id` column at all. Every endpoint touching them was permission-gated (`alarm.view`/`alarm.configure`/`alarm.acknowledge`) but never tenant-filtered:

- `alarm_rules.py` — full CRUD (create/list/get/update/delete/toggle) on alarm configuration
- `alarm_history.py`, `alarm_analytics.py` (4 endpoints), `alarm_metrics.py` — read access to every alarm event platform-wide
- `device_alarm.py` — active/history/**acknowledge**/**close** on any alarm, including two state-changing writes
- `reports.py`'s `POST /reports/generate/alarm` — would include any tenant's alarms in a generated report

Any authenticated user with the relevant permission could see, edit, delete, or acknowledge/close any tenant's alarm rules and events, platform-wide.

This platform is single-tenant today (same situation as the earlier gateway-alarm fix), so nothing was actively exploitable — but there was no defense-in-depth if a second tenant is ever onboarded, and this is the *core* alarm system, more central than the gateway-specific one already fixed.

## Fix

- Added `tenant_id` (Integer FK to `tenants.id`, `NOT NULL`, indexed) to both tables via migration `5bb1058a2ccd`, backfilled from each row's `device_id -> devices.tenant_id` — 100% join coverage verified before backfilling, zero nulls after.
- `alarm_rules.py`: `tenant_id` is always derived from the authenticated identity on create, never trusted from the request body (the schema has no `tenant_id` field). All 6 endpoints filter/check by `current_user["tenant_id"]`, matching the pattern `devices.py` already established elsewhere in this backend.
- `alarm_history.py`, `alarm_analytics.py`, `alarm_metrics.py`, `device_alarm.py`, `reports.py`: every `AlarmEvent` query now filters by `tenant_id`.
- `alarm_engine.py`: real (non-shadow-mode) `AlarmEvent` creation now stamps `tenant_id` from the triggering rule.

## Verified live

ruff/pytest clean, migration applied (zero-null backfill confirmed), CI green, service restarted with all three background schedulers starting cleanly, no errors in a post-deploy soak, and confirmed every touched endpoint still returns 401 anonymously.
