"""
ReviewQueue: human-in-the-loop checkpoint between prompt_engine and OutreachDispatcher.

Sits between prompt_engine.get_decision() and OutreachDispatcher.dispatch(). Instead
of firing outreach immediately, the agent writes its output to data/review_queue/pending/
as a JSON file for CSM review. A human approves or rejects each item before anything
is sent.

Workflow:
  1. ReviewQueue.submit(output, signal) — agent writes decision to pending/
  2. Human reviews pending/ files in their tooling
  3. ReviewQueue.approve(output_id)    — moves to approved/, fires OutreachDispatcher
  4. ReviewQueue.reject(output_id, reason) — moves to rejected/, logs reason

File naming: {signal_type}_{account_id}_{output_id}.json
Every file includes status, submitted_at, and the full prompt_engine output so
reviewers have complete context without opening another system.

Directories created on first use:
  data/review_queue/pending/
  data/review_queue/approved/
  data/review_queue/rejected/
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agents.signal_detector import Signal

_QUEUE_DIR    = Path(__file__).parent.parent / "data" / "review_queue"
PENDING_DIR   = _QUEUE_DIR / "pending"
APPROVED_DIR  = _QUEUE_DIR / "approved"
REJECTED_DIR  = _QUEUE_DIR / "rejected"


class ReviewQueue:
    def __init__(self):
        for directory in (PENDING_DIR, APPROVED_DIR, REJECTED_DIR):
            directory.mkdir(parents=True, exist_ok=True)

    def submit(self, output: dict, signal: Signal) -> str:
        """Write a prompt_engine decision to pending/ for human review.

        Args:
            output: The full dict returned by prompt_engine.get_decision().
            signal: The Signal that triggered this decision — stored for context
                    and passed through to OutreachDispatcher on approval.

        Returns:
            output_id — the unique ID for this pending item (use with approve/reject).
        """
        output_id = uuid.uuid4().hex[:12]
        filename = f"{signal.signal}_{signal.account_id}_{output_id}.json"

        payload = {
            "output_id": output_id,
            "status": "pending_review",
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "signal": {
                "signal": signal.signal,
                "account_id": signal.account_id,
                "urgency_tier": signal.urgency_tier,
                "trigger_mode": signal.trigger_mode,
                "human_escalation": signal.human_escalation,
                "metric_current": signal.metric_current,
                "metric_previous": signal.metric_previous,
                "days_inactive": signal.days_inactive,
                "sequence": signal.sequence,
                "recommended_action": signal.recommended_action,
            },
            "agent_output": output,
        }

        (PENDING_DIR / filename).write_text(json.dumps(payload, indent=2))
        return output_id

    def approve(self, output_id: str) -> dict:
        """Approve a pending item — moves it to approved/ and fires OutreachDispatcher.

        Args:
            output_id: The ID returned by submit().

        Returns:
            The OutreachDispatcher dispatch result, plus the queue file path.

        Raises:
            FileNotFoundError: if no pending file matches output_id.
        """
        from agents.outreach_dispatcher import OutreachDispatcher

        pending_file = self._find_pending(output_id)
        payload = json.loads(pending_file.read_text())

        signal = _signal_from_dict(payload["signal"])
        outreach = payload["agent_output"]

        dispatch_result = OutreachDispatcher().dispatch(outreach, signal)

        payload["status"] = "approved"
        payload["approved_at"] = datetime.now(timezone.utc).isoformat()
        payload["dispatch_result"] = dispatch_result

        approved_path = APPROVED_DIR / pending_file.name
        approved_path.write_text(json.dumps(payload, indent=2))
        pending_file.unlink()

        return dispatch_result

    def reject(self, output_id: str, reason: str) -> dict:
        """Reject a pending item — moves it to rejected/ and records the reason.

        Args:
            output_id: The ID returned by submit().
            reason:    Human-readable explanation (stored in the file and printed).

        Returns:
            A summary dict with output_id, status, and reason.

        Raises:
            FileNotFoundError: if no pending file matches output_id.
        """
        pending_file = self._find_pending(output_id)
        payload = json.loads(pending_file.read_text())

        payload["status"] = "rejected"
        payload["rejected_at"] = datetime.now(timezone.utc).isoformat()
        payload["rejection_reason"] = reason

        rejected_path = REJECTED_DIR / pending_file.name
        rejected_path.write_text(json.dumps(payload, indent=2))
        pending_file.unlink()

        print(f"[REVIEW_QUEUE] Rejected {output_id}: {reason}")

        return {
            "output_id": output_id,
            "status": "rejected",
            "reason": reason,
        }

    def list_pending(self) -> list[dict]:
        """Return a summary list of all items currently awaiting review."""
        items = []
        for f in sorted(PENDING_DIR.glob("*.json")):
            payload = json.loads(f.read_text())
            sig = payload.get("signal", {})
            agent_out = payload.get("agent_output", {})
            items.append({
                "output_id": payload["output_id"],
                "submitted_at": payload["submitted_at"],
                "signal": sig.get("signal"),
                "account_id": sig.get("account_id"),
                "urgency_tier": sig.get("urgency_tier"),
                "action": agent_out.get("action"),
                "outreach_subject": agent_out.get("outreach_subject"),
            })
        return items

    # --- internal ---

    def _find_pending(self, output_id: str) -> Path:
        matches = list(PENDING_DIR.glob(f"*_{output_id}.json"))
        if not matches:
            raise FileNotFoundError(
                f"No pending item found with output_id={output_id!r}. "
                "It may have already been approved, rejected, or the ID is wrong."
            )
        return matches[0]


def _signal_from_dict(d: dict) -> Signal:
    """Reconstruct a Signal dataclass from the dict stored in the queue file."""
    from agents.signal_detector import Signal
    return Signal(
        signal=d["signal"],
        account_id=d["account_id"],
        urgency_tier=d["urgency_tier"],
        trigger_mode=d["trigger_mode"],
        human_escalation=d["human_escalation"],
        metric_current=d.get("metric_current"),
        metric_previous=d.get("metric_previous"),
        days_inactive=d.get("days_inactive"),
        last_used=d.get("last_used"),
        sequence=d["sequence"],
        recommended_action=d["recommended_action"],
    )
