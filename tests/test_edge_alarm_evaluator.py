from datetime import datetime, timedelta, timezone

import edge_alarm_evaluator


def reset_state(monkeypatch):
    monkeypatch.setattr(edge_alarm_evaluator, "_latest_readings", {})
    monkeypatch.setattr(edge_alarm_evaluator, "_active_state", {})
    monkeypatch.setattr(edge_alarm_evaluator, "_current_alarm_rules", [])
    monkeypatch.setattr(edge_alarm_evaluator, "EDGE_ALARM_SHADOW_MODE", True)


def now():
    return datetime.now(timezone.utc)


def test_high_alarm_triggers_at_or_above_threshold():
    rule = {"alarm_type": "high", "threshold_value": 50.0}
    assert edge_alarm_evaluator._evaluate_condition(rule, 50.0, now()) is True
    assert edge_alarm_evaluator._evaluate_condition(rule, 49.9, now()) is False


def test_low_alarm_triggers_at_or_below_threshold():
    rule = {"alarm_type": "low", "threshold_value": 10.0}
    assert edge_alarm_evaluator._evaluate_condition(rule, 10.0, now()) is True
    assert edge_alarm_evaluator._evaluate_condition(rule, 10.1, now()) is False


def test_digital_on_triggers_only_at_value_one():
    rule = {"alarm_type": "digital_on"}
    assert edge_alarm_evaluator._evaluate_condition(rule, 1, now()) is True
    assert edge_alarm_evaluator._evaluate_condition(rule, 0, now()) is False


def test_digital_off_triggers_only_at_value_zero():
    rule = {"alarm_type": "digital_off"}
    assert edge_alarm_evaluator._evaluate_condition(rule, 0, now()) is True
    assert edge_alarm_evaluator._evaluate_condition(rule, 1, now()) is False


def test_communication_loss_triggers_after_staleness_threshold():
    rule = {"alarm_type": "communication_loss", "threshold_value": 30}

    fresh = now()
    assert edge_alarm_evaluator._evaluate_condition(rule, 0, fresh) is False

    stale = now() - timedelta(seconds=60)
    assert edge_alarm_evaluator._evaluate_condition(rule, 0, stale) is True


def test_unknown_alarm_type_never_triggers():
    rule = {"alarm_type": "anomaly", "threshold_value": 3}
    assert edge_alarm_evaluator._evaluate_condition(rule, 999, now()) is False


def test_evaluate_all_rules_shadow_mode_logs_open_and_close(monkeypatch):
    reset_state(monkeypatch)

    pushed = []
    monkeypatch.setattr(
        edge_alarm_evaluator,
        "_push_state_change",
        lambda *args, **kwargs: pushed.append(args),
    )

    edge_alarm_evaluator.set_current_alarm_rules(
        [
            {
                "id": 1,
                "device_id": 10,
                "tag_id": 20,
                "alarm_name": "Test High Alarm",
                "alarm_type": "high",
                "threshold_value": 50.0,
            }
        ]
    )

    # Below threshold -- no transition, nothing active.
    edge_alarm_evaluator.record_latest_reading(10, 20, 10.0, "good")
    edge_alarm_evaluator.evaluate_all_rules()
    assert edge_alarm_evaluator._active_state.get(1) is None

    # Crosses threshold -- opens.
    edge_alarm_evaluator.record_latest_reading(10, 20, 60.0, "good")
    edge_alarm_evaluator.evaluate_all_rules()
    assert edge_alarm_evaluator._active_state[1] is True

    # Drops back below -- closes.
    edge_alarm_evaluator.record_latest_reading(10, 20, 10.0, "good")
    edge_alarm_evaluator.evaluate_all_rules()
    assert edge_alarm_evaluator._active_state[1] is False

    # Shadow mode never actually pushes to the cloud.
    assert pushed == []


def test_evaluate_all_rules_pushes_when_shadow_mode_off(monkeypatch):
    reset_state(monkeypatch)
    monkeypatch.setattr(edge_alarm_evaluator, "EDGE_ALARM_SHADOW_MODE", False)

    pushed = []
    monkeypatch.setattr(
        edge_alarm_evaluator,
        "_push_state_change",
        lambda rule, action, value: pushed.append((rule["id"], action, value)),
    )

    edge_alarm_evaluator.set_current_alarm_rules(
        [
            {
                "id": 1,
                "device_id": 10,
                "tag_id": 20,
                "alarm_name": "Test High Alarm",
                "alarm_type": "high",
                "threshold_value": 50.0,
            }
        ]
    )

    edge_alarm_evaluator.record_latest_reading(10, 20, 60.0, "good")
    edge_alarm_evaluator.evaluate_all_rules()

    assert pushed == [(1, "open", 60.0)]
