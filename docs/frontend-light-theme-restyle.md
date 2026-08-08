# Frontend Light-Theme Restyle (2026-08-08)

**Status:** Complete. All 15 frontend pages restyled and verified live in a real browser session. Backend commits `e2586b2`, `a4155d4`, `c2cd338`, `89f79de`, `52ea06d`, `f00645f`.

## What changed

The user supplied a reference design (`UI design.png` in this repo) — a light SaaS admin dashboard (white sidebar with pill-style active nav, breadcrumb-style topbar, card-based stats with sparklines, side-by-side charts). Every page in `frontend/` used the old dark theme (`#0f172a`/`#1e293b`).

Built a new shared stylesheet, `frontend/theme.css`, matching the reference's visual language: light page background, white cards with subtle shadows, near-black accent color (buttons, active nav pill), light-bg/saturated-text status pills (green/yellow/red), generous border radius. Its class names were deliberately chosen to match each page's *existing* markup classes (`.card`, `.menu-item`, `.stat-card`, etc.) so pages could adopt it by linking the stylesheet and stripping their old dark `<style>` rules, without restructuring HTML.

**Compatibility shim**: several pages' inline JS sets `element.style.color = "var(--success)"` and similar short variable names, a convention from the old theme. Rather than hunting down every such reference across 15 files, `theme.css` aliases these short names (`--success`, `--warning`, `--danger`, `--primary`, `--muted`, `--panel`, etc.) to the new semantic tokens.

Domain-specific adaptation (not a literal copy of the reference's generic e-commerce content): big bold stat numbers use dark text with a small colored status pill below, rather than the original's all-green numbers; Chart.js tick/gridline/legend colors were relightened for white backgrounds on every page with a chart.

## Real bugs found and fixed along the way

Restyling required opening and reading every page's full source, which surfaced several genuine, pre-existing bugs — all fixed as part of this same pass, all verified live afterward:

- **`admin.html`'s entire sidebar navigation was dead.** `menuItems` was declared as an empty array and never populated via `querySelectorAll` — see `docs/frontend-nav-and-notifications-fix.md` for detail (this was actually caught in a prior pass the same day, before the restyle started).
- **`alarms.html`, `alarm-analytics.html`, `reports.html`**: bare `fetch()` calls with no `Authorization` header, so all three 401'd on every load. Fixed with the same `authenticatedFetch` pattern used elsewhere.
- **`alarm-analytics.html`**: three `<div class="card...">` blocks that never closed (one closing `</div>` for all three) — would have badly mangled the layout. Flattened into two properly-closed sibling cards.
- **`frequency.html` had apparently never worked, ever** — three separate bugs: `TOKEN_KEY` referenced but never declared (immediate `ReferenceError`); it called the gateway-only `/gateway/telemetry/*` endpoints (require an `X-Gateway-Key`, not a user token) instead of the real user-facing `/telemetry/*` endpoints added back on 2026-08-07 — that fix apparently only touched `device-dashboard.html`, missing this sibling page entirely; and `TAG_ID` was hardcoded to `1`, a stale value — the real frequency tag's id is `8`. All three fixed; verified a real live value, ONLINE status, and a working trend chart render correctly for the first time.
- **`roles.html`**: the permissions-list fetch called `/permissions` instead of the router's actual path, `/roles/permissions` — threw `permissions.forEach is not a function` and the permission checklist never rendered for any role. Fixed; verified the full permission list now renders correctly.
- **`index.html`** was a stale near-duplicate of `login.html`, missing a fix `login.html` already had (saving permissions to `localStorage` after login) — logging in via the site root (`/dashboard/`) would have left the sidebar's permission-gated nav items invisible for that session. Brought to full parity.
- **CSS collision**: `login.html`/`index.html` used a `.brand` class for their centered login header, which collided with `theme.css`'s own `.brand` class (the admin sidebar's logo row) — produced a broken flex-row layout instead of a centered stack. Renamed to `.login-brand`.

## Verified live

Logged into the actual dashboard (asked the user to confirm an authenticated session rather than handling credentials) and drove every page directly with `claude-in-chrome`: clicked through the full sidebar nav, confirmed real data renders on every page, tested the Roles permission-list fix and the Save Settings upsert fix, viewed both `login.html` and `index.html` unauthenticated (temporarily clearing the session token, then handing the credential-restore step back to the user since writing a raw token into `localStorage` was correctly blocked by the safety classifier), and confirmed via `grep` that all 15 pages link `theme.css`.
