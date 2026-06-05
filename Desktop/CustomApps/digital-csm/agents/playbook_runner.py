"""
PlaybookRunner: validates a Signal against its YAML playbook and returns an
outreach recommendation ready for OutreachDispatcher.

Two entry points:

  run_playbook(signal) — AI-powered path. Calls prompt_engine to build a
    personalized outreach decision using PES + Salesforce context. Human
    escalation signals are short-circuited before reaching the prompt engine.

  execute(signal) — structural path used by orchestrator.py. Loads the YAML
    and returns the outreach dict directly from the Signal fields. No AI call.
    Use this when the orchestrator drives OutreachDispatcher directly.

Playbook files live at:  playbooks/<signal_name>.yaml
"""

from __future__ import annotations

import os
import yaml

from agents.signal_detector import Signal, SIGNAL_PLAYBOOK_MAP
from agents import prompt_engine
from integrations.salesforce_client import SalesforceClient
from integrations.pes_client import PESClient

PLAYBOOKS_DIR = os.path.join(os.path.dirname(__file__), "..", "playbooks")


class PlaybookRunner:
    def __init__(self):
        self._salesforce = SalesforceClient()
        self._pes = PESClient()

    def run_playbook(self, signal: Signal) -> dict:
        """AI-powered path: returns a structured JSON decision for a signal.

        Bypasses the prompt engine entirely when human_escalation is True,
        returning a structured escalation payload instead.

        Escalation payload fields:
          action, signal, urgency_tier, account_id, csm_owner,
          escalation_reason, escalate_within_minutes
        """
        if SIGNAL_PLAYBOOK_MAP.get(signal.signal) is None:
            return {"action": "skip", "reason": "no_matching_playbook"}

        account = self._salesforce.get_account(signal.account_id)

        if signal.human_escalation:
            return {
                "action": "escalate_to_csm",
                "signal": signal.signal,
                "urgency_tier": signal.urgency_tier,
                "account_id": signal.account_id,
                "csm_owner": account.get("csm_owner"),
                "escalation_reason": "Signal requires human CSM judgment",
                "escalate_within_minutes": 15 if signal.signal == "cancel_link_clicked" else 60,
            }

        pes_context = self._pes.get_context(signal.account_id)
        return prompt_engine.get_decision(signal, pes_context, account)

    def execute(self, signal: Signal) -> dict:
        """Structural path: load the YAML and return an outreach dict.

        Does not call the AI — returns the signal's pre-computed fields
        enriched with personalization metadata from the playbook YAML.

        Returns one of:
          {"playbook_name": str, "outreach": dict}   — dispatch this
          {"skip_reason": str}                        — no playbook found
        """
        filename = SIGNAL_PLAYBOOK_MAP.get(signal.signal)
        if not filename:
            return {"skip_reason": "no_matching_playbook"}

        playbook = self._load(filename)

        return {
            "playbook_name": playbook["name"],
            "outreach": {
                "signal": signal.signal,
                "account_id": signal.account_id,
                "trigger_mode": signal.trigger_mode,
                "urgency_tier": signal.urgency_tier,
                "sequence": signal.sequence,
                "recommended_action": signal.recommended_action,
                "human_escalation": signal.human_escalation,
                "metric_current": signal.metric_current,
                "metric_previous": signal.metric_previous,
                "days_inactive": signal.days_inactive,
                "personalization": playbook.get("personalization", []),
            },
        }

    def _load(self, filename: str) -> dict:
        path = os.path.join(PLAYBOOKS_DIR, filename)
        with open(path) as f:
            return yaml.safe_load(f)
