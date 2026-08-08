# Frontend Navigation & Notifications — Fixed (2026-08-08)

**Status:** Fixed, deployed, and verified live in a real browser session (backend commit `d13b0d2`).

## What was actually wrong

Investigating "what's left on frontend" started as "3 pages are unreachable" but turned into a much bigger single root cause:

**`admin.html`'s entire sidebar navigation was non-functional.** `let menuItems = [];` was declared and never actually assigned via `querySelectorAll` — so the click handler that loads a page into the content `<iframe>` was attached to zero buttons. Clicking Dashboard, Frequency, Device Management, Device Tags, Trends, Alarms, Reports, or Notifications did nothing at all; only the iframe's default `src` (the live dashboard) was ever visible. The only buttons that responded to clicks were the two `coming-soon` placeholders (Users, Settings), which use a separate, correctly-wired handler.

This single bug explained the earlier "orphaned pages" finding — `alarm-rules.html`, `users.html`, and `roles.html` weren't just missing buttons, *nothing* was reachable by clicking, including pages that already had a properly configured `data-url` button (Alarms, Reports, Notifications).

**Also found and fixed in the same file**: a malformed "Device Management" button that never closed — no icon/text spans, no closing `</button>` tag, with the next button's markup effectively swallowed into it.

## Fix

- `menuItems = document.querySelectorAll(".menu-item[data-url]")` — the actual missing line. This alone made every already-correctly-configured button (Alarms, Reports, Notifications, Device Tags, API Docs) start working.
- Closed the malformed Device Management button properly.
- Added a working "Alarm Rules" button (`/dashboard/alarm-rules.html`, gated on `alarm.configure`) — needed to configure any of the alarm types built earlier today, including `anomaly` and `communication_loss`, both of which had no UI path to reach until now.
- "Users" was marked `coming-soon` despite `users.html` already being a fully built, working page — wired it up properly (real `data-url`, `data-title`, `data-subtitle`).
- Added a new "Roles" button (`/dashboard/roles.html`) — no placeholder existed at all before.
- Left "Settings" as `coming-soon` — no `settings.html` file exists, genuinely not built yet.

**`notifications.html`** had its own, separate bug: its history fetch (`fetch("/notifications/history")`) sent no `Authorization` header at all, despite that endpoint requiring auth — so the page always 401'd and silently showed an empty table regardless of who was logged in. Fixed, and added a real settings form: the backend's `GET`/`POST /notifications/settings` existed with zero frontend calling it anywhere, meaning the only way to configure a recipient's email/mobile/channel toggles/severity filter was direct DB or API access (exactly what this session had to do manually before this fix).

**Backend bug found and fixed while building that settings form**: `POST /notifications/settings` always created a new row, with no update/upsert logic. Left as-is, clicking "Save" a second time would silently create a duplicate settings row for the same user — and `send_alarm_notification()` would then notify them twice per alarm. Made it a proper upsert (update the existing row for that user if one exists).

**Also removed**: 11 stale backup/`.save` files sitting in `frontend/` (`admin_backup.html`, `admin-broken-backup.html`, `alarm-rules-backup.html`, `device-dashboard.html.save`/`.save.1`, `users_backup.html`, etc.) — publicly web-accessible since the whole directory is mounted as static files. These weren't caught by the 2026-08-07 cleanup because that pass only matched a `*-before-*` naming pattern; these use `-backup`/`_backup`/`.save` instead.

## Verified live, in a real browser (not just code review)

Logged into the actual dashboard and drove it directly:
- Clicked "Alarm Rules" — loaded correctly, title/subtitle updated, all 4 rules visible (including today's `anomaly` and `communication_loss` rules)
- Clicked "Users" — loaded real user list (2 users, correct roles/status)
- Clicked "Roles" — loaded the roles/permissions editor
- Clicked "Notifications" — history loaded with real counts (no more silent 401), settings form pre-populated with the real saved values
- Clicked "Save Settings" — got "Settings saved.", then confirmed via direct DB query that it updated the existing row rather than creating a duplicate
- Queried the live `alarmType` dropdown via JS: all 8 types present (`high`, `high_high`, `low`, `low_low`, `digital_on`, `digital_off`, `communication_loss`, `anomaly`)

ruff/pytest clean, CI green, service restarted with no errors in the logs.
