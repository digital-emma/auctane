"""
TranscriptIngester: classifies, parses, and routes CSM meeting transcripts.

Input files are named generically (e.g. optimization_call_2026-06-01.txt,
automation_call_2026-06-01.txt) — signal type is never inferred from the
filename. Every transcript goes through a Claude API classification step
before heuristic extraction.

Processing pipeline per transcript:
  1. Parse raw dict into a TranscriptRecord
  2. Classify via Claude API → signal_type, urgency_tier, outcome, confidence
  3. Route by confidence:
       high | medium  → heuristic extraction → data/transcripts/processed/
       low            → data/transcripts/needs_review/  (needs human tagging)
       parse/API fail → data/transcripts/rejected/

Output filenames: [signal_type]_[outcome]_[original_stem].json
Every output JSON includes a classification_confidence field.

Falls back to keyword-based stub classification when ANTHROPIC_API_KEY is
not set, so the pipeline runs end-to-end in development without credentials.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Load .env from project root if present — lets ANTHROPIC_API_KEY persist
# across sessions without needing python-dotenv as a dependency.
_ENV_FILE = Path(__file__).parent.parent / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _, _val = _line.partition("=")
            os.environ.setdefault(_key.strip(), _val.strip())

_DATA_DIR        = Path(__file__).parent.parent / "data" / "transcripts"
PROCESSED_DIR    = _DATA_DIR / "processed"
NEEDS_REVIEW_DIR = _DATA_DIR / "needs_review"
REJECTED_DIR     = _DATA_DIR / "rejected"

VALID_SIGNAL_TYPES = {
    "shipping_volume_decline", "revenue_decline", "cancel_link_clicked",
    "no_label_printed_7_days", "zero_automation_rules",
    "rate_shopper_not_adopted", "no_walleted_carriers", "general_optimization",
}
VALID_URGENCY_TIERS = {"early_warning", "active_risk", "critical"}
VALID_OUTCOMES = {
    "retained_account", "booked_optimization_call", "feature_adopted",
    "no_commitment", "churned", "unknown",
}
VALID_CONFIDENCE = {"high", "medium", "low"}

CLASSIFICATION_PROMPT = """
You are analyzing a customer success call transcript.
Read the transcript and identify:

1. signal_type — what customer problem prompted this call?
   Choose the closest match from:
   - shipping_volume_decline
   - revenue_decline
   - cancel_link_clicked
   - no_label_printed_7_days
   - zero_automation_rules
   - rate_shopper_not_adopted
   - no_walleted_carriers
   - general_optimization (if none of the above clearly apply)

2. urgency_tier — how serious was the situation?
   - early_warning
   - active_risk
   - critical

3. outcome — what happened at the end of the call?
   - retained_account
   - booked_optimization_call
   - feature_adopted
   - no_commitment
   - churned
   - unknown

4. confidence — how confident are you in this classification?
   - high (clear evidence in transcript)
   - medium (inferred from context)
   - low (insufficient information)

Respond in JSON only. No preamble.

Transcript:
{transcript_text}
"""


@dataclass
class TranscriptRecord:
    account_id: str
    meeting_date: str       # ISO 8601
    participants: list[str]
    outcome: str
    raw_text: str
    source: str = "manual"  # "gong" | "zoom" | "manual"
    metadata: dict = field(default_factory=dict)


@dataclass
class ClassificationResult:
    signal_type: str
    urgency_tier: str
    outcome: str
    confidence: str         # "high" | "medium" | "low"


@dataclass
class BatchSummary:
    processed: int = 0
    needs_review: int = 0
    rejected: int = 0
    signal_type_counts: dict = field(default_factory=lambda: defaultdict(int))

    def print(self) -> None:
        print("Batch complete:")
        print(f"- Processed: {self.processed} transcripts")
        print(f"- Needs review: {self.needs_review} transcripts")
        print(f"- Rejected: {self.rejected} transcripts")
        print(f"- Signal type breakdown: {dict(self.signal_type_counts)}")


class TranscriptIngester:
    def __init__(self):
        for directory in (PROCESSED_DIR, NEEDS_REVIEW_DIR, REJECTED_DIR):
            directory.mkdir(parents=True, exist_ok=True)

    # --- public API ---

    def ingest(self, raw: dict) -> TranscriptRecord:
        """Parse a raw transcript dict into a normalized TranscriptRecord.

        Does not classify — call ingest_batch() for the full classification
        and routing pipeline.
        """
        return TranscriptRecord(
            account_id=raw.get("account_id", "unknown"),
            meeting_date=raw.get("date", datetime.utcnow().isoformat()),
            participants=raw.get("participants", []),
            outcome=raw.get("outcome", "unknown"),
            raw_text=raw.get("transcript", ""),
            source=raw.get("source", "manual"),
            metadata=raw.get("metadata", {}),
        )

    def ingest_batch(self, records: list[dict]) -> BatchSummary:
        """Classify and route a batch of raw transcript dicts.

        Each dict must have at minimum:
          transcript  — raw transcript text
          filename    — original source filename (used for output naming)

        Optional fields: account_id, date, participants, source, metadata.

        Returns and prints a BatchSummary.
        """
        from learning_engine.heuristic_extractor import HeuristicExtractor
        extractor = HeuristicExtractor()
        summary = BatchSummary()

        for raw in records:
            source_filename = raw.get("filename", "transcript.txt")

            try:
                record = self.ingest(raw)
            except Exception as exc:
                self._write_rejected(source_filename, raw, reason=str(exc))
                summary.rejected += 1
                continue

            try:
                classification = self._classify(record.raw_text)
            except Exception as exc:
                self._write_rejected(
                    source_filename, raw,
                    reason=f"classification_failed: {exc}",
                )
                summary.rejected += 1
                continue

            output = {
                "source_file": source_filename,
                "account_id": record.account_id,
                "meeting_date": record.meeting_date,
                "participants": record.participants,
                "raw_text": record.raw_text,
                "source": record.source,
                "signal_type": classification.signal_type,
                "urgency_tier": classification.urgency_tier,
                "outcome": classification.outcome,
                "classification_confidence": classification.confidence,
                "heuristics": [],
            }

            out_stem = _output_filename(
                classification.signal_type, classification.outcome, source_filename
            )

            if classification.confidence == "low":
                (NEEDS_REVIEW_DIR / out_stem).write_text(json.dumps(output, indent=2))
                summary.needs_review += 1
            else:
                heuristic_report = extractor.extract([record])
                output["heuristics"] = heuristic_report.flagged_patterns
                (PROCESSED_DIR / out_stem).write_text(json.dumps(output, indent=2))
                summary.processed += 1

            summary.signal_type_counts[classification.signal_type] += 1

        summary.print()
        return summary

    # --- classification ---

    def _classify(self, transcript_text: str) -> ClassificationResult:
        """Classify transcript via Claude API, falling back to keyword stub if key absent."""
        if os.environ.get("ANTHROPIC_API_KEY"):
            return self._classify_with_api(transcript_text)
        return self._stub_classify(transcript_text)

    def _classify_with_api(self, transcript_text: str) -> ClassificationResult:
        import anthropic
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=256,
            messages=[{
                "role": "user",
                "content": CLASSIFICATION_PROMPT.format(transcript_text=transcript_text),
            }],
        )
        try:
            raw = response.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```", 2)[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw.strip())
        except (json.JSONDecodeError, IndexError) as exc:
            raise ValueError(f"API returned unparseable classification: {exc}") from exc
        return _parse_classification(data)

    def _stub_classify(self, text: str) -> ClassificationResult:
        """Keyword-based stub used when ANTHROPIC_API_KEY is not set."""
        lower = text.lower()
        if "cancel" in lower or "leaving" in lower or "discontinue" in lower:
            signal_type = "cancel_link_clicked"
        elif ("volume" in lower or "shipment" in lower) and any(
            w in lower for w in ("declin", "down", "fewer", "drop")
        ):
            signal_type = "shipping_volume_decline"
        elif "revenue" in lower and any(w in lower for w in ("declin", "down", "drop")):
            signal_type = "revenue_decline"
        elif "rate shop" in lower or "rate comparison" in lower:
            signal_type = "rate_shopper_not_adopted"
        elif "walleted carrier" in lower or "carrier connection" in lower:
            signal_type = "no_walleted_carriers"
        elif "automation" in lower or "automation rule" in lower:
            signal_type = "zero_automation_rules"
        elif "label" in lower and any(w in lower for w in ("print", "not ship", "no ship")):
            signal_type = "no_label_printed_7_days"
        else:
            signal_type = "general_optimization"

        return ClassificationResult(
            signal_type=signal_type,
            urgency_tier="early_warning",
            outcome="unknown",
            confidence="medium",
        )

    # --- output helpers ---

    def _write_rejected(self, source_filename: str, raw: dict, reason: str) -> None:
        stem = Path(source_filename).stem
        out_path = REJECTED_DIR / f"{stem}.json"
        out_path.write_text(json.dumps({
            "source_file": source_filename,
            "rejection_reason": reason,
            "raw_preview": str(raw)[:500],
        }, indent=2))


# --- module-level helpers ---

def _output_filename(signal_type: str, outcome: str, source_filename: str) -> str:
    stem = Path(source_filename).stem
    return f"{signal_type}_{outcome}_{stem}.json"


def _parse_classification(data: dict) -> ClassificationResult:
    """Validate and normalise raw API response into a ClassificationResult.

    Any unrecognised value is replaced with a safe default rather than raising,
    so a partial or slightly malformed API response doesn't drop the transcript.
    """
    signal_type  = data.get("signal_type",  "general_optimization")
    urgency_tier = data.get("urgency_tier", "early_warning")
    outcome      = data.get("outcome",      "unknown")
    confidence   = data.get("confidence",   "low")

    if signal_type  not in VALID_SIGNAL_TYPES:  signal_type  = "general_optimization"
    if urgency_tier not in VALID_URGENCY_TIERS: urgency_tier = "early_warning"
    if outcome      not in VALID_OUTCOMES:       outcome      = "unknown"
    if confidence   not in VALID_CONFIDENCE:     confidence   = "low"

    return ClassificationResult(
        signal_type=signal_type,
        urgency_tier=urgency_tier,
        outcome=outcome,
        confidence=confidence,
    )
