"""
SegmentClient: interface to Segment.io for real-time events and trait enrichment.

Fetches recent track events and identify traits for a given account or user.
Used by SignalDetector to surface real-time behavioral signals before
BigQuery aggregates are available.

All methods return mock data. Replace with the Segment Public API or a
Segment Functions webhook handler once credentials are available:
  SEGMENT_WRITE_KEY    — for tracking outbound events
  SEGMENT_ACCESS_TOKEN — for the Segment Public API (trait/event reads)
"""

from __future__ import annotations


class SegmentClient:
    def get_recent_events(self, account_id: str, limit: int = 50) -> list[dict]:
        """Most recent track events associated with any user in the account."""
        return [
            {
                "event": "feature_discovery",
                "user_id": "u123",
                "ts": "2026-06-01T10:00:00Z",
                "properties": {"feature": "advanced_analytics"},
            },
            {
                "event": "page_view",
                "user_id": "u123",
                "ts": "2026-06-02T11:15:00Z",
                "properties": {"page": "/integrations", "time_on_page_s": 94},
            },
        ]

    def get_account_traits(self, account_id: str) -> dict:
        """Current identify traits for the account group."""
        return {
            "account_id": account_id,
            "plan": "growth",
            "mrr": 4_000,
            "nps_score": 8,
            "integrations_enabled": ["shopify", "fedex"],
            "created_at": "2025-09-14T00:00:00Z",
        }

    def track(self, event: str, user_id: str, properties: dict) -> dict:
        """Fire a track event back into Segment (used to log agent actions)."""
        return {"status": "ok", "event": event, "user_id": user_id}

    def identify(self, user_id: str, traits: dict) -> dict:
        """Update identify traits for a user."""
        return {"status": "ok", "user_id": user_id, "traits_written": list(traits.keys())}
