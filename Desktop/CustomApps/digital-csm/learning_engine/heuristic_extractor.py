"""
HeuristicExtractor: derives playbook-improvement signals from ingested transcripts.

Analyzes TranscriptRecords across a batch of CSM meetings to surface patterns:
  - Which signal types preceded churn (for scoring calibration)
  - Which outreach sequences correlated with positive outcomes
  - Common objections or blockers mentioned by at-risk accounts
  - Expansion conversations that converted vs. stalled

Outputs a HeuristicReport that can be reviewed by CSMs and eventually used to
adjust playbook scoring thresholds, sequence selection, and personalization fields.

Phase 1 implementation: keyword + outcome correlation (no LLM dependency).
Phase 2: replace with an LLM call over the transcript corpus.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from learning_engine.transcript_ingester import TranscriptRecord


@dataclass
class HeuristicReport:
    total_transcripts: int
    outcome_distribution: dict[str, int]      # {"positive": N, "at_risk": N, ...}
    churn_precursors: list[str]               # signals/topics that preceded churn
    expansion_precursors: list[str]           # signals/topics that preceded expansion
    flagged_patterns: list[dict]              # anomalies or high-signal observations
    raw_notes: list[str] = field(default_factory=list)


# Stub keyword lists — replace with LLM extraction or a trained classifier
CHURN_KEYWORDS    = ["cancel", "leaving", "competitor", "too expensive", "not using", "switching"]
EXPANSION_KEYWORDS = ["grow", "more seats", "new team", "additional", "upgrade", "scale"]


class HeuristicExtractor:
    def extract(self, transcripts: list[TranscriptRecord]) -> HeuristicReport:
        """Analyze a batch of transcripts and return a HeuristicReport.

        Stub: runs simple keyword matching over raw_text.
        """
        outcome_dist: dict[str, int] = defaultdict(int)
        churn_hits: list[str] = []
        expansion_hits: list[str] = []
        flagged: list[dict] = []

        for t in transcripts:
            outcome_dist[t.outcome] += 1
            text_lower = t.raw_text.lower()

            matched_churn = [kw for kw in CHURN_KEYWORDS if kw in text_lower]
            if matched_churn and t.outcome in ("at_risk", "churned"):
                churn_hits.extend(matched_churn)
                flagged.append({
                    "account_id": t.account_id,
                    "date": t.meeting_date,
                    "pattern": "churn_language_confirmed",
                    "keywords": matched_churn,
                })

            matched_expansion = [kw for kw in EXPANSION_KEYWORDS if kw in text_lower]
            if matched_expansion and t.outcome == "positive":
                expansion_hits.extend(matched_expansion)

        return HeuristicReport(
            total_transcripts=len(transcripts),
            outcome_distribution=dict(outcome_dist),
            churn_precursors=list(set(churn_hits)),
            expansion_precursors=list(set(expansion_hits)),
            flagged_patterns=flagged,
        )
