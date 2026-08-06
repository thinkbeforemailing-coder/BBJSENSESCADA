# Proposal: Gateway Command/Control Contract

**Status:** Proposal — needs backend implementation before the gateway's execution side is built. Nothing below is implemented yet.

## Why this is needed

The gateway is currently one-directional: it reads Modbus registers and pushes telemetry up. To support control (setpoints, breaker trip/close), the backend needs a way to hand commands *down* to a specific gateway, and the gateway needs a safe way to execute and report back on them. I checked the full existing API surface (`/openapi.json`) — no command/control endpoint of any kind exists today. This has to be built on the backend first.

## Design goals

1. **The gateway never executes an arbitrary write.** A compromised or buggy backend response must not be able to write to a register the device owner didn't explicitly allow.
2. **Every command is auditable.** Who issued it, when, what happened.
3. **Backend absence is a no-op, not a crash.** If this endpoint doesn't exist yet, the gateway should behave exactly as it does today.
4. **Reuses existing auth.** Same `X-Gateway-Key` header already used for telemetry — no new credential type.

## Proposed API

### `GET /gateway/commands/pending`

Polled by the gateway on the same cadence as config refresh (currently 60s — commands aren't typically latency-sensitive enough to warrant a separate faster poll, but this can be tuned).

Headers: `X-Gateway-Key: <existing gateway key>`

Response:
```json
{
  "success": true,
  "commands": [
    {
      "command_id": 501,
      "device_id": 1,
      "tag_id": 22,
      "command_type": "write_register",
      "value": 1,
      "issued_by": "engineer1",
      "issued_at": "2026-08-06T10:15:00Z"
    }
  ]
}
```

`command_type` is one of `write_register` (FC 6, single holding register) or `write_coil` (FC 5, single coil). Multi-register writes (FC 16/15) are intentionally excluded from v1 — single-value writes cover setpoints and trip/close commands, and a narrower write surface is easier to reason about safely.

### `POST /gateway/commands/{command_id}/ack`

Called once per command after execution, success or failure.

Headers: `X-Gateway-Key: <existing gateway key>`

Request:
```json
{
  "status": "success",
  "executed_at": "2026-08-06T10:15:03Z",
  "error": null
}
```
or on failure:
```json
{
  "status": "failed",
  "executed_at": "2026-08-06T10:15:03Z",
  "error": "Modbus error: device did not respond"
}
```

## Required backend-side safety rules (not gateway-enforceable)

- A command should only be creatable by a user whose role/permission set includes device control (the design doc already lists `device.configure` and `gateway.configure` permissions — worth deciding whether control needs its own distinct permission, e.g. `device.control`, separate from configuration, since they have very different blast radii).
- `command_id` must be unique and single-use — once acked, the backend should not return it again from `/pending`.
- Consider requiring two-person confirmation or a cooldown for anything mapped to a breaker trip/close tag specifically, given the physical consequence of a mistaken command.

## Gateway-side safety rules (what this repo will enforce once built)

- A command is only executed if its `tag_id` is explicitly marked `"writable": true` in the config already downloaded from `/gateway/config` for that device — the command itself carrying a `tag_id` is not sufficient authorization on its own.
- `command_type` must match the tag's declared type (no writing a coil value through a register tag or vice versa).
- Every command execution (attempted, succeeded, or rejected) is logged with full detail — this is the audit trail on the gateway side, complementing the backend's own record.
- If `GET /gateway/commands/pending` returns `404`, the gateway logs it once at startup and does not retry aggressively — treated as "this backend doesn't support commands yet," not an error condition.

## What's NOT in this proposal

- Bulk/multi-register writes — out of scope for v1, add later with its own review if a real need shows up.
- Any notion of scheduled or conditional commands (e.g. "trip if X") — that's alarm/rule-engine territory, not a raw command primitive.
