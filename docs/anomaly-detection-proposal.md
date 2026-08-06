# Proposal: Anomaly-Based Alarms

**Status:** Proposal only — not implemented anywhere. For the backend team, not this gateway repo.

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
