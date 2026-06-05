# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`digital-csm` is an agentic AI-powered Digital Customer Success Manager (CSM) built at Auctane. It learns from human CSM optimization meetings and customer interaction data, then triggers personalized outreach at scale to drive adoption, retention, and churn intervention.

**Current phase:** Early ideation and architecture — prioritize system design and data flow over implementation.

## Tech Stack

| Layer | Tool | Role |
|---|---|---|
| CRM | Salesforce | Accounts, contacts, opportunities, health scores |
| Outreach | HubSpot | Email sequences, workflows, enrollment triggers |
| Data Warehouse | BigQuery | Behavioral data, product usage, event history |
| CDP | Segment.io | Real-time event streaming, trait enrichment, audiences |

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run all tests
pytest

# Run a single test file
pytest tests/test_signals.py

# Run a single test by name
pytest tests/test_signals.py::test_critical_churn_on_zero_logins

# Run the agent loop for one account (once a CLI entrypoint exists)
python -m agents.orchestrator
```

## Architecture

The pipeline flows: **SignalDetector → PlaybookRunner → OutreachDispatcher**, coordinated by the Orchestrator.

### agents/
- `orchestrator.py` — entry point; runs one full CSM cycle per account. Returns a structured run report (signals, actions, skipped) for CSM audit.
- `signal_detector.py` — fuses Segment real-time events + BigQuery historical usage into typed `Signal` objects with severity (`early_warning | active_risk | critical`) and a 0–1 confidence score.
- `playbook_runner.py` — loads the matching YAML playbook from `playbooks/`, resolves the severity tier, and returns an outreach recommendation or skip reason. Critical-tier accounts always return `pause_automation` to force human handoff.
- `outreach_dispatcher.py` — translates playbook action lists into HubSpot enrollments, CSM tasks, and Salesforce opportunity updates.

### integrations/
All four clients (`salesforce_client.py`, `hubspot_client.py`, `bigquery_client.py`, `segment_client.py`) are stubbed to return mock data. Each file's docstring specifies the exact env vars needed to wire up the real API.

### playbooks/
YAML decision trees keyed by `signal_type`. Each playbook defines `tiers:` (severity blocks) with `actions:` lists. `PlaybookRunner` loads these at runtime — adding a new playbook requires no code changes, only a new YAML file and an entry in `SIGNAL_TO_PLAYBOOK` in `playbook_runner.py`.

### learning_engine/
- `transcript_ingester.py` — normalizes CSM meeting transcripts (Gong, Zoom, manual) into `TranscriptRecord` objects.
- `heuristic_extractor.py` — keyword + outcome correlation over transcript batches, producing a `HeuristicReport`. Phase 2 will replace keyword matching with an LLM call.

### tests/
Tests inject fixture data by subclassing `SignalDetector` with fake Segment/BQ clients — no actual API calls, no monkeypatching frameworks needed.

## Integration Notes

`integrations/pes_client.py` is stubbed and reads from `data/fixtures/pes_context_mock.json`. PES data will migrate to either Salesforce custom fields or a BigQuery product metrics table — update `pes_client.py` to point at the real source when that migration is complete.

All other integration clients (`salesforce_client.py`, `hubspot_client.py`, `bigquery_client.py`, `segment_client.py`) follow the same stub pattern: mock data returned by default, with the required env vars and replacement approach documented in each file's docstring.

## CTA Model

Primary CTA: Always a direct product deep link driving immediate in-product action. Never a meeting booking or Calendly link.

Secondary CTA: Reply invitation on all emails — agent continues the conversation if the customer responds. HubSpot sequences must be configured to route replies back to the agent inbox, not a human CSM inbox.

Deep links by signal (defined in `PRODUCT_DEEP_LINKS` in `agents/prompt_engine.py`):
- `rate_shopper_not_adopted`: `/settings/rateShopper`
- `zero_automation_rules`: `/automations`
- `no_walleted_carriers`: `/settings/carriers`
- `no_label_printed_7_days`: `/orders/awaiting-shipment`
- `shipping_volume_decline`: `/dashboard/operations`
- `revenue_decline`: `/dashboard/operations` + `/pricing/` if on legacy plan
- `cancel_link_clicked`: escalate to human, no CTA

Future state: inbound reply routing via HubSpot webhook → agent conversation continuation. Flag for eng team — HubSpot sequences must allow reply routing to agent inbox.

## Core Design Principles

- Augment human CSMs; never replace relationship judgment on strategic accounts
- All outreach must be personalized and contextual — no batch-and-blast
- Churn intervention is tiered: early warning → active risk → critical
- Every agent action must be explainable to CSMs
- Signal quality over signal volume
- Critical-tier accounts always trigger human escalation — `pause_automation` halts all automated sequences
