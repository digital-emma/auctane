"""
PromptEngine: builds the AI prompt and returns a structured outreach decision.

Takes a Signal + PES context + Salesforce account context as input. Formats
the USER_PROMPT_TEMPLATE with all personalization data — including the top 2
CSM heuristics for the signal type fetched from BigQuery — and calls the AI
to produce a structured JSON decision (outreach subject/body, HubSpot sequence,
Salesforce action).

The prompt engine is never called for human_escalation signals — PlaybookRunner
short-circuits those before reaching here. If somehow called with a critical or
human_escalation signal, the engine respects the rule in SYSTEM_PROMPT and
returns an escalation notice rather than drafting outreach.

Stub: get_decision() returns a mock response. Replace the _stub_decision() call
with a Claude API call once ANTHROPIC_API_KEY is available in the environment.
"""

from __future__ import annotations

from agents.signal_detector import Signal
from integrations.bigquery_client import BigQueryClient
from learning_engine.heuristic_extractor import get_recommendations

_bq = BigQueryClient()

PRODUCT_DEEP_LINKS = {
    "rate_shopper":    "https://ship14.shipstation.com/settings/rateShopper",
    "automation_rules": "https://ship14.shipstation.com/automations",
    "inventory":       "https://ship14.shipstation.com/settings/inventorysettings",
    "carriers":        "https://ship14.shipstation.com/settings/carriers",
    "analytics":       "https://ship14.shipstation.com/dashboard/operations",
    "orders":          "https://ship14.shipstation.com/orders/awaiting-shipment",
    "plans":           "https://www.shipstation.com/pricing/",
}

SYSTEM_PROMPT = """
You are a Digital Customer Success Manager for a shipping and logistics platform.
Your job is to review customer account signals and craft personalized, contextual outreach
that helps customers get more value from the platform.

You never send generic messages. Every outreach must reference:
- The specific signal that fired (volume decline, feature non-adoption, etc.)
- The features the customer currently has enabled vs. not enabled (from PES data)
- The customer's recent activity (last shipment date, total volume)

You follow these rules without exception:
- If urgency_tier is critical or human_escalation is True, do NOT draft outreach — return an escalation notice for the CSM instead
- If the customer has a relevant feature disabled, reference that specific feature in your message
- If the customer has no shipments in 7+ days, acknowledge the gap directly but not accusatorially
- Churn outreach tone scales with urgency: early_warning = helpful and consultative, active_risk = direct and value-focused, critical = escalate to human immediately
- Never mention competitors, pricing, or cancellation in outreach copy

CTA RULES BY SIGNAL TYPE:

zero_automation_rules →
  https://ship14.shipstation.com/automations
  Frame: "You can create your first rule in under 5 minutes here: [link]"

no_walleted_carriers →
  https://ship14.shipstation.com/settings/carriers
  Frame: "You can connect your carrier account directly here: [link]"

no_label_printed_7_days →
  https://ship14.shipstation.com/orders/awaiting-shipment
  Frame: "Your orders are ready and waiting here: [link]"

shipping_volume_decline →
  https://ship14.shipstation.com/dashboard/operations
  Frame: "Your full carrier performance breakdown is here: [link]"

revenue_decline →
  https://ship14.shipstation.com/dashboard/operations
  primary link, plus https://www.shipstation.com/pricing/
  if on legacy plan

cancel_link_clicked →
  NO autonomous CTA — escalate to human CSM immediately.
  Do not generate outreach for this signal.

ALL SIGNALS:
- End every email with a reply invitation:
  "Just reply here if you have any questions — I'm here to help."
- Never use Calendly, booking links, or meeting request language
- Never use generic CTAs like "let us know if you need help"
  or "feel free to reach out"
- Always frame the CTA as a direct action the merchant can take
  right now, in under 5 minutes
"""

USER_PROMPT_TEMPLATE = """
Signal fired: {signal_name}
Trigger mode: {trigger_mode}
Urgency tier: {urgency_tier}
Human escalation required: {human_escalation}

Account context from PES:
- Features enabled: {features_enabled}
- Features not enabled: {features_disabled}
- Last shipment date: {last_shipment_date}
- T12M shipment volume: {t12m_volume}
- P12M shipment volume: {p12m_volume}

Account context from Salesforce:
- Account name: {account_name}
- CSM owner: {csm_owner}
- Lifecycle stage: {lifecycle_stage}

How your best CSMs have handled this situation:
{heuristics_section}

Best practice recommendations to include:
{best_practices_section}

Based on the above:
1. Should this be handled by the agent or escalated to the CSM? State your reasoning.
2. If agent-handled: draft a personalized outreach message referencing the specific features
   not enabled that are relevant to this signal. End with the signal-appropriate direct
   product deep link and a reply invitation — never a Calendly or booking link.
3. Which HubSpot sequence should this account be enrolled in?
4. What is the recommended Salesforce action (update health score, create task, etc.)?

Respond in this JSON format:
{{
  "action": "agent_handles" | "escalate_to_csm",
  "escalation_reason": "string or null",
  "outreach_subject": "string or null",
  "outreach_body": "string or null",
  "hubspot_sequence": "string",
  "salesforce_action": "string",
  "features_referenced": ["list of features mentioned in outreach"]
}}
"""

RATE_SHOPPER_SYSTEM_PROMPT = """
You are a Digital Customer Success Manager for ShipStation, a shipping
and logistics platform. You are reaching out to a merchant who is not
using Rate Shopper — a feature that automatically compares carrier rates
and selects the best option on every shipment.

You have reviewed their account before writing this message. You know:
- How many orders per month they process
- Which carriers they currently use
- Whether they are on a legacy plan (Silver/Bronze/Gold) or Standard
- Which features are enabled vs not enabled on their account

Your outreach must follow these rules without exception:

FRAMING: Atlas has been assigned to this account and conducted a
proactive audit before reaching out. Never frame outreach as an alert
or notification. Always frame it as a follow-up from work Atlas already
did on their account. Atlas is an ongoing point of contact, not a
one-time message.

OPENING: Always introduce Atlas by name, state they have been assigned
to support the account, and reference the audit they conducted. Never
open with a feature alert.

STRUCTURE: Every Rate Shopper email must include:
- Personalized insight from the audit (volume, carrier, industry
  comparison, estimated savings %)
- Three numbered recommended steps with deep links:
  Step 1: Enable Rate Shopper → https://ship14.shipstation.com/settings/rateShopper
  Step 2: Connect walleted carriers → https://ship14.shipstation.com/settings/carriers
  Step 3: Set first automation rule → https://ship14.shipstation.com/automations
- Video walkthrough reference: {video_link}
- Reply invitation as secondary CTA

TONE: Proactive advisor who did real work. Warm but professional. Never
robotic, never alert-style, never generic. Reads like a thoughtful
human CSM who reviewed the account before writing.

CORE MECHANIC — THE PRICE REVEAL: If the merchant is on a legacy plan
(Silver/Bronze/Gold), always include the plan comparison with both
numbers stated side by side. Example: "Your current plan is $74.99/mo.
Standard is $75.00/mo and includes Rate Shopper, Analytics, and 10
users — features that were $149/mo add-ons on your current plan."
The number must appear next to their current number. "There is a new
plan" without the numbers does not activate. The numbers do.

OBJECTION HANDLING: If their account shows walleted/negotiated carriers,
proactively address the likely objection: "The preference setting lets
you still prioritize your negotiated UPS rates even when ShipStation
finds a cheaper option — it adds your rates to the comparison, it does
not override them."

WHAT NOT TO SAY: Never mention competitors. Never mention cancellation.
Never say "I wanted to reach out" or "just checking in." Never show
features they have no current problem with.

CTA RULES — FOLLOW EXACTLY:

Primary CTA: Always drive the customer to take action directly
in the product. Use this exact link for Rate Shopper:
https://ship14.shipstation.com/settings/rateShopper
Frame it as a direct 2-minute action, not a meeting request.
Good example: "You can turn this on in under 2 minutes here:
https://ship14.shipstation.com/settings/rateShopper"
Bad example: "Book a call to learn more" — never use this.

Secondary CTA: End every email with a reply invitation.
Good example: "If you have questions about setting your carrier
preference rules, just reply here — I can walk you through it."

If the merchant is on a legacy plan, also include the plan
comparison link: https://www.shipstation.com/pricing/
Frame it as: "You can see the full plan comparison here:
[link] — the difference in price is usually under $1."

NEVER use: Calendly links, booking language, "schedule a call",
"20-minute setup", or any meeting request framing.

SUBJECT LINE: Must reference something account-specific. Never use
generic subject lines like "Optimize your shipping" or "Quick question."
Good examples:
- "The UPS vs USPS decision you're making manually {X} times a week"
- "Rate Shopper is already on your account — here's what you're missing"
- "Your {carrier} selection on {X} orders/month — there's a faster way"
"""

RATE_SHOPPER_USER_PROMPT = """
Trigger mode: {trigger_mode}
(onboarding = never used Rate Shopper / regression = used it and stopped)

Account data:
- Account name: {account_name}
- Monthly order volume: {monthly_order_volume}
- Current plan: {current_plan}
- Current monthly cost: ${current_plan_cost}
- Standard plan cost: ${standard_plan_cost}
- Primary carriers in use: {carriers_in_use}
- Has negotiated/walleted carriers: {has_walleted_carriers}
- Estimated manual rate decisions per week: {manual_rate_decisions_weekly}

PES feature status:
- Rate Shopper enabled: {rate_shopper_enabled}
- Rate Shopper type: {rate_shopper_type} (basic/customizable/none)
- Automation rules count: {automation_rules_count}
- Analytics enabled: {analytics_enabled}

Few-shot examples from your best CSMs handling this exact situation:
{heuristic_examples}

Best practice recommendations to include:
{best_practices_section}

Using the account data above and the CSM examples as your guide:

1. Write a personalized outreach email subject line that references
   something specific from this account
2. Write the email body — open with the specific manual behavior you
   found, include the price reveal if on legacy plan, handle the
   negotiated carrier objection if walleted_carriers is true.
   The email must end with:
   (a) Direct link to https://ship14.shipstation.com/settings/rateShopper
       framed as a 2-minute direct action
   (b) If legacy plan: secondary link to https://www.shipstation.com/pricing/
       with the "under $1 difference" framing
   (c) Reply invitation: "Just reply here if you have questions —
       I can walk you through the setup."
3. Write a shorter in-app Pendo message (2-3 sentences max) for the
   same account — this appears on their order processing page.
   The Pendo message must end with the direct Rate Shopper link only —
   no reply invitation in Pendo, no plan link.
4. Which HubSpot sequence should this enroll in:
   rate-shopper-education-new (trigger_mode: onboarding) or
   rate-shopper-reengagement (trigger_mode: regression)
5. Recommended Salesforce action

Respond in this exact JSON format:
{{
  "action": "agent_handles",
  "email_subject": "string",
  "email_body": "string",
  "pendo_message": "string",
  "hubspot_sequence": "string",
  "salesforce_action": "string",
  "features_referenced": ["array of features mentioned"],
  "price_reveal_included": true or false,
  "objection_handled": true or false
}}
"""


def build_rate_shopper_prompt(
    signal_payload: dict,
    pes_context: dict,
    salesforce_context: dict,
    heuristics: list[dict],
) -> tuple[str, str]:
    """Build the Rate Shopper system + user prompt from signal and account context.

    Pulls qualifying language and mechanics from the 94-call CSM analysis.
    Produces both an email and a Pendo in-app message in one API call.

    Returns:
        (system_prompt, user_prompt) — pass both to the Claude API call.
    """
    heuristic_text = _format_heuristics(heuristics, "rate_shopper_not_adopted")

    account_context = {
        "has_multiple_stores":     pes_context.get("store_count", 1) > 1,
        "has_mixed_weight_orders": pes_context.get("has_mixed_weight_orders", False),
        "has_po_box_orders":       pes_context.get("has_po_box_orders", False),
        "has_high_value_orders":   pes_context.get("has_high_value_orders", False),
        "ships_internationally":   pes_context.get("ships_internationally", False),
    }
    recs = get_recommendations("rate_shopper_not_adopted", account_context)
    best_practices_section = _format_best_practices(recs)

    user_prompt = RATE_SHOPPER_USER_PROMPT.format(
        trigger_mode=signal_payload.get("trigger_mode"),
        account_name=salesforce_context.get("account_name") or salesforce_context.get("name", "unknown"),
        monthly_order_volume=salesforce_context.get("monthly_order_volume", "unknown"),
        current_plan=salesforce_context.get("plan_type", "unknown"),
        current_plan_cost=salesforce_context.get("current_plan_cost", "unknown"),
        standard_plan_cost=salesforce_context.get("standard_plan_cost", "75.00"),
        carriers_in_use=", ".join(pes_context.get("carriers_in_use", [])) or "unknown",
        has_walleted_carriers=pes_context.get("has_walleted_carriers", False),
        manual_rate_decisions_weekly=salesforce_context.get("manual_rate_decisions_weekly", "unknown"),
        rate_shopper_enabled=pes_context.get("rate_shopper_enabled", False),
        rate_shopper_type=pes_context.get("rate_shopper_type", "none"),
        automation_rules_count=pes_context.get("automation_rules_count", 0),
        analytics_enabled=pes_context.get("analytics_enabled", False),
        heuristic_examples=heuristic_text,
        best_practices_section=best_practices_section,
    )
    return RATE_SHOPPER_SYSTEM_PROMPT, user_prompt


# Maps each signal to the PES feature keys most relevant to reference in outreach.
# Features are only mentioned if they appear in the account's features_disabled list.
_SIGNAL_FEATURE_RELEVANCE: dict[str, list[str]] = {
    "shipping_volume_decline":  ["automation_rules", "rate_shopper", "walleted_carriers"],
    "revenue_decline":          ["automation_rules", "rate_shopper", "walleted_carriers"],
    "no_label_printed_7_days":  ["automation_rules"],
    "zero_automation_rules":    ["automation_rules"],
    "rate_shopper_not_adopted": ["rate_shopper", "walleted_carriers", "automation_rules", "analytics"],
    "no_walleted_carriers":     ["walleted_carriers"],
    "cancel_link_clicked":      [],  # never reaches prompt engine
}

_SALESFORCE_ACTIONS: dict[str, str] = {
    "shipping_volume_decline":  "update_health_score_flag_for_csm_review",
    "revenue_decline":          "create_csm_task_update_opportunity_stage",
    "no_label_printed_7_days":  "log_activity_update_health_score",
    "zero_automation_rules":    "log_activity",
    "rate_shopper_not_adopted": "log_activity",
    "no_walleted_carriers":     "log_activity",
}

_ADOPTION_SIGNALS = {
    "zero_automation_rules",
    "rate_shopper_not_adopted",
    "no_walleted_carriers",
    "no_label_printed_7_days",
}

_FEATURE_DISPLAY_NAMES: dict[str, str] = {
    "automation_rules":        "Automation Rules",
    "rate_shopper":            "Rate Shopper",
    "walleted_carriers":       "Walleted Carrier connections",
    "returns_portal":          "Returns Portal",
    "basic_labels":            "Basic Labels",
    "address_validation":      "Address Validation",
    "tracking_notifications":  "Tracking Notifications",
}


def _format_best_practices(recommendations: list[dict]) -> str:
    """Format get_recommendations() output into numbered prompt text."""
    lines = []
    for i, rec in enumerate(recommendations, 1):
        lines.append(f"{i}. [{rec['id']}] {rec['name']}")
        if rec.get("rule_condition"):
            lines.append(f"   Rule: {rec['rule_condition']}" +
                         (f" → {rec['rule_action']}" if rec.get("rule_action") else ""))
        if rec.get("why_it_matters"):
            lines.append(f"   Why: {rec['why_it_matters']}")
        if rec.get("deep_link"):
            lines.append(f"   Link: {rec['deep_link']}")
    return "\n".join(lines)


def build_prompt(signal: Signal, pes_context: dict, salesforce_context: dict) -> str:
    """Format USER_PROMPT_TEMPLATE with signal + PES + Salesforce + heuristics context.

    Fetches the top 2 CSM heuristics for the signal type from BigQuery and injects
    them under 'How your best CSMs have handled this situation:'. Falls back
    gracefully if no heuristics exist for the signal type yet.

    All personalization comes from the input dicts — no hardcoded account data.
    """
    features_enabled  = ", ".join(pes_context.get("features_enabled", [])) or "none"
    features_disabled = ", ".join(pes_context.get("features_disabled", [])) or "none"

    heuristics = _bq.get_heuristics(signal.signal, limit=2)
    heuristics_section = _format_heuristics_section(heuristics)

    account_context = {
        "has_multiple_stores":     pes_context.get("store_count", 1) > 1,
        "has_mixed_weight_orders": pes_context.get("has_mixed_weight_orders", False),
        "has_po_box_orders":       pes_context.get("has_po_box_orders", False),
        "has_high_value_orders":   pes_context.get("has_high_value_orders", False),
        "ships_internationally":   pes_context.get("ships_internationally", False),
    }
    recs = get_recommendations(signal.signal, account_context)
    best_practices_section = _format_best_practices(recs)

    return USER_PROMPT_TEMPLATE.format(
        signal_name=signal.signal,
        trigger_mode=signal.trigger_mode,
        urgency_tier=signal.urgency_tier,
        human_escalation=signal.human_escalation,
        features_enabled=features_enabled,
        features_disabled=features_disabled,
        last_shipment_date=pes_context.get("last_shipment_date") or "unknown",
        t12m_volume=pes_context.get("t12m_volume") or "unknown",
        p12m_volume=pes_context.get("p12m_volume") or "unknown",
        account_name=salesforce_context.get("name", "unknown"),
        csm_owner=salesforce_context.get("csm_owner", "unknown"),
        lifecycle_stage=salesforce_context.get("lifecycle_stage", "unknown"),
        heuristics_section=heuristics_section,
        best_practices_section=best_practices_section,
    )


def _format_heuristics_section(heuristics: list[dict]) -> str:
    """Format heuristic records into numbered prompt text, or a fallback note."""
    if not heuristics:
        return "No heuristics recorded for this signal type yet."
    return "\n".join(f"{i}. {h['observation']}" for i, h in enumerate(heuristics, 1))


def _format_heuristics(heuristics: list[dict], signal_name: str) -> str:
    """Format heuristics for signal-specific prompt builders.

    Filters to the given signal, then formats as numbered examples.
    Falls back gracefully if no matching heuristics are found.
    """
    matching = [h for h in heuristics if h.get("signal") == signal_name]
    if not matching:
        return "No CSM examples recorded for this signal type yet."
    return "\n\n".join(
        f"Example {i}:\n{h['observation']}"
        for i, h in enumerate(matching, 1)
    )


def get_decision(signal: Signal, pes_context: dict, salesforce_context: dict) -> dict:
    """Build the prompt and return a structured outreach decision.

    Routes rate_shopper_not_adopted to its dedicated prompt builder; all other
    signals use the generic build_prompt() path.

    Stub: returns a mock decision. Replace _stub_decision() with a real API call:

      import anthropic, json
      client = anthropic.Anthropic()

      # Generic path:
      response = client.messages.create(
          model="claude-sonnet-4-6",
          max_tokens=1024,
          system=SYSTEM_PROMPT,
          messages=[{"role": "user", "content": build_prompt(signal, pes_context, salesforce_context)}],
      )

      # Rate Shopper dedicated path:
      heuristics = _bq.get_heuristics(signal.signal, limit=3)
      system, user = build_rate_shopper_prompt(
          signal_payload={"trigger_mode": signal.trigger_mode},
          pes_context=pes_context,
          salesforce_context=salesforce_context,
          heuristics=heuristics,
      )
      response = client.messages.create(
          model="claude-sonnet-4-6",
          max_tokens=1024,
          system=system,
          messages=[{"role": "user", "content": user}],
      )

      return json.loads(response.content[0].text)
    """
    if signal.signal == "rate_shopper_not_adopted":
        heuristics = _bq.get_heuristics(signal.signal, limit=3)
        build_rate_shopper_prompt(
            signal_payload={"trigger_mode": signal.trigger_mode},
            pes_context=pes_context,
            salesforce_context=salesforce_context,
            heuristics=heuristics,
        )
    else:
        build_prompt(signal, pes_context, salesforce_context)

    return _stub_decision(signal, pes_context, salesforce_context)


# ---------------------------------------------------------------------------
# Stub decision logic — replace body of get_decision() with real API call
# ---------------------------------------------------------------------------

def _stub_decision(signal: Signal, pes_context: dict, salesforce_context: dict) -> dict:
    """Return a realistic mock decision without calling the AI."""
    if signal.urgency_tier == "critical" or signal.human_escalation:
        return {
            "action": "escalate_to_csm",
            "escalation_reason": f"{signal.signal} at {signal.urgency_tier} urgency requires human judgment",
            "outreach_subject": None,
            "outreach_body": None,
            "hubspot_sequence": signal.sequence,
            "salesforce_action": _SALESFORCE_ACTIONS.get(signal.signal, "log_activity"),
            "features_referenced": [],
        }

    if signal.signal == "rate_shopper_not_adopted":
        return _stub_rate_shopper_decision(signal, pes_context, salesforce_context)

    relevant = _relevant_disabled_features(signal.signal, pes_context.get("features_disabled", []))
    subject, body = _draft_outreach(signal, pes_context, salesforce_context, relevant)

    return {
        "action": "agent_handles",
        "escalation_reason": None,
        "outreach_subject": subject,
        "outreach_body": body,
        "hubspot_sequence": signal.sequence,
        "salesforce_action": _SALESFORCE_ACTIONS.get(signal.signal, "log_activity"),
        "features_referenced": relevant,
    }


def _stub_rate_shopper_decision(
    signal: Signal, pes_context: dict, salesforce_context: dict
) -> dict:
    """Stub response matching the Rate Shopper prompt's JSON schema."""
    account_name   = salesforce_context.get("name", "your account")
    plan_type      = salesforce_context.get("plan_type", "")
    current_cost   = salesforce_context.get("current_plan_cost", "unknown")
    standard_cost  = salesforce_context.get("standard_plan_cost", "75.00")
    monthly_vol    = salesforce_context.get("monthly_order_volume", "unknown")
    weekly_manual  = salesforce_context.get("manual_rate_decisions_weekly", "unknown")
    carriers       = pes_context.get("carriers_in_use", [])
    carrier_str    = " and ".join(carriers) if carriers else "your carriers"
    has_walleted   = pes_context.get("has_walleted_carriers", False)
    is_legacy_plan = plan_type in ("Silver", "Gold", "Bronze")
    is_regression  = signal.trigger_mode == "regression"

    if is_regression:
        subject = f"Rate Shopper is still on your account, {account_name} — worth another look"
        body = (
            f"Hi there,\n\n"
            f"I was reviewing {account_name}'s account and noticed Rate Shopper hasn't been used "
            f"in a while. Carrier rates shift constantly — a comparison that wasn't competitive "
            f"last time you tried may look very different today.\n\n"
        )
    else:
        subject = (
            f"The {carrier_str} decision you're making manually "
            f"{weekly_manual}x a week — {account_name}"
        )
        body = (
            f"Hi there,\n\n"
            f"I pulled up {account_name}'s account and can see you're processing around "
            f"{monthly_vol} orders a month across {carrier_str}. Right now that carrier "
            f"selection is happening manually on every order — Rate Shopper can make that "
            f"automatic and ensure you're always on the best available rate.\n\n"
        )

    if is_legacy_plan:
        body += (
            f"One thing worth knowing: your current {plan_type} plan is ${current_cost}/mo. "
            f"Standard is ${standard_cost}/mo and includes Rate Shopper (customizable), "
            f"Analytics, and 10 users — features that were $149/mo add-ons on your current plan. "
            f"You can see the full plan comparison here: {PRODUCT_DEEP_LINKS['plans']} "
            f"— the difference in price is usually under $1.\n\n"
        )

    if has_walleted:
        body += (
            f"If you're thinking 'I already have negotiated UPS rates' — Rate Shopper "
            f"won't override those. The preference setting lets you prioritize your "
            f"negotiated rates; it just adds them to the comparison so you can see "
            f"where ShipStation rates are cheaper.\n\n"
        )

    body += (
        f"You can turn this on in under 2 minutes here: {PRODUCT_DEEP_LINKS['rate_shopper']}\n\n"
        f"Just reply here if you have questions about setting your carrier preference rules "
        f"— I can walk you through it."
    )

    pendo_message = (
        f"You're selecting carriers manually on ~{weekly_manual} orders a week. "
        f"Rate Shopper is already on your account and can automate this — "
        f"you can turn it on in under 2 minutes: {PRODUCT_DEEP_LINKS['rate_shopper']}"
    )

    features_referenced = ["rate_shopper"]
    if is_legacy_plan:
        features_referenced.append("analytics")
    if has_walleted:
        features_referenced.append("walleted_carriers")

    return {
        "action": "agent_handles",
        "email_subject": subject,
        "email_body": body,
        "pendo_message": pendo_message,
        "hubspot_sequence": signal.sequence,
        "salesforce_action": _SALESFORCE_ACTIONS.get(signal.signal, "log_activity"),
        "features_referenced": features_referenced,
        "price_reveal_included": is_legacy_plan,
        "objection_handled": has_walleted,
    }


def _relevant_disabled_features(signal_name: str, disabled: list[str]) -> list[str]:
    """Return the subset of disabled features relevant to this signal."""
    candidates = _SIGNAL_FEATURE_RELEVANCE.get(signal_name, [])
    return [f for f in candidates if f in disabled]


def _draft_outreach(
    signal: Signal,
    pes_context: dict,
    salesforce_context: dict,
    relevant_features: list[str],
) -> tuple[str, str]:
    """Return a (subject, body) tuple for the mock outreach draft."""
    account_name  = salesforce_context.get("name", "your account")
    last_shipment = pes_context.get("last_shipment_date") or "recently"
    t12m          = pes_context.get("t12m_volume")
    p12m          = pes_context.get("p12m_volume")
    feature_names = [_FEATURE_DISPLAY_NAMES.get(f, f) for f in relevant_features]
    feature_list  = " and ".join(feature_names) if feature_names else "several platform features"
    is_adoption   = signal.signal in _ADOPTION_SIGNALS
    reply_cta     = "\n\nJust reply here if you have any questions — I'm here to help."

    _signal_deep_links = {
        "zero_automation_rules":    PRODUCT_DEEP_LINKS["automation_rules"],
        "no_walleted_carriers":     PRODUCT_DEEP_LINKS["carriers"],
        "no_label_printed_7_days":  PRODUCT_DEEP_LINKS["orders"],
        "shipping_volume_decline":  PRODUCT_DEEP_LINKS["analytics"],
        "revenue_decline":          PRODUCT_DEEP_LINKS["analytics"],
    }

    # --- churn signals ---
    if signal.signal == "shipping_volume_decline":
        pct = round((1 - t12m / p12m) * 100) if t12m and p12m else None
        pct_str = f"{pct}%" if pct else "noticeably"
        link = _signal_deep_links["shipping_volume_decline"]
        if signal.urgency_tier == "early_warning":
            subject = f"Quick check-in on {account_name}'s shipping volume"
            body = (
                f"Hi there,\n\nI noticed {account_name}'s shipping volume over the past 12 months is "
                f"running {pct_str} below the prior year. I wanted to check in — there may be a few "
                f"things we can do to help.\n\n"
                f"One area that often helps accounts like yours recover volume is {feature_list} — "
                f"which {account_name} hasn't enabled yet. Your full carrier performance breakdown "
                f"is here: {link}"
            )
        else:  # active_risk
            subject = f"Your shipping volume at {account_name} — let's dig in"
            body = (
                f"Hi there,\n\nI'm reaching out because {account_name}'s shipping volume is down "
                f"{pct_str} year-over-year, and I want to make sure we're doing everything we can "
                f"to support your business.\n\n"
                f"Accounts in a similar position have seen real results by activating {feature_list}. "
                f"Your carrier performance breakdown is a good place to start: {link}"
            )
        body += reply_cta
        return subject, body

    if signal.signal == "revenue_decline":
        link = _signal_deep_links["revenue_decline"]
        subject = f"Checking in on {account_name} — a few things worth looking at"
        body = (
            f"Hi there,\n\nI've been reviewing {account_name}'s account and there are a few "
            f"platform capabilities — specifically {feature_list} — that aren't currently active "
            f"and could have a meaningful impact on your shipping costs and volume.\n\n"
            f"Your operations dashboard is a good starting point: {link}"
            + reply_cta
        )
        return subject, body

    if signal.signal == "no_label_printed_7_days":
        link = _signal_deep_links["no_label_printed_7_days"]
        subject = f"Everything okay with shipping at {account_name}?"
        body = (
            f"Hi there,\n\nI noticed {account_name} hasn't printed any shipping labels since "
            f"{last_shipment}. If you've hit any friction in your workflow, I'm happy to help "
            f"troubleshoot.\n\n"
            f"If volume is slower than usual, it might also be a good time to look at {feature_list}, "
            f"which can help streamline your process when things pick back up. "
            f"Your orders are ready and waiting here: {link}"
            + reply_cta
        )
        return subject, body

    # --- adoption signals ---
    if signal.signal == "zero_automation_rules":
        link = _signal_deep_links["zero_automation_rules"]
        subject = (
            f"Save time with Automation Rules — {account_name}"
            if signal.trigger_mode == "onboarding"
            else f"Your automation rules at {account_name} — quick check-in"
        )
        if signal.trigger_mode == "onboarding":
            body = (
                f"Hi there,\n\nI noticed {account_name} hasn't set up any Automation Rules yet. "
                f"Automation Rules let you automatically apply carrier selection, packaging, and "
                f"service levels based on your order criteria — saving significant manual effort "
                f"at scale.\n\nAccounts that set up even 2–3 rules typically save 30+ minutes per "
                f"week on order processing. You can create your first rule in under 5 minutes here: "
                f"{link}"
            )
        else:
            body = (
                f"Hi there,\n\nI noticed {account_name}'s Automation Rules have been inactive for "
                f"a while. Was there something about the setup that wasn't working for your workflow? "
                f"We've made some improvements that might address any friction you experienced.\n\n"
                f"You can create your first rule in under 5 minutes here: {link}"
            )
        body += reply_cta
        return subject, body

    if signal.signal == "rate_shopper_not_adopted":
        link = PRODUCT_DEEP_LINKS["rate_shopper"]
        subject = (
            f"Are you getting the best rates, {account_name}?"
            if signal.trigger_mode == "onboarding"
            else f"Rate Shopper is still on your account, {account_name} — worth another look"
        )
        if signal.trigger_mode == "onboarding":
            body = (
                f"Hi there,\n\nWith {t12m or 'your current'} shipments per year, Rate Shopper "
                f"could be finding you meaningfully cheaper options on every label. "
                f"{account_name} hasn't run a rate comparison yet — you can turn it on in under "
                f"2 minutes here: {link}"
            )
        else:
            body = (
                f"Hi there,\n\nCarrier rates shift frequently, and there's a good chance a "
                f"comparison today would surface savings you're currently leaving on the table. "
                f"You can turn Rate Shopper back on in under 2 minutes here: {link}"
            )
        body += reply_cta
        return subject, body

    if signal.signal == "no_walleted_carriers":
        link = _signal_deep_links["no_walleted_carriers"]
        subject = (
            f"Connect your carrier accounts at {account_name}"
            if signal.trigger_mode == "onboarding"
            else f"Your carrier connections at {account_name} — let's reconnect"
        )
        if signal.trigger_mode == "onboarding":
            body = (
                f"Hi there,\n\nConnecting your own carrier accounts (UPS, FedEx, USPS) to "
                f"{account_name} unlocks your negotiated rates directly in the platform — "
                f"no more switching between systems. It takes about 5 minutes to connect "
                f"and immediately consolidates your shipping into one workflow. "
                f"You can connect your carrier account directly here: {link}"
            )
        else:
            body = (
                f"Hi there,\n\nI noticed {account_name}'s carrier accounts were disconnected. "
                f"Without them, you're missing access to your negotiated rates inside the platform. "
                f"Was there a reason for the change? You can reconnect directly here: {link}"
            )
        body += reply_cta
        return subject, body

    # Fallback for any signal not explicitly handled above
    subject = f"A note on your {account_name} account"
    body = (
        f"Hi there,\n\nThere are a few features — specifically {feature_list} — that could "
        f"improve your workflow and aren't currently active on your account."
        + reply_cta
    )
    return subject, body
