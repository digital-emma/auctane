"""
OutreachDispatcher: translates playbook outreach dicts into HubSpot and Salesforce operations.

Handles two recommended_action types:
  enroll_hubspot_sequence — enrolls the account champion in the named HubSpot sequence
                            and logs activity to Salesforce
  escalate_to_csm         — creates an urgent Salesforce task, notifies the CSM owner,
                            and never sends automated outreach (human-only path)

cancel_link_clicked is always escalate_to_csm with a 15-minute SLA expectation.
Critical churn signals follow the same path.

Every dispatch result is returned in full so the orchestrator run report gives
CSMs a complete audit trail before any action is confirmed as sent.
"""

from __future__ import annotations

from integrations.hubspot_client import HubSpotClient
from integrations.salesforce_client import SalesforceClient
from agents.signal_detector import Signal


class OutreachDispatcher:
    def __init__(self):
        self._hubspot = HubSpotClient()
        self._salesforce = SalesforceClient()

    def dispatch(self, outreach: dict, signal: Signal) -> dict:
        """Execute the outreach recommendation and return a dispatch log."""
        account = self._salesforce.get_account(outreach["account_id"])
        contacts = self._salesforce.get_contacts(outreach["account_id"])
        champion = next(
            (c for c in contacts if c.get("role") == "Champion"),
            contacts[0] if contacts else None,
        )

        action = outreach["recommended_action"]

        if action == "enroll_hubspot_sequence":
            return self._enroll_sequence(outreach, account, champion)
        if action == "escalate_to_csm":
            return self._escalate(outreach, account)

        return {"status": "skipped", "reason": f"unknown_recommended_action:{action}"}

    # --- action handlers ---

    def _enroll_sequence(self, outreach: dict, account: dict, champion: dict | None) -> dict:
        if not champion:
            return {
                "account_id": account["id"],
                "status": "skipped",
                "reason": "no_champion_contact",
            }

        enroll_result = self._hubspot.enroll_in_sequence(
            contact_email=champion["email"],
            sequence_id=outreach["sequence"],
        )
        self._salesforce.update_health_score(
            account_id=account["id"],
            score=max(0, account.get("health_score", 100) - 5),
        )

        return {
            "account_id": account["id"],
            "account_name": account.get("name"),
            "action": "enrolled_hubspot_sequence",
            "sequence": outreach["sequence"],
            "trigger_mode": outreach.get("trigger_mode"),
            "contact_email": champion["email"],
            "hubspot_result": enroll_result,
        }

    def _escalate(self, outreach: dict, account: dict) -> dict:
        urgency_tier = outreach.get("urgency_tier", "critical").upper()
        signal_name = outreach.get("signal", "unknown")

        task = self._salesforce.create_task(
            account_id=account["id"],
            subject=f"[{urgency_tier}] {signal_name} — CSM intervention required",
            notify=["csm_owner"],
        )

        # Stub: production would post to Slack #csm-alerts or send a push notification
        print(
            f"[ESCALATION] {account.get('name')} | signal={signal_name} "
            f"tier={urgency_tier} | assigned to {account.get('csm_owner')}"
        )

        return {
            "account_id": account["id"],
            "account_name": account.get("name"),
            "action": "escalated_to_csm",
            "signal": signal_name,
            "urgency_tier": outreach.get("urgency_tier"),
            "csm_owner": account.get("csm_owner"),
            "salesforce_task": task,
        }
