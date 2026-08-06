# BBJ Sense Gateway

Windows-based industrial gateway agent for the BBJ Sense SCADA/IoT platform. Runs on-site as a Windows Service, polls Modbus devices (RTU and TCP), and pushes telemetry to the BBJ Sense cloud backend.

See `docs/design.pdf` for the full platform design summary (backend, multi-tenancy, roles, roadmap). This repo is the gateway agent specifically — one piece of that platform.

## Architecture

```
start_gateway.py  (entry point, runs as the "BBJ Sense Gateway" Windows service via NSSM)
  │
  ├── watchdog loop: checks every 5s, restarts either child if it dies
  │
  ├── dynamic_modbus_poller.py   (telemetry + control)
  │     ├── downloads device/tag config from the backend every 60s
  │     ├── polls each device's tags over Modbus RTU or TCP
  │     ├── decodes/scales/quality-checks each value, posts to the backend
  │     ├── on POST failure: buffers to local SQLite (offline_buffer.py),
  │     │     retries every 10s until the backend is reachable again
  │     ├── caches last-known-good config locally (config_cache.py),
  │     │     so a backend outage at startup doesn't leave devices idle
  │     ├── tracks per-device connected/failed state (device_status.py)
  │     └── polls for pending control commands (gateway_commands.py),
  │           executes write_register/write_coil against a safety gate,
  │           acks the result back to the backend
  │
  └── gateway_health_reporter.py  (health)
        └── posts CPU/memory/disk/uptime + real device counts every 60s
```

All inter-process state (device status, cached config) is exchanged via small atomically-written JSON files on disk, since the poller and health reporter are separate OS processes with no shared memory.

## Tech stack

- Python 3.12, `pymodbus` (Modbus RTU/TCP), `pyserial`, `requests`, `psutil`
- SQLite (offline telemetry buffer)
- Windows Service via [NSSM](https://nssm.cc/), registered as **`BBJ Sense Gateway`**
- `pytest` for tests (dev-only, see `requirements-dev.txt`)

## Configuration

All runtime configuration is via environment variables — nothing is hardcoded in source:

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `BBJ_GATEWAY_KEY` | **Yes** | none | Auth key sent as `X-Gateway-Key` on telemetry/command requests. The poller refuses to start without it. |
| `BBJ_API_BASE_URL` | No | `http://34.131.199.29:8000` | Backend base URL. |
| `BBJ_GATEWAY_ID` | No | `BBJ-GW-001-v2` | This gateway's identity, used in health reports and command polling. |
| `BBJ_GATEWAY_NAME` | No | `BBJ Windows Gateway 01` | Display name in health reports. |

Device and tag configuration (Modbus addresses, data types, poll intervals, scaling, `writable` flags) is **not** stored in this repo — it's pulled from the backend's `/gateway/config` endpoint every 60 seconds and cached locally for resilience.

## Deploying / running as a service

The gateway runs under [NSSM](https://nssm.cc/), pointed at `start_gateway.py`. Environment variables for a service (unlike a login shell) need to go through NSSM directly, not `setx`, since the Service Control Manager doesn't pick up machine env var changes without a reboot:

```powershell
& "C:\nssm\win64\nssm.exe" set "BBJ Sense Gateway" AppEnvironmentExtra "BBJ_GATEWAY_KEY=<your key>"
& "C:\nssm\win64\nssm.exe" restart "BBJ Sense Gateway"
```

To install the service fresh (if it doesn't exist yet):
```powershell
& "C:\nssm\win64\nssm.exe" install "BBJ Sense Gateway" "C:\bbj-sense-gateway\venv\Scripts\python.exe" "-u" "C:\bbj-sense-gateway\start_gateway.py"
& "C:\nssm\win64\nssm.exe" set "BBJ Sense Gateway" AppDirectory "C:\bbj-sense-gateway"
& "C:\nssm\win64\nssm.exe" set "BBJ Sense Gateway" AppEnvironmentExtra "BBJ_GATEWAY_KEY=<your key>"
& "C:\nssm\win64\nssm.exe" set "BBJ Sense Gateway" Start SERVICE_AUTO_START
```

## Logs

All logs rotate at 5MB with 5 backups, under `logs/`:

| File | Written by |
|---|---|
| `telemetry_poller.log` | `dynamic_modbus_poller.py` and its helper modules (offline buffer, config cache, commands) |
| `gateway_health.log` | `gateway_health_reporter.py` and `device_status.py` |
| `startup_manager.log` | `start_gateway.py` (process start/stop/restart events, watchdog activity) |

The `%(name)s` field in each log line identifies the specific subsystem (e.g. `bbj-sense-offline-buffer`, `bbj-sense-gateway-commands`) even when multiple modules share one file.

## Running tests

```powershell
venv\Scripts\python.exe -m pip install -r requirements-dev.txt
venv\Scripts\python.exe -m pytest
```

**Do not run `pytest` without the `tests/` scoping in `pytest.ini`.** The repo root also contains several `test_*.py` files (`test_current.py`, `test_modbus_driver.py`, etc.) — these are manual, one-off hardware-scanning scripts that open the real serial port on import, not actual tests. `pytest.ini` restricts discovery to `tests/` specifically so these never get collected.

## Repo layout

```
start_gateway.py            entry point + process watchdog
dynamic_modbus_poller.py    telemetry polling (RTU/TCP) + command execution
gateway_health_reporter.py  health reporting
settings.py                 shared config (env-var backed)
offline_buffer.py           local SQLite telemetry queue
device_status.py            per-device connected/failed tracking (shared via JSON)
config_cache.py             last-known-good config cache (shared via JSON)
gateway_commands.py         control command polling/execution/ack
logging_config.py           shared rotating-file logger setup
tests/                      pytest suite
docs/                       design docs, security findings, proposals
```

## Known limitations / open work

See `docs/` for details on each:
- `backend-security-findings.md` — backend-side gaps found during gateway work (unauthenticated config/health endpoints, credential rotation, default admin password)
- `gateway-command-contract.md` — control command support is implemented gateway-side but inactive until the backend implements the corresponding endpoint
- `anomaly-detection-proposal.md` — proposed approach for anomaly-based alarms (backend work, not this repo)

Only Modbus function codes 3/4 are supported for reads, and 5/6 for writes (no multi-register/multi-coil writes in v1).
