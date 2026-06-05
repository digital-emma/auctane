"""
PESClient: interface to the Product Enablement Score (PES) data source.

PES context captures which platform features an account has enabled vs. disabled,
and recent product engagement metrics (last shipment date, trailing volumes).
This data drives personalization in prompt_engine.py — outreach always references
the specific features the account has not yet adopted.

Stub: reads from data/fixtures/pes_context_mock.json for all accounts.

NOTE: PES data is currently maintained as a standalone dataset. It will be
migrated to Salesforce (as custom fields) or BigQuery (as a product metrics
table) — update this client once that migration is complete and remove the
fixture dependency.

Credentials needed once the real source is wired:
  If Salesforce: covered by existing SALESFORCE_* env vars
  If BigQuery:   covered by existing GOOGLE_APPLICATION_CREDENTIALS
"""

from __future__ import annotations

import json
import os

_FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "fixtures", "pes_context_mock.json")


class PESClient:
    def get_context(self, account_id: str) -> dict:
        """Return PES feature context for an account.

        Returns a dict with:
          features_enabled   — list of feature keys the account has active
          features_disabled  — list of feature keys available but not enabled
          last_shipment_date — ISO date string or None
          t12m_volume        — total shipments in the trailing 12 months
          p12m_volume        — total shipments in the prior 12 months
        """
        with open(_FIXTURE_PATH) as f:
            data = json.load(f)
        return {**data, "account_id": account_id}
