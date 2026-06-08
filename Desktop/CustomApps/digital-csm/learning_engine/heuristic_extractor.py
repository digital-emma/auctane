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
from pathlib import Path

import yaml

from learning_engine.transcript_ingester import TranscriptRecord

_BP_PATH = Path(__file__).parent / "best_practices.yaml"


def get_recommendations(
    signal_type: str,
    account_context: dict,
    priority: str | None = None,
) -> list[dict]:
    """Return best-practice recommendations for a signal + account context.

    priority controls injection mode:
      "primary"   — recs are main email content; max from cross_signal_injection_rules
      "secondary" — recs are a bonus section; max from cross_signal_injection_rules
      "none"      — returns [] (used for cancel_link_clicked / critical escalation)
      None        — falls back to max_recommendations_per_email from recommendation_logic

    Always leads with BP-001 (Rate Shopper Best Value). Selects additional
    recommendations from conditional_best_practices using account_context signals:
      - has_multiple_stores     → BP-004
      - has_mixed_weight_orders → CBP-003
      - has_po_box_orders       → CBP-001
      - has_high_value_orders   → CBP-002
      - ships_internationally   → CBP-004
    Falls back to signal-type defaults when no context signals are present.
    """
    if priority == "none":
        return []

    with open(_BP_PATH) as f:
        kb = yaml.safe_load(f)

    logic = kb.get("recommendation_logic", {})

    if priority in ("primary", "secondary"):
        cross_rules = kb.get("cross_signal_injection_rules", {})
        max_recs = cross_rules.get(priority, {}).get("max_recommendations", 3)
    else:
        max_recs = logic.get("max_recommendations_per_email", 3)

    all_bps: dict[str, dict] = {}
    for bp in kb.get("core_best_practices", []):
        all_bps[bp["id"]] = bp
    for bp in kb.get("conditional_best_practices", []):
        all_bps[bp["id"]] = bp

    # BP-001 is always first
    recommendations = [_format_recommendation(all_bps["BP-001"])]

    # Collect candidate IDs from signal-type defaults and account-context signals
    candidate_ids: list[str] = []

    signal_key = f"include_if_{signal_type}"
    for id_ in logic.get(signal_key, []):
        if id_ != "BP-001" and id_ not in candidate_ids:
            candidate_ids.append(id_)

    context_gates = [
        ("has_multiple_stores",     "include_if_multi_store"),
        ("has_mixed_weight_orders", "include_if_mixed_weight"),
        ("has_po_box_orders",       "include_if_has_po_box_orders"),
        ("has_high_value_orders",   "include_if_high_value_orders"),
        ("ships_internationally",   "include_if_international"),
    ]
    for ctx_key, logic_key in context_gates:
        if account_context.get(ctx_key):
            for id_ in logic.get(logic_key, []):
                if id_ != "BP-001" and id_ not in candidate_ids:
                    candidate_ids.append(id_)

    for id_ in candidate_ids:
        if len(recommendations) >= max_recs:
            break
        bp = all_bps.get(id_)
        if bp:
            recommendations.append(_format_recommendation(bp))

    return recommendations


def get_injection_rules(priority: str) -> dict:
    """Return the cross_signal_injection_rules block for a given priority.

    Returns dict with keys: section_header, max_recommendations, footer (optional).
    Returns {} if priority not found (e.g. priority="none").
    """
    with open(_BP_PATH) as f:
        kb = yaml.safe_load(f)
    return kb.get("cross_signal_injection_rules", {}).get(priority, {})


def _format_recommendation(bp: dict) -> dict:
    """Extract prompt-injection fields from a best practice entry."""
    return {
        "id":             bp.get("id"),
        "name":           bp.get("name"),
        "rule_condition": bp.get("rule_condition") or bp.get("rule_condition_1"),
        "rule_action":    bp.get("rule_action"),
        "why_it_matters": bp.get("why_it_matters", "").strip(),
        "deep_link":      bp.get("deep_link"),
    }


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
