# Dashboard Consolidation, Root Redirect & Date-Range Picker (2026-08-08)

**Status:** Implemented, deployed, and verified live in a real browser session (backend commit `7c21d35`).

## What changed

Five related requests, all touching `device-dashboard.html` or its surrounding shell:

1. **Removed the static Device Information card and "Dynamic telemetry display..." caption** from `device-dashboard.html`. That config (manufacturer/model/type/location/protocol/status) already lives in Device Management (`devices.html`) — showing it again on the live dashboard was redundant.

2. **Consolidated the graph into one section, driven by clicking a parameter tile** instead of a separate `<select id="tagSelector">` dropdown. Tiles (Frequency, Voltage, Current Total, etc.) are now clickable; clicking one calls `selectTag(tagId)`, which highlights the tile (`.tag-card.active`, thicker accent border) and reloads the trend chart for that tag. The tile grid and the chart now live inside one `<section class="chart-card">` rather than being visually separate pieces. The first tag is auto-selected on page load so the chart is never empty.

3. **Root domain (`https://www.bbjsense.com/`) now redirects to the login page** instead of returning a JSON status blob. `GET /` in `app/main.py` returns `RedirectResponse(url="/dashboard/index.html")` (307). `/health` is untouched and still returns JSON for uptime monitoring.

4. **Removed the standalone Frequency page and its sidebar entry.** `frequency.html` was a single-tag monitoring page that predated the tile-click consolidation above — with any tag selectable from the main dashboard now, it was fully redundant. Deleted `frontend/frequency.html` and its `menu-item` button in `admin.html`. Confirmed via grep that no other file referenced it before deleting.

5. **Custom date-range picker on the trend chart.** Added `from_date`/`to_date` (ISO date/datetime, optional) query params to `GET /telemetry/history/tag/{tag_id}`. Backward compatible: callers that omit both params get the exact same behavior as before (last N records, DESC then reversed client-side). When either is present, the query switches to ascending chronological order with a higher row cap (5000 vs 1000), and a bare date `to_date` is treated as inclusive-through-end-of-day (`23:59:59.999999`) rather than midnight — avoids a "picked today as both from and to, got zero rows" trap. Frontend adds `From`/`To` date inputs and `Apply`/`Clear` buttons next to the chart title.

## Verified live, in a real browser (not just code review)

- Loaded `https://www.bbjsense.com/` with no path — landed on the dashboard shell via the redirect chain, confirming the 307.
- Confirmed via curl: `HTTP/1.1 307 Temporary Redirect`, `Location: /dashboard/index.html`.
- Confirmed the Device Information card and its caption are gone; Frequency is gone from the sidebar.
- Confirmed the Frequency tile auto-selects and highlights on page load with real chart data.
- Clicked the Voltage tile — active-tile highlight moved to Voltage, chart title updated to "Historical Trend — Voltage", chart re-rendered with real voltage data (~77–78.6V range).
- Set a date range (2026-08-07 to 2026-08-08) and clicked Apply — chart switched from the default last-50-points window to the full requested range (many more points, wider time span, 04:56am–7:14pm+).
- Clicked Clear — date inputs emptied and chart reverted to the default recent-window view.

ruff/pytest clean, service restarted with no errors in the logs.
