"""
Orchestrator: entry point for the Digital CSM agent loop.

Coordinates the full signal-to-action pipeline for a given account:
  1. Pulls classified signals from SignalDetector (Segment events + BigQuery triggers)
  2. Selects and executes the matching playbook via PlaybookRunner
  3. Hands approved outreach recommendations to OutreachDispatcher (HubSpot)
  4. Returns a structured run report for CSM review and Learning Engine ingestion

Designed to be called per-account on a schedule or in response to a real-time
Segment event webhook. All decisions are logged in the returned report so CSMs
can audit and override any action before it is sent.
"""

from __future__ import annotations

from agents.signal_detector import Signal, SignalDetector
from agents.playbook_runner import PlaybookRunner
from agents.outreach_dispatcher import OutreachDispatcher


def run(account_id: str) -> dict:
    """Run one full CSM agent cycle for an account.

    Returns a report dict with keys:
      account_id  — the account processed
      signals     — list of detected signals (may be empty)
      actions     — list of outreach actions dispatched
      skipped     — signals that matched no playbook or were suppressed
    """
    signals: list[Signal] = SignalDetector().detect(account_id)

    if not signals:
        return {"account_id": account_id, "signals": [], "actions": [], "skipped": []}

    runner = PlaybookRunner()
    dispatcher = OutreachDispatcher()

    actions = []
    skipped = []

    for signal in signals:
        playbook_result = runner.execute(signal)

        if playbook_result.get("outreach"):
            dispatch_result = dispatcher.dispatch(
                outreach=playbook_result["outreach"],
                signal=signal,
            )
            actions.append({
                "signal": signal.signal,
                "urgency_tier": signal.urgency_tier,
                "playbook": playbook_result.get("playbook_name"),
                "dispatch": dispatch_result,
            })
        else:
            skipped.append({
                "signal": signal.signal,
                "reason": playbook_result.get("skip_reason", "no_matching_playbook"),
            })

    return {
        "account_id": account_id,
        "signals": [s.__dict__ for s in signals],
        "actions": actions,
        "skipped": skipped,
    }
