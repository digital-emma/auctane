"""
BigQueryClient: interface to the Auctane data warehouse.

Provides two categories of queries:
  1. csm_signals summary table — pre-computed signal rows written by the nightly
     batch job. SignalDetector reads exclusively from this table; all threshold
     logic and metric aggregation lives in the batch SQL, not in Python.
  2. Raw analytical queries — cohort benchmarks, event history, ad-hoc SQL.

Nightly batch job SQL pattern (example for shipping_volume_decline):
  INSERT INTO csm_analytics.csm_signals
  SELECT
    account_id,
    'shipping_volume_decline'           AS signal_name,
    SUM(CASE WHEN ship_date >= DATE_SUB(CURRENT_DATE, INTERVAL 365 DAY)
             THEN shipment_count END)   AS metric_current,   -- T12M
    SUM(CASE WHEN ship_date BETWEEN DATE_SUB(CURRENT_DATE, INTERVAL 730 DAY)
                              AND DATE_SUB(CURRENT_DATE, INTERVAL 365 DAY)
             THEN shipment_count END)   AS metric_previous,  -- P12M
    MAX(ship_date)                      AS last_used,
    NULL                                AS days_inactive,
    NULL                                AS trigger_mode,
    CURRENT_DATE                        AS batch_date
  FROM shipping_facts
  GROUP BY account_id
  HAVING metric_current < metric_previous * 0.80;

All methods return mock data. Replace with google-cloud-bigquery once credentials
are configured:
  GOOGLE_APPLICATION_CREDENTIALS — path to service account JSON
  BIGQUERY_PROJECT_ID            — GCP project ID
  BIGQUERY_DATASET               — dataset name (e.g. "csm_analytics")
"""

from __future__ import annotations

import json
import os

_HEURISTICS_FIXTURE = os.path.join(os.path.dirname(__file__), "..", "data", "fixtures", "heuristics_mock.json")


class BigQueryClient:
    def get_signal_summary(self, account_id: str) -> list[dict]:
        """Read pre-computed signal rows from the csm_signals nightly batch table.

        Returns a list of row dicts. Each row has:
          signal_name     — matches a key in SignalDetector._BATCH_PARSERS
          metric_current  — T12M value (volume, revenue, rule count, etc.)
          metric_previous — P12M value for comparison signals; None for others
          last_used       — ISO date of last relevant activity, or None
          days_inactive   — days since last relevant activity, or None
          trigger_mode    — "onboarding" | "regression" | None (adoption signals only)
          batch_date      — date this row was written by the batch job
        """
        return [
            {
                "signal_name": "shipping_volume_decline",
                "metric_current": 8_200.0,    # T12M shipments
                "metric_previous": 10_500.0,  # P12M shipments (~22% decline → active_risk)
                "last_used": "2026-05-28",
                "days_inactive": None,
                "trigger_mode": None,
                "batch_date": "2026-06-04",
            },
            {
                "signal_name": "zero_automation_rules",
                "metric_current": 0.0,
                "metric_previous": 3.0,
                "last_used": "2026-04-10",
                "days_inactive": 55,
                "trigger_mode": "regression",  # had rules, now 0 for 55 days
                "batch_date": "2026-06-04",
            },
        ]

    def get_heuristics(self, signal_name: str, limit: int = 2) -> list[dict]:
        """Fetch CSM heuristics for a signal type from the heuristics table.

        Returns up to `limit` heuristic records ordered by recency (fixture order).
        Each record has: signal, urgency_tier, observation, outcome, source.

        Stub: reads from data/fixtures/heuristics_mock.json.
        In production, queries:
          SELECT * FROM csm_analytics.csm_heuristics
          WHERE signal = @signal_name AND outcome = 'positive'
          ORDER BY created_at DESC LIMIT @limit
        """
        with open(_HEURISTICS_FIXTURE) as f:
            data = json.load(f)
        matching = [h for h in data.get("heuristics", []) if h.get("signal") == signal_name]
        return matching[:limit]

    def get_event_history(self, account_id: str, days: int = 90) -> list[dict]:
        """Raw event log for an account over the specified lookback window."""
        return [
            {"event": "login",         "ts": "2026-04-15T09:00:00Z", "user_id": "u123"},
            {"event": "export_report", "ts": "2026-04-22T14:30:00Z", "user_id": "u123"},
            {"event": "login",         "ts": "2026-05-01T08:45:00Z", "user_id": "u123"},
        ]

    def get_cohort_benchmarks(self, lifecycle_stage: str, plan: str) -> dict:
        """Median usage metrics for accounts in the same lifecycle + plan cohort."""
        return {
            "lifecycle_stage": lifecycle_stage,
            "plan": plan,
            "median_logins_30d": 12,
            "median_features_used": 5,
            "median_session_minutes": 9.8,
        }

    def run_query(self, sql: str) -> list[dict]:
        """Escape hatch for ad-hoc queries during development."""
        return [{"stub": True, "query_preview": sql[:120]}]
