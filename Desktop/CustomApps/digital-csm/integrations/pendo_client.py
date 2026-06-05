"""
PendoClient: interface to Pendo for programmatic in-app guide creation and publishing.

Used to surface targeted in-app messages to merchants based on CSM signals — e.g.,
a Rate Shopper adoption prompt for legacy-plan accounts browsing rates manually, or
an automation rule nudge for accounts with zero rules and high order volume.

All methods return mock data. Replace with Pendo API calls (REST, no official Python SDK)
once credentials are available:
  PENDO_API_KEY       — env var for Pendo integration API key
  PENDO_ACCOUNT_ID    — Pendo subscription account ID

Pendo API base URL: https://app.pendo.io/api/v1
Guide creation endpoint: POST /guide
Guide publish endpoint:   PUT  /guide/{guide_id}
"""

from __future__ import annotations

import uuid


class PendoClient:
    def create_guide(
        self,
        account_id: str,
        guide_content: str,
        trigger_event: str,
    ) -> dict:
        """Create a draft in-app guide targeted to a specific account.

        Args:
            account_id:    ShipStation account ID used to scope the guide audience.
            guide_content: Body copy for the in-app message.
            trigger_event: Pendo event name that surfaces the guide (e.g.
                           'order_processing_page_viewed').

        Returns a dict with guide_id, status, and the submitted fields.
        """
        return {
            "guide_id": f"guide_{uuid.uuid4().hex[:12]}",
            "status": "draft",
            "account_id": account_id,
            "guide_content": guide_content,
            "trigger_event": trigger_event,
        }

    def publish_guide(self, guide_id: str) -> dict:
        """Publish a draft guide so it becomes visible to the targeted account.

        Args:
            guide_id: ID returned by create_guide().

        Returns a dict confirming the guide is live.
        """
        return {
            "guide_id": guide_id,
            "status": "published",
        }
