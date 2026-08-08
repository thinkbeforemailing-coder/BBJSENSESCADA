# Remaining Alarm Types — Implemented (2026-08-08)

**Status:** Live. Backend commit `8ecdaa0`.

## What was missing

The `ck_alarm_type` DB constraint on `alarm_rules` (extended earlier the same day to allow `anomaly`) had always allowed `high_high`, `low_low`, `digital_on`, `digital_off`, and `communication_loss` — but `alarm_engine.py`'s `check_device_alarms()` only had evaluation branches for `high`/`low`/`anomaly`. A rule created with any of the other five types would sit there forever, never triggering, with no error anywhere. The frontend didn't even expose them as selectable options. This directly maps to `design.pdf`'s stated future work ("Over current, Breaker trip, Device offline, Communication failure") — someone had clearly scaffolded the schema for this and never finished the engine side.

No migration was needed — the constraint already allowed these values.

## What was built

- **`high_high` / `low_low`**: identical comparison logic to `high`/`low` (same direction), intended as a second, more severe tier configured as its own rule with its own threshold and severity — e.g. "High Voltage" at 240V (medium) and "High High Voltage" at 260V (critical) as two separate rules on the same tag. Reset-value hysteresis logic extended to cover them too, for parity.
- **`digital_on` / `digital_off`**: for binary/status tags (e.g. a breaker trip contact) — triggers while the tag reads `1` or `0` respectively. Maps to `design.pdf`'s "Breaker trip".
- **`communication_loss`**: per-tag staleness — triggers when the tag's latest telemetry reading is older than `threshold_value` seconds (reusing that column the same way `anomaly` reuses it as a stddev multiplier). This is deliberately distinct from `gateway_monitor.py`'s existing gateway-level `communication_loss` alarm, which detects the *whole gateway* going offline via heartbeat, not one specific tag going stale while the gateway itself is fine. Maps to `design.pdf`'s "Device offline"/"Communication failure".
- `alarm-rules.html`: all five now selectable in the alarm-type dropdown, with the threshold field's placeholder relabeling per type (seconds for `communication_loss`, "not used" for the two digital types).

Unlike `anomaly`, none of these run in shadow mode — they're simple, predictable comparisons with no risk of bad statistical math, so they behave exactly like the existing `high`/`low` alarms and raise real `AlarmEvent`s/notifications as soon as a rule using them is configured and enabled.

## Verified live

ruff/pytest clean, CI green, service restarted cleanly with all three schedulers starting, existing alarms (Low Frequency, High Voltage, Active Power Anomaly) still evaluating correctly post-deploy, no errors in a monitored soak. The five new branches haven't been exercised yet since no rule uses them — same "inert until configured" pattern as everything else built this session.

## `communication_loss` end-to-end test (2026-08-08)

Created rule id 7 ("Frequency Communication Loss", tag `frequency` on `Main Incomer Meter`) with a deliberately tiny threshold to force an immediate fire without needing to actually break anything. Confirmed the full real pipeline: fired on the first eval cycle → created a real, correctly tenant-stamped `AlarmEvent` → dispatched real notifications (email genuinely delivered to `bbjsense@gmail.com`, WhatsApp honestly reported "not configured") → no duplicate notifications on subsequent cycles (dedup logic held) → threshold then set to a sane production value (60 seconds) → confirmed via direct DB query that the alarm auto-closed once staleness returned under threshold.

**Kept live as a real rule** — rule id 7 now serves as an actual per-tag staleness watchdog on the frequency tag, not just a test artifact.
