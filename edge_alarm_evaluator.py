import logging
import threading
import time
from datetime import datetime, timezone

import requests

from settings import API_BASE_URL, GATEWAY_KEY, HTTP_TIMEOUT_SECONDS


# Deliberately NOT setup_logger() -- see offline_buffer.py for why.
logger = logging.getLogger("telemetry-poller.edge_alarm_evaluator")

EDGE_ALARM_INTERVAL_SECONDS = 5

# Gateway-evaluated alarms don't yet push real state changes to the
# cloud -- they log what *would* happen so the evaluation logic can
# be sanity-checked against real readings before it's trusted to
# change live alerting. Same shadow-mode-before-cutover pattern as
# the backend's own ANOMALY_SHADOW_MODE
# (app/services/alarm_engine.py in the backend repo). Flip to False
# once that trial period is done -- the real push path below is
# already fully implemented, not a stub, so cutover is a one-line
# change here plus a deploy.
EDGE_ALARM_SHADOW_MODE = True

STATE_CHANGE_URL = f"{API_BASE_URL}/gateway/alarms/state-change"

_state_lock = threading.Lock()

# (device_id, tag_id) -> {"value": float, "quality": str, "timestamp": datetime}
_latest_readings: dict[tuple[int, int], dict] = {}

# rule_id -> True while that rule is considered triggered locally.
_active_state: dict[int, bool] = {}

_rules_lock = threading.Lock()
_current_alarm_rules: list[dict] = []


def set_current_alarm_rules(alarm_rules: list[dict] | None) -> None:
    """Called whenever the gateway's config refreshes (see
    dynamic_modbus_poller.main()) so the evaluator always checks
    against the latest rules without the evaluation loop needing to
    know anything about config download/caching itself."""

    with _rules_lock:
        _current_alarm_rules[:] = alarm_rules or []


def record_latest_reading(
    device_id: int,
    tag_id: int,
    value: float,
    quality: str,
) -> None:
    """Called from save_telemetry() right after every successful
    poll -- cheap in-memory update, no I/O, so it can't slow down the
    poll hot path the way a database read would."""

    with _state_lock:
        _latest_readings[(device_id, tag_id)] = {
            "value": value,
            "quality": quality,
            "timestamp": datetime.now(timezone.utc),
        }


def _evaluate_condition(
    rule: dict,
    value: float,
    reading_timestamp: datetime,
) -> bool:
    """Mirrors the backend's alarm_engine.check_device_alarms
    condition-by-condition, intentionally kept in lockstep with it --
    "anomaly" is excluded because the backend never sends anomaly
    rules to /gateway/config (they need cloud-side baseline data this
    gateway doesn't have)."""

    alarm_type = rule.get("alarm_type")
    threshold = rule.get("threshold_value")

    if alarm_type in ("high", "high_high"):
        return threshold is not None and value >= threshold

    if alarm_type in ("low", "low_low"):
        return threshold is not None and value <= threshold

    if alarm_type == "digital_on":
        return value == 1

    if alarm_type == "digital_off":
        return value == 0

    if alarm_type == "communication_loss":
        if threshold is None:
            return False

        staleness_seconds = (
            datetime.now(timezone.utc) - reading_timestamp
        ).total_seconds()

        return staleness_seconds >= threshold

    return False


def _push_state_change(
    rule: dict,
    action: str,
    trigger_value: float,
) -> None:
    try:
        response = requests.post(
            STATE_CHANGE_URL,
            headers={"X-Gateway-Key": GATEWAY_KEY},
            json={
                "alarm_rule_id": rule["id"],
                "action": action,
                "trigger_value": trigger_value,
            },
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        logger.error(
            "Failed to push alarm state change | rule=%s action=%s "
            "error=%s",
            rule.get("alarm_name"),
            action,
            error,
        )


def evaluate_all_rules() -> None:

    with _rules_lock:
        rules_snapshot = list(_current_alarm_rules)

    with _state_lock:
        readings_snapshot = dict(_latest_readings)

    for rule in rules_snapshot:

        key = (rule.get("device_id"), rule.get("tag_id"))
        reading = readings_snapshot.get(key)

        if reading is None:
            continue

        triggered = _evaluate_condition(
            rule,
            reading["value"],
            reading["timestamp"],
        )

        rule_id = rule["id"]
        was_active = _active_state.get(rule_id, False)

        if triggered and not was_active:

            _active_state[rule_id] = True

            if EDGE_ALARM_SHADOW_MODE:
                logger.info(
                    "SHADOW ALARM (would open, not pushed -- shadow "
                    "mode): %s VALUE=%s THRESHOLD=%s",
                    rule.get("alarm_name"),
                    reading["value"],
                    rule.get("threshold_value"),
                )
            else:
                _push_state_change(
                    rule, "open", reading["value"]
                )

        elif not triggered and was_active:

            _active_state[rule_id] = False

            if EDGE_ALARM_SHADOW_MODE:
                logger.info(
                    "SHADOW ALARM (would close, not pushed -- "
                    "shadow mode): %s",
                    rule.get("alarm_name"),
                )
            else:
                _push_state_change(
                    rule, "close", reading["value"]
                )


def evaluator_worker() -> None:

    logger.info(
        "Edge alarm evaluator started (shadow_mode=%s)",
        EDGE_ALARM_SHADOW_MODE,
    )

    while True:

        try:
            evaluate_all_rules()
        except Exception:
            logger.exception("Edge alarm evaluator error")

        time.sleep(EDGE_ALARM_INTERVAL_SECONDS)
