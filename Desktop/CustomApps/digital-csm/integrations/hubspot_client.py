"""
HubSpotClient: interface to HubSpot for email sequences and CRM task creation.

Used by OutreachDispatcher to enroll contacts in nurture sequences, set contact
properties, create CSM tasks, and trigger workflow automation.

All methods return mock data. Replace with the HubSpot Python SDK (hubspot-api-client)
once a Private App token is available:
  HUBSPOT_ACCESS_TOKEN — env var expected by the real client
"""

from __future__ import annotations


class HubSpotClient:
    def enroll_in_sequence(self, contact_email: str, sequence_id: str) -> dict:
        return {
            "status": "enrolled",
            "contact_email": contact_email,
            "sequence_id": sequence_id,
        }

    def create_task(self, contact_email: str, subject: str, priority: str = "medium") -> dict:
        return {
            "status": "created",
            "contact_email": contact_email,
            "subject": subject,
            "priority": priority,
        }

    def update_contact_property(self, contact_email: str, properties: dict) -> dict:
        return {
            "status": "ok",
            "contact_email": contact_email,
            "updated_properties": properties,
        }

    def trigger_workflow(self, workflow_id: str, contact_email: str) -> dict:
        return {
            "status": "triggered",
            "workflow_id": workflow_id,
            "contact_email": contact_email,
        }

    def unenroll_from_sequence(self, contact_email: str, sequence_id: str) -> dict:
        return {
            "status": "unenrolled",
            "contact_email": contact_email,
            "sequence_id": sequence_id,
        }
