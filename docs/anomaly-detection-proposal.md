# Proposal: Anomaly-Based Alarms

**Status:** Built 2026-08-08, running in shadow mode on the live backend (commit `3a06fe2`). No alarm rule uses it yet, and shadow mode means it won't create real alarms/notifications even once one does, until `ANOMALY_SHADOW_MODE` is flipped off in `alarm_engine.py`. See "Built (2026-08-08)" at the bottom for what's live vs. what's still a manual step.

## Why this doesn't belong in the gateway

`bbj-sense-gateway` (this repo) reads live Modbus registers and forwards each value immediately — it has no memory of history and sees only the devices physically wired to it. Anomaly detection needs a baseline built from historical telemetry across time (and ideally across similar devices/sites), which only exists in the backend's PostgreSQL telemetry table. This is backend work.

## Fit with the existing roadmap

`design.pdf`'s alarm system already lists this as adjacent future work:

> Future: Over current, Breaker trip, Device offline, Communication failure

Anomaly detection is a natural extension of that same alarm pipeline — not a separate system.

## Recommended approach: start statistical, not ML

For electrical telemetry (frequency, voltage, current, power factor), a full ML model is disproportionate to start with — these signals have well-understood normal operating ranges and simple statistics catch the vast majority of real anomalies:

1. **Per-tag rolling baseline** — mean and standard deviation over a trailing window (e.g. last 7 days, same tag).
2. **Flag deviations** — e.g. a reading more than N standard deviations from the rolling mean, or a sustained trend outside the historical range that the existing static min/max thresholds wouldn't catch (those are fixed thresholds; this catches drift *within* the fixed range that's still abnormal for that specific device).
3. **Feed into the existing alarm system** as a new alarm type (`alarm.acknowledge`, `alarm.configure` permissions already exist) rather than a separate notification path.
4. **Only revisit ML** (e.g. seasonal decomposition for load patterns, or a proper forecasting model) if the statistical approach demonstrably misses real cases in practice — start simple, earn the complexity.

## What this needs from the gateway side (already true today)

Nothing new. The gateway already reliably delivers timestamped, quality-flagged telemetry (`good`/`out_of_range`) for every tag — that's the only input this needs. No gateway changes required to support this.

---

## Scoped design (2026-08-08)

Reviewed the live backend to ground this in actual data, not guesswork: `telemetry_values` has 118,859 rows across 9 distinct (device, tag) pairs, ~14,400 rows/tag over the last 5 days (a reading roughly every 30s), table size is 18MB, and every row so far is `quality='good'`. Only 2 `alarm_rules` exist today (Low Frequency, High Voltage). At this scale, computing a 7-day mean/stddev on the fly is trivially cheap — but the design below decouples baseline computation from alarm evaluation anyway, since that's the right shape regardless of current scale and avoids a rewrite later.

### Schema: one new table, no changes to existing tables

```sql
CREATE TABLE tag_baselines (
    id SERIAL PRIMARY KEY,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES device_tags(id) ON DELETE CASCADE,
    mean_value FLOAT NOT NULL,
    stddev_value FLOAT NOT NULL,
    sample_count INTEGER NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (device_id, tag_id)
);
```

`alarm_rules.alarm_type` gets a third value, `"anomaly"`, alongside the existing `"high"`/`"low"` strings (it's a plain `String(30)` with no CHECK constraint, so this needs no migration). The existing `threshold_value` column is reused as the **standard-deviation multiplier** for anomaly rules (e.g. `3.0` = flag anything more than 3σ from the rolling mean) — same column, different meaning depending on `alarm_type`, consistent with how the table already overloads that field.

### New service: `anomaly_baseline_scheduler.py`

A fourth background thread alongside the existing `gateway_scheduler`/`alarm_scheduler`/`notification_scheduler` (same `threading.Thread(daemon=True)` pattern in `main.py`). Runs every 30–60 minutes, not every 5 seconds like the alarm loop — recomputing a rolling baseline doesn't need to happen at alarm-check frequency, and separating the two means a slow aggregate query never has a chance to block real-time alarm evaluation.

For each `(device_id, tag_id)` that has at least one enabled `anomaly`-type rule (skip computing baselines nobody asked for):

```sql
SELECT avg(value), stddev_samp(value), count(*)
FROM telemetry_values
WHERE device_id = :device_id AND tag_id = :tag_id
  AND quality = 'good'
  AND timestamp > now() - interval '7 days'
```

Upsert the result into `tag_baselines`. Postgres's native `stddev_samp()` does the math — no Python-side statistics needed.

### Evaluation: one new branch in `alarm_engine.py`'s `check_device_alarms()`

Alongside the existing `if rule.alarm_type == "high": ... elif == "low": ...`:

```python
elif rule.alarm_type == "anomaly":
    baseline = get_baseline(db, rule.device_id, rule.tag_id)

    if baseline is None or baseline.sample_count < MIN_SAMPLES_FOR_BASELINE:
        continue  # cold start: not enough history yet, skip silently

    if baseline.stddev_value < MIN_STDDEV_EPSILON:
        continue  # flat signal: any deviation would trigger; not meaningful yet

    z = abs(value - baseline.mean_value) / baseline.stddev_value
    alarm_triggered = z >= rule.threshold_value
```

Two guards worth calling out because they're easy to skip and both cause false positives if skipped: a **cold-start minimum sample count** (a tag with 20 minutes of history has no meaningful baseline — recommend requiring a full window's worth, e.g. 7 days, before evaluating at all) and a **near-zero-stddev guard** (a genuinely constant signal has σ≈0, so any tiny reading noise would compute as "infinite" standard deviations away and fire constantly).

V1 close/reset logic: simplest option is closing the alarm as soon as `z` drops back under the threshold, same as today's `high`/`low` handling without a separate `reset_value`. This risks some flapping right at the boundary — acceptable to start, and `reset_value` is already there to reuse for hysteresis (e.g. a lower z-threshold to reset) if flapping turns out to be a real problem in practice.

### What doesn't need to change

No new API endpoints — `alarm_rules.py`'s existing CRUD already handles arbitrary `alarm_type` strings. The only UI touch is the alarm-rule creation form: add `"anomaly"` as a selectable type, and relabel the threshold field to "Std Dev Multiplier" when that type is selected.

### Rollout recommendation: shadow mode first

Don't wire this straight into live `AlarmEvent`/notification creation on day one. Run the evaluation branch for a trial period (a week or two, matching the baseline window) logging what *would* have fired without actually creating alarm events or sending notifications, then review those against what the site operator would consider a real anomaly. This is cheap insurance against an early bug in the baseline math (e.g. mixing up mean/stddev order, or the cold-start guard being too permissive) turning into real spurious alerts to whoever's on the notification list.

### Effort estimate

Roughly a half-day to a day of implementation (one migration, one small scheduler service, one new branch in an existing function, one small frontend form tweak), plus the shadow-mode observation period before it's trusted to raise real alarms. Small in code volume; the actual cost is calendar time waiting to see the baseline behave sanely on real data.

## Built (2026-08-08)

Implemented exactly as scoped above — backend commit `3a06fe2`, deployed and verified live (ruff/pytest clean, migration applied, monitored soak showed clean startup with `Anomaly baseline scheduler started` and no errors).

**What's live:**
- `tag_baselines` table exists, migration `f20859f1e9cd` applied.
- `anomaly_baseline_scheduler.py` runs as a fourth background thread, recomputing every 30 minutes for any `(device_id, tag_id)` with an enabled `anomaly`-type rule. Currently a no-op — no such rule exists yet.
- `alarm_engine.py`'s `check_device_alarms()` has the `anomaly` branch with both guards (cold-start coverage check, near-zero-stddev check).
- `alarm-rules.html` has "Anomaly" as a selectable type, with the threshold field relabeling to "Std Dev Multiplier".

**First real rule created 2026-08-08** (rule id 6): "Active Power Anomaly" on the only device (`Main Incomer Meter`, id 1), tag `active_power` (id 14) — picked because Frequency and Voltage already have static threshold rules, and total active power is the most informative "is something behaving abnormally" signal for an incomer meter that wasn't already covered. Threshold set to `3.0` (3 standard deviations). Confirmed live in the logs (`ALARM CHECK: Active Power Anomaly ...`) within seconds of creation, no restart needed — the alarm loop reads rules fresh from the DB every 5s.

**Gotcha found while creating it, now fixed**: a DB-level `CHECK` constraint (`ck_alarm_type`) on `alarm_rules.alarm_type` — added in an earlier migration, never reflected in the SQLAlchemy model — only allowed `high/high_high/low/low_low/digital_on/digital_off/communication_loss`. Rejected the insert with `CheckViolation`. Fixed via migration `e29850117161`, extending the constraint to also allow `anomaly` rather than dropping it.

**Still a manual step, by design:**
- **Shadow mode is still on** (`ANOMALY_SHADOW_MODE = True` in `alarm_engine.py`). The rule is evaluating but currently skipping every cycle via the cold-start guard — no baseline exists yet, since the baseline scheduler only just started picking this pair up. Expect `ANOMALY CHECK` / `SHADOW ANOMALY` log lines to start appearing roughly 6 days from rule creation (once the baseline scheduler has enough history behind it), not immediately.
- Once you've watched shadow-mode output for a while and trust it, flip `ANOMALY_SHADOW_MODE` to `False` and redeploy to let it raise real alarms/notifications.
