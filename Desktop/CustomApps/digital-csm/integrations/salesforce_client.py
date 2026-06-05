"""
SalesforceClient: interface to Salesforce CRM data.

Provides account health scores, contact lists, opportunity management, and
CSM task creation. Used by OutreachDispatcher (actions) and SignalDetector
(account context enrichment).

All methods return mock data. Replace with simple-salesforce or the Salesforce
REST API once OAuth credentials are available via environment variables:
  SALESFORCE_USERNAME, SALESFORCE_PASSWORD, SALESFORCE_SECURITY_TOKEN
"""

from __future__ import annotations


class SalesforceClient:
    def get_account(self, account_id: str) -> dict:
        return {
            "id": account_id,
            "name": "Tackle Industries",
            "health_score": 72,
            "arr": 48_000,
            "csm_owner": "Jessica Lane",
            "lifecycle_stage": "growth",
            "contract_renewal_date": "2026-11-01",
            "plan_type": "Silver",
            "current_plan_cost": "74.99",
            "standard_plan_cost": "75.00",
            "monthly_order_volume": 280,
            "manual_rate_decisions_weekly": 65,
        }

    def get_contacts(self, account_id: str) -> list[dict]:
        return [
            {"id": "c001", "name": "Alice Nguyen", "email": "alice@acmeshipping.com", "role": "Champion"},
            {"id": "c002", "name": "Bob Patel",   "email": "bob@acmeshipping.com",   "role": "Economic Buyer"},
        ]

    def update_health_score(self, account_id: str, score: int) -> dict:
        return {"status": "ok", "account_id": account_id, "health_score": score}

    def create_task(self, account_id: str, subject: str, notify: list[str]) -> dict:
        return {
            "status": "created",
            "account_id": account_id,
            "subject": subject,
            "notified": notify,
        }

    def upsert_opportunity(self, account_id: str, stage: str, owner: str) -> dict:
        return {
            "status": "upserted",
            "account_id": account_id,
            "stage": stage,
            "owner": owner,
        }
