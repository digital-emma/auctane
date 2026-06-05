"""
SignalDetector: reads pre-computed signals from the nightly batch summary table
and enriches with real-time Segment events for immediate triggers.

Data flow:
  BigQuery csm_signals table (nightly batch) →  batch signals
  Segment event stream (real-time)           →  immediate signals (cancel_link_clicked)

The batch job runs nightly SQL against shipping, revenue, and product-usage tables,
writes one row per account per triggered signal into csm_signals, and includes the
pre-computed urgency tier and metric values. SignalDetector reads that table and
maps rows into Signal objects; all threshold logic lives in the batch job SQL.

Adoption signals carry a trigger_mode ("onboarding" vs "regression") from the batch
row so PlaybookRunner knows which HubSpot sequence to enroll the account in.

Urgency sort order:  critical > active_risk > early_warning
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Optional

from integrations.bigquery_client import BigQueryClient
from integrations.segment_client import SegmentClient

TriggerMode = Literal["onboarding", "regression", "one_time"]
UrgencyTier = Literal["early_warning", "active_risk", "critical"]
ActionType  = Literal["enroll_hubspot_sequence", "escalate_to_csm"]

URGENCY_RANK: dict[str, int] = {"critical": 3, "active_risk": 2, "early_warning": 1}


@dataclass
class Signal:
    signal: str
    account_id: str
    trigger_mode: TriggerMode
    urgency_tier: UrgencyTier
    last_used: str | None
    days_inactive: int | None
    metric_current: float | None
    metric_previous: float | None
    recommended_action: ActionType
    sequence: str
    human_escalation: bool

    def to_dict(self) -> dict:
        return {
            "signal": self.signal,
            "account_id": self.account_id,
            "trigger_mode": self.trigger_mode,
            "urgency_tier": self.urgency_tier,
            "last_used": self.last_used,
            "days_inactive": self.days_inactive,
            "metric_current": self.metric_current,
            "metric_previous": self.metric_previous,
            "recommended_action": self.recommended_action,
            "sequence": self.sequence,
            "human_escalation": self.human_escalation,
        }


# Maps signal names to their playbook YAML filenames.
SIGNAL_PLAYBOOK_MAP: dict[str, str] = {
    "shipping_volume_decline":  "shipping_volume_decline.yaml",
    "revenue_decline":          "revenue_decline.yaml",
    "cancel_link_clicked":      "cancel_link_clicked.yaml",
    "no_label_printed_7_days":  "no_label_printed_7_days.yaml",
    "zero_automation_rules":    "zero_automation_rules.yaml",
    "rate_shopper_not_adopted": "rate_shopper_not_adopted.yaml",
    "no_walleted_carriers":     "no_walleted_carriers.yaml",
}


class SignalDetector:
    def __init__(self):
        self._bq = BigQueryClient()
        self._segment = SegmentClient()

    def detect(self, account_id: str) -> list[Signal]:
        """Return all active signals for an account, sorted critical-first.

        Combines pre-computed batch signals from BigQuery with real-time
        Segment event checks. Returns an empty list if no signals are active.
        """
        batch = self._read_batch_signals(account_id)
        realtime = self._read_realtime_signals(account_id)
        return sorted(batch + realtime, key=lambda s: URGENCY_RANK.get(s.urgency_tier, 0), reverse=True)

    # --- batch signals (nightly BQ summary table) ---

    def _read_batch_signals(self, account_id: str) -> list[Signal]:
        rows = self._bq.get_signal_summary(account_id)
        signals: list[Signal] = []
        for row in rows:
            parser = _BATCH_PARSERS.get(row.get("signal_name", ""))
            if parser:
                signal = parser(account_id, row)
                if signal:
                    signals.append(signal)
        return signals

    # --- real-time signals (Segment event stream) ---

    def _read_realtime_signals(self, account_id: str) -> list[Signal]:
        events = self._segment.get_recent_events(account_id)
        if any(e.get("event") == "cancel_subscription_clicked" for e in events):
            return [Signal(
                signal="cancel_link_clicked",
                account_id=account_id,
                trigger_mode="one_time",
                urgency_tier="critical",
                last_used=None,
                days_inactive=None,
                metric_current=None,
                metric_previous=None,
                recommended_action="escalate_to_csm",
                sequence="cancel-intent-intervention",
                human_escalation=True,
            )]
        return []


# ---------------------------------------------------------------------------
# Per-signal batch parsers — one function per signal name.
# Each reads from a csm_signals row and returns a Signal or None (not triggered).
# ---------------------------------------------------------------------------

_BatchParser = Callable[[str, dict], Optional[Signal]]


def _parse_shipping_volume_decline(account_id: str, row: dict) -> Signal | None:
    t12m = row.get("metric_current")
    p12m = row.get("metric_previous")
    if not t12m or not p12m or p12m == 0 or t12m >= p12m * 0.90:
        return None
    pct_decline = (p12m - t12m) / p12m
    if pct_decline >= 0.35:
        tier: UrgencyTier = "critical"
    elif pct_decline >= 0.20:
        tier = "active_risk"
    else:
        tier = "early_warning"
    return Signal(
        signal="shipping_volume_decline",
        account_id=account_id,
        trigger_mode="one_time",
        urgency_tier=tier,
        last_used=row.get("last_used"),
        days_inactive=row.get("days_inactive"),
        metric_current=t12m,
        metric_previous=p12m,
        recommended_action="escalate_to_csm" if tier == "critical" else "enroll_hubspot_sequence",
        sequence="churn-intervention-volume",
        human_escalation=tier == "critical",
    )


def _parse_revenue_decline(account_id: str, row: dict) -> Signal | None:
    t12m = row.get("metric_current")
    p12m = row.get("metric_previous")
    if not t12m or not p12m or p12m == 0 or t12m >= p12m * 0.90:
        return None
    pct_decline = (p12m - t12m) / p12m
    if pct_decline >= 0.35:
        tier: UrgencyTier = "critical"
    elif pct_decline >= 0.20:
        tier = "active_risk"
    else:
        tier = "early_warning"
    return Signal(
        signal="revenue_decline",
        account_id=account_id,
        trigger_mode="one_time",
        urgency_tier=tier,
        last_used=row.get("last_used"),
        days_inactive=row.get("days_inactive"),
        metric_current=t12m,
        metric_previous=p12m,
        recommended_action="escalate_to_csm" if tier == "critical" else "enroll_hubspot_sequence",
        sequence="churn-intervention-revenue",
        human_escalation=tier == "critical",
    )


def _parse_no_label_printed_7_days(account_id: str, row: dict) -> Signal | None:
    days_inactive = row.get("days_inactive", 0)
    if days_inactive < 7:
        return None
    return Signal(
        signal="no_label_printed_7_days",
        account_id=account_id,
        trigger_mode="one_time",
        urgency_tier="early_warning",
        last_used=row.get("last_used"),
        days_inactive=days_inactive,
        metric_current=None,
        metric_previous=None,
        recommended_action="enroll_hubspot_sequence",
        sequence="re-engagement-label",
        human_escalation=False,
    )


def _make_adoption_parser(
    signal_name: str,
    onboarding_sequence: str,
    regression_sequence: str,
) -> _BatchParser:
    """Factory that returns a parser for a two-mode adoption signal."""
    def _parse(account_id: str, row: dict) -> Signal | None:
        trigger_mode = row.get("trigger_mode")
        if trigger_mode not in ("onboarding", "regression"):
            return None
        sequence = onboarding_sequence if trigger_mode == "onboarding" else regression_sequence
        return Signal(
            signal=signal_name,
            account_id=account_id,
            trigger_mode=trigger_mode,
            urgency_tier="early_warning",
            last_used=row.get("last_used"),
            days_inactive=row.get("days_inactive"),
            metric_current=row.get("metric_current"),
            metric_previous=row.get("metric_previous"),
            recommended_action="enroll_hubspot_sequence",
            sequence=sequence,
            human_escalation=False,
        )
    return _parse


_BATCH_PARSERS: dict[str, _BatchParser] = {
    "shipping_volume_decline":  _parse_shipping_volume_decline,
    "revenue_decline":          _parse_revenue_decline,
    "no_label_printed_7_days":  _parse_no_label_printed_7_days,
    "zero_automation_rules":    _make_adoption_parser(
        "zero_automation_rules",
        onboarding_sequence="automation-education-new",
        regression_sequence="automation-reengagement",
    ),
    "rate_shopper_not_adopted": _make_adoption_parser(
        "rate_shopper_not_adopted",
        onboarding_sequence="rate-shopper-education-new",
        regression_sequence="rate-shopper-reengagement",
    ),
    "no_walleted_carriers":     _make_adoption_parser(
        "no_walleted_carriers",
        onboarding_sequence="walleted-carrier-setup-new",
        regression_sequence="walleted-carrier-reengagement",
    ),
}
