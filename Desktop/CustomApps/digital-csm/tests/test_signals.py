"""
Tests for SignalDetector: validates signal parsing and urgency classification
against controlled fixture data for all seven defined signals.

Fixture injection pattern: construct a SignalDetector via __new__ and replace
_bq / _segment with fake clients that return controlled rows. No monkeypatching
framework needed — the fake clients are simple inline classes.
"""

from __future__ import annotations

import pytest
from agents.signal_detector import Signal, SignalDetector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_detector(
    signal_rows: list[dict] | None = None,
    segment_events: list[dict] | None = None,
) -> SignalDetector:
    """Return a SignalDetector backed by controlled fixture data."""
    detector = SignalDetector.__new__(SignalDetector)

    class _FakeBQ:
        def get_signal_summary(self, account_id):
            return signal_rows or []

    class _FakeSegment:
        def get_recent_events(self, account_id):
            return segment_events or []
        def get_account_traits(self, account_id):
            return {}

    detector._bq = _FakeBQ()
    detector._segment = _FakeSegment()
    return detector


def signal_names(signals: list[Signal]) -> list[str]:
    return [s.signal for s in signals]


def get_signal(signals: list[Signal], name: str) -> Signal | None:
    return next((s for s in signals if s.signal == name), None)


# ---------------------------------------------------------------------------
# shipping_volume_decline
# ---------------------------------------------------------------------------

def test_shipping_volume_decline_critical():
    row = {"signal_name": "shipping_volume_decline", "metric_current": 5_000.0, "metric_previous": 10_000.0}
    signals = make_detector([row]).detect("acct_001")
    s = get_signal(signals, "shipping_volume_decline")
    assert s is not None
    assert s.urgency_tier == "critical"
    assert s.human_escalation is True
    assert s.recommended_action == "escalate_to_csm"
    assert s.trigger_mode == "one_time"


def test_shipping_volume_decline_active_risk():
    row = {"signal_name": "shipping_volume_decline", "metric_current": 7_500.0, "metric_previous": 10_000.0}
    signals = make_detector([row]).detect("acct_002")
    s = get_signal(signals, "shipping_volume_decline")
    assert s is not None
    assert s.urgency_tier == "active_risk"
    assert s.human_escalation is False
    assert s.recommended_action == "enroll_hubspot_sequence"
    assert s.sequence == "churn-intervention-volume"


def test_shipping_volume_decline_early_warning():
    # 15% decline — between 10% and 20%
    row = {"signal_name": "shipping_volume_decline", "metric_current": 8_500.0, "metric_previous": 10_000.0}
    signals = make_detector([row]).detect("acct_003")
    s = get_signal(signals, "shipping_volume_decline")
    assert s is not None
    assert s.urgency_tier == "early_warning"


def test_shipping_volume_no_signal_when_below_threshold():
    # Only 5% decline — does not meet the 20% trigger threshold
    row = {"signal_name": "shipping_volume_decline", "metric_current": 9_600.0, "metric_previous": 10_000.0}
    signals = make_detector([row]).detect("acct_004")
    assert "shipping_volume_decline" not in signal_names(signals)


# ---------------------------------------------------------------------------
# revenue_decline
# ---------------------------------------------------------------------------

def test_revenue_decline_active_risk():
    # 25% decline
    row = {"signal_name": "revenue_decline", "metric_current": 75_000.0, "metric_previous": 100_000.0}
    signals = make_detector([row]).detect("acct_010")
    s = get_signal(signals, "revenue_decline")
    assert s is not None
    assert s.urgency_tier == "active_risk"
    assert s.sequence == "churn-intervention-revenue"


def test_revenue_decline_no_signal_when_above_threshold():
    # Only 10% decline — does not meet the 15% trigger threshold
    row = {"signal_name": "revenue_decline", "metric_current": 91_000.0, "metric_previous": 100_000.0}
    signals = make_detector([row]).detect("acct_011")
    assert "revenue_decline" not in signal_names(signals)


def test_revenue_decline_critical_escalates():
    # 40% decline
    row = {"signal_name": "revenue_decline", "metric_current": 60_000.0, "metric_previous": 100_000.0}
    signals = make_detector([row]).detect("acct_012")
    s = get_signal(signals, "revenue_decline")
    assert s.urgency_tier == "critical"
    assert s.human_escalation is True


# ---------------------------------------------------------------------------
# cancel_link_clicked  (real-time Segment signal)
# ---------------------------------------------------------------------------

def test_cancel_link_clicked_produces_critical_signal():
    events = [{"event": "cancel_subscription_clicked", "user_id": "u1", "ts": "2026-06-04T10:00:00Z"}]
    signals = make_detector(segment_events=events).detect("acct_020")
    s = get_signal(signals, "cancel_link_clicked")
    assert s is not None
    assert s.urgency_tier == "critical"
    assert s.human_escalation is True
    assert s.recommended_action == "escalate_to_csm"
    assert s.trigger_mode == "one_time"
    assert s.sequence == "cancel-intent-intervention"


def test_cancel_link_clicked_absent_produces_no_signal():
    signals = make_detector(segment_events=[]).detect("acct_021")
    assert "cancel_link_clicked" not in signal_names(signals)


# ---------------------------------------------------------------------------
# no_label_printed_7_days
# ---------------------------------------------------------------------------

def test_no_label_printed_7_days_fires_at_threshold():
    row = {"signal_name": "no_label_printed_7_days", "days_inactive": 9, "last_used": "2026-05-26"}
    signals = make_detector([row]).detect("acct_030")
    s = get_signal(signals, "no_label_printed_7_days")
    assert s is not None
    assert s.urgency_tier == "early_warning"
    assert s.human_escalation is False
    assert s.sequence == "re-engagement-label"
    assert s.days_inactive == 9


def test_no_label_printed_does_not_fire_below_threshold():
    row = {"signal_name": "no_label_printed_7_days", "days_inactive": 4, "last_used": "2026-06-01"}
    signals = make_detector([row]).detect("acct_031")
    assert "no_label_printed_7_days" not in signal_names(signals)


# ---------------------------------------------------------------------------
# zero_automation_rules — onboarding and regression modes
# ---------------------------------------------------------------------------

def test_zero_automation_rules_onboarding_sequence():
    row = {"signal_name": "zero_automation_rules", "trigger_mode": "onboarding",
           "metric_current": 0.0, "days_inactive": None}
    signals = make_detector([row]).detect("acct_040")
    s = get_signal(signals, "zero_automation_rules")
    assert s is not None
    assert s.trigger_mode == "onboarding"
    assert s.sequence == "automation-education-new"
    assert s.human_escalation is False


def test_zero_automation_rules_regression_sequence():
    row = {"signal_name": "zero_automation_rules", "trigger_mode": "regression",
           "metric_current": 0.0, "metric_previous": 3.0, "days_inactive": 45}
    signals = make_detector([row]).detect("acct_041")
    s = get_signal(signals, "zero_automation_rules")
    assert s is not None
    assert s.trigger_mode == "regression"
    assert s.sequence == "automation-reengagement"


def test_zero_automation_rules_invalid_trigger_mode_skipped():
    row = {"signal_name": "zero_automation_rules", "trigger_mode": None}
    signals = make_detector([row]).detect("acct_042")
    assert "zero_automation_rules" not in signal_names(signals)


# ---------------------------------------------------------------------------
# rate_shopper_not_adopted
# ---------------------------------------------------------------------------

def test_rate_shopper_onboarding_sequence():
    row = {"signal_name": "rate_shopper_not_adopted", "trigger_mode": "onboarding",
           "days_inactive": None, "last_used": None}
    signals = make_detector([row]).detect("acct_050")
    s = get_signal(signals, "rate_shopper_not_adopted")
    assert s.trigger_mode == "onboarding"
    assert s.sequence == "rate-shopper-education-new"


def test_rate_shopper_regression_sequence():
    row = {"signal_name": "rate_shopper_not_adopted", "trigger_mode": "regression",
           "days_inactive": 35, "last_used": "2026-04-30"}
    signals = make_detector([row]).detect("acct_051")
    s = get_signal(signals, "rate_shopper_not_adopted")
    assert s.trigger_mode == "regression"
    assert s.sequence == "rate-shopper-reengagement"
    assert s.days_inactive == 35


# ---------------------------------------------------------------------------
# no_walleted_carriers
# ---------------------------------------------------------------------------

def test_no_walleted_carriers_onboarding_sequence():
    row = {"signal_name": "no_walleted_carriers", "trigger_mode": "onboarding",
           "metric_current": 0.0, "days_inactive": None}
    signals = make_detector([row]).detect("acct_060")
    s = get_signal(signals, "no_walleted_carriers")
    assert s.trigger_mode == "onboarding"
    assert s.sequence == "walleted-carrier-setup-new"


def test_no_walleted_carriers_regression_sequence():
    row = {"signal_name": "no_walleted_carriers", "trigger_mode": "regression",
           "metric_current": 0.0, "metric_previous": 2.0, "days_inactive": 32}
    signals = make_detector([row]).detect("acct_061")
    s = get_signal(signals, "no_walleted_carriers")
    assert s.trigger_mode == "regression"
    assert s.sequence == "walleted-carrier-reengagement"


# ---------------------------------------------------------------------------
# Ordering and multi-signal
# ---------------------------------------------------------------------------

def test_signals_sorted_critical_first():
    rows = [
        {"signal_name": "shipping_volume_decline", "metric_current": 5_000.0, "metric_previous": 10_000.0},  # critical
        {"signal_name": "zero_automation_rules", "trigger_mode": "onboarding"},  # early_warning
    ]
    signals = make_detector(rows).detect("acct_070")
    assert signals[0].urgency_tier == "critical"
    assert signals[-1].urgency_tier == "early_warning"


def test_cancel_click_and_batch_signal_both_present():
    rows = [{"signal_name": "shipping_volume_decline", "metric_current": 5_000.0, "metric_previous": 10_000.0}]
    events = [{"event": "cancel_subscription_clicked", "user_id": "u1", "ts": "2026-06-04T10:00:00Z"}]
    signals = make_detector(rows, segment_events=events).detect("acct_071")
    names = signal_names(signals)
    assert "cancel_link_clicked" in names
    assert "shipping_volume_decline" in names
    # Both are critical — ordering within same tier is not guaranteed
    assert all(s.urgency_tier == "critical" for s in signals if s.signal in names)


def test_unknown_signal_name_in_batch_row_is_ignored():
    rows = [{"signal_name": "unknown_future_signal", "metric_current": 1.0}]
    signals = make_detector(rows).detect("acct_080")
    assert signals == []
