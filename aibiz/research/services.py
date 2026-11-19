"""Phase 2: 22 automation services, each with the brief's 10 questions, plus a fit score for the
three top niches (cleaning, car detailing, trades). Scores are analyst estimates (1-5, 5 = best).

    python3 aibiz/research/services.py        # writes research/results/services.{json,md}
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "results"

FIELDS = ["problem", "payer", "competitors", "feasibility", "difficulty", "opcost", "maintenance",
          "pricing", "risks", "ai"]
FIELD_NAMES = ["Problem it solves", "Who pays", "Existing products", "Technical feasibility",
               "Implementation difficulty", "Operating cost (estimate)", "Maintenance", "Pricing model",
               "Risks and failure modes", "Is AI needed?"]
WEIGHTS = {"value": 0.35, "feasibility": 0.20, "differentiation": 0.20, "recurring": 0.15, "risk": 0.10}

SERVICES = [
    dict(key="booking", name="Appointment scheduling (real free slots)",
         s=dict(value=4, feasibility=4, differentiation=2, recurring=4, risk=4),
         problem="Customers wait for a call back to get a time; owner juggles a paper or phone calendar",
         payer="Any appointment business", competitors="Fresha, Booksy, Zoyya, Calendly, Google Calendar booking pages",
         feasibility="High with an own calendar; integrating a client's existing platform depends on its API",
         difficulty="Medium (availability rules, no double booking)", opcost="EUR 1-5/client/month hosting",
         maintenance="Low once rules are set", pricing="Monthly subscription",
         risks="Double bookings, wrong hours, owner forgets to block time off", ai="No: rules are more reliable"),
    dict(key="reminders", name="Appointment reminders",
         s=dict(value=4, feasibility=5, differentiation=1, recurring=4, risk=4),
         problem="No-shows and late cancellations", payer="Appointment businesses",
         competitors="Built into every booking platform", feasibility="High",
         difficulty="Low", opcost="Email ~0; SMS ~USD 0.14 each to Croatia (Twilio); WhatsApp template fees per message",
         maintenance="Low", pricing="Included in a bundle", risks="Messaging without consent, wrong time zone, spam complaints",
         ai="No"),
    dict(key="missedcall", name="Missed-call text-back",
         s=dict(value=4, feasibility=3, differentiation=3, recurring=4, risk=3),
         problem="Calls missed while working turn into lost jobs", payer="Trades, detailing, cleaning",
         competitors="US tools (e.g. inside field-service suites); few Croatian offers seen",
         feasibility="Medium: needs call forwarding to a virtual number and an SMS or WhatsApp sender",
         difficulty="Medium", opcost="Virtual number plus about USD 0.14 per SMS (Twilio, Croatia)",
         maintenance="Medium (telephony)", pricing="Monthly", risks="Number porting, carrier rules, cost per SMS",
         ai="No"),
    dict(key="webchat", name="Website support assistant",
         s=dict(value=3, feasibility=4, differentiation=2, recurring=3, risk=3),
         problem="Same questions asked again and again", payer="Businesses with website traffic",
         competitors="Tidio, Intercom, many AI chat widgets", feasibility="High",
         difficulty="Low to medium", opcost="LLM cost under EUR 1/month at small volumes (estimate)",
         maintenance="Keep answers current", pricing="Monthly",
         risks="Wrong answers stated confidently; small sites get little traffic", ai="Optional: retrieval over the FAQ helps with phrasing"),
    dict(key="leadqual", name="Lead capture and qualification",
         s=dict(value=5, feasibility=4, differentiation=4, recurring=4, risk=4),
         problem="Inquiries arrive half-complete; owner spends time asking the same questions",
         payer="Quote-based services, real estate", competitors="Form builders, CRMs",
         feasibility="High", difficulty="Medium", opcost="Low", maintenance="Low",
         pricing="Monthly; optionally per qualified lead",
         risks="Asking too much and losing the lead", ai="Optional: understanding free text; structured forms work without it"),
    dict(key="classify", name="Inquiry classification and routing",
         s=dict(value=3, feasibility=4, differentiation=3, recurring=3, risk=4),
         problem="Mixed inbox: complaints, quotes, spam", payer="Firms with several staff", competitors="Helpdesk tools",
         feasibility="High", difficulty="Low to medium", opcost="Low", maintenance="Low",
         pricing="Part of a bundle", risks="Misrouted urgent messages", ai="Yes for free text, with a human fallback"),
    dict(key="emailreply", name="Automated email replies (drafts for approval)",
         s=dict(value=3, feasibility=4, differentiation=2, recurring=3, risk=3),
         problem="Slow email replies", payer="Office-based businesses", competitors="Gmail/Outlook AI features",
         feasibility="High (drafts only)", difficulty="Low", opcost="Low", maintenance="Low", pricing="Monthly",
         risks="Sending wrong information if fully automatic", ai="Yes, but drafts reviewed by a human"),
    dict(key="faq", name="FAQ assistant",
         s=dict(value=2, feasibility=5, differentiation=1, recurring=2, risk=4),
         problem="Repetitive questions about hours, prices, location", payer="Any small business",
         competitors="Free chat widgets, WhatsApp Business quick replies", feasibility="High", difficulty="Low",
         opcost="Low", maintenance="Low", pricing="Usually bundled",
         risks="Little value on its own", ai="Usually no: quick replies and a good FAQ page suffice"),
    dict(key="reviews", name="Customer review requests",
         s=dict(value=3, feasibility=5, differentiation=2, recurring=4, risk=4),
         problem="Few Google reviews despite happy customers", payer="Local services",
         competitors="Review-management tools", feasibility="High", difficulty="Low", opcost="Low",
         maintenance="Low", pricing="Bundle add-on",
         risks="Review gating and incentives can breach platform rules", ai="No"),
    dict(key="crm", name="CRM updates", s=dict(value=3, feasibility=3, differentiation=2, recurring=4, risk=4),
         problem="Customer details scattered across phone, WhatsApp, notebooks", payer="Growing teams",
         competitors="HubSpot free, Pipedrive", feasibility="Medium (depends on the CRM's API)", difficulty="Medium",
         opcost="Low", maintenance="Medium", pricing="Setup + monthly", risks="Duplicate or wrong records", ai="No"),
    dict(key="invoicerem", name="Invoice and payment reminders",
         s=dict(value=3, feasibility=4, differentiation=2, recurring=4, risk=2),
         problem="Late payments", payer="B2B services, accountants",
         competitors="Invoicing software; e-invoicing services under Fiskalizacija 2.0", feasibility="High",
         difficulty="Low", opcost="Low", maintenance="Low", pricing="Monthly",
         risks="Financial data; reminders to wrong people; collection rules", ai="No"),
    dict(key="onboarding", name="Customer onboarding flows",
         s=dict(value=3, feasibility=4, differentiation=3, recurring=3, risk=4),
         problem="New clients need documents, instructions, forms", payer="Agencies, accountants, gyms",
         competitors="Form and e-signature tools", feasibility="High", difficulty="Low to medium", opcost="Low",
         maintenance="Low", pricing="Setup + monthly", risks="Collecting more data than needed", ai="No"),
    dict(key="quotes", name="Quote generation (instant price range)",
         s=dict(value=5, feasibility=4, differentiation=4, recurring=4, risk=3),
         problem="Every inquiry waits for a manual quote; slow quotes lose jobs", payer="Cleaning, detailing, trades",
         competitors="Field-service suites (Jobber etc., mostly English)", feasibility="High with price rules",
         difficulty="Medium (each business prices differently)", opcost="Low", maintenance="Price updates",
         pricing="Setup + monthly",
         risks="A quoted range the business will not honour; must say 'estimate, confirmed after inspection'",
         ai="No for the price (rules); optional for reading free-text descriptions"),
    dict(key="docs", name="Document processing", s=dict(value=4, feasibility=2, differentiation=2, recurring=4, risk=1),
         problem="Manual data entry from invoices and forms", payer="Accountants, logistics",
         competitors="OCR/IDP vendors, accounting software", feasibility="Medium", difficulty="High (accuracy)",
         opcost="Medium", maintenance="High", pricing="Per document", risks="Errors in financial data; sensitive data",
         ai="Yes (OCR + extraction), with human review"),
    dict(key="inventory", name="Inventory notifications", s=dict(value=2, feasibility=3, differentiation=2, recurring=3, risk=4),
         problem="Running out of stock", payer="Shops, restaurants", competitors="Inventory and POS software",
         feasibility="Depends on POS API", difficulty="Medium", opcost="Low", maintenance="Medium", pricing="Monthly",
         risks="Bad data in, bad alerts out", ai="No"),
    dict(key="reporting", name="Internal reporting", s=dict(value=2, feasibility=4, differentiation=2, recurring=3, risk=4),
         problem="Owner lacks a weekly overview", payer="Multi-staff businesses", competitors="Spreadsheet templates, BI tools",
         feasibility="High", difficulty="Low", opcost="Low", maintenance="Low", pricing="Add-on",
         risks="Nobody reads the report", ai="No"),
    dict(key="followup", name="Quote and sales follow-ups",
         s=dict(value=4, feasibility=5, differentiation=3, recurring=4, risk=4),
         problem="Quotes sent and never chased", payer="Quote-based services", competitors="CRMs, field-service suites",
         feasibility="High", difficulty="Low", opcost="Low", maintenance="Low", pricing="Bundle",
         risks="Too many follow-ups annoy customers; needs consent rules", ai="No"),
    dict(key="feedback", name="Customer feedback collection", s=dict(value=2, feasibility=5, differentiation=2, recurring=3, risk=4),
         problem="No structured feedback", payer="Service businesses", competitors="Survey tools", feasibility="High",
         difficulty="Low", opcost="Low", maintenance="Low", pricing="Bundle", risks="Low response rates", ai="No"),
    dict(key="social", name="Social-media inquiry management (Instagram, WhatsApp, Messenger)",
         s=dict(value=4, feasibility=2, differentiation=3, recurring=4, risk=2),
         problem="Inquiries scattered over DMs, lost in personal inboxes", payer="Instagram-driven local businesses",
         competitors="Meta Business Suite inbox (free), unified-inbox tools",
         feasibility="Medium: official Meta APIs need business verification and app review",
         difficulty="High (platform approval, policy changes)", opcost="WhatsApp template messages are charged per message",
         maintenance="High (API changes)", pricing="Monthly", risks="Account restrictions if rules are broken; no unofficial automation",
         ai="Optional"),
    dict(key="dashboard", name="Automated business dashboards", s=dict(value=2, feasibility=4, differentiation=2, recurring=3, risk=4),
         problem="No overview of bookings and revenue", payer="Owners with several data sources",
         competitors="Looker Studio, built-in reports", feasibility="High", difficulty="Low to medium",
         opcost="Low", maintenance="Medium", pricing="Setup + monthly", risks="Low perceived value for very small firms", ai="No"),
    dict(key="rebook", name="Rebooking reminders for repeat services",
         s=dict(value=4, feasibility=5, differentiation=3, recurring=4, risk=3),
         problem="Customers who should come back (e.g. every 3-6 months) forget", payer="Cleaning, detailing, servicing",
         competitors="Booking-platform marketing features", feasibility="High", difficulty="Low", opcost="Low",
         maintenance="Low", pricing="Bundle", risks="Marketing messages need prior consent (ZEK Art. 50)", ai="No"),
    dict(key="deposit", name="Deposits and prepayment links against no-shows",
         s=dict(value=3, feasibility=3, differentiation=2, recurring=3, risk=2),
         problem="No-shows on long or expensive jobs", payer="Detailing, beauty", competitors="Booking platforms with payments",
         feasibility="Medium (payment provider account per client)", difficulty="Medium", opcost="Payment fees",
         maintenance="Medium", pricing="Bundle or per transaction", risks="Refund disputes; handling payments raises the stakes",
         ai="No"),
]


def score(s):
    return round(100 * sum(WEIGHTS[k] * s[k] for k in WEIGHTS) / 5, 1)


def main():
    OUT.mkdir(exist_ok=True)
    order = sorted(SERVICES, key=lambda x: (-score(x["s"]), x["name"]))
    (OUT / "services.json").write_text(json.dumps(dict(weights=WEIGHTS, services=SERVICES), indent=1))
    md = ["# Automation services (Phase 2)", "",
          "Fit for the top niches (cleaning, detailing, trades). Scores 1-5 are estimates; risk 5 = low risk.", "",
          "| Rank | Service | Fit | Value | Feasibility | Differentiation | Recurring | Low risk | AI needed? |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for i, x in enumerate(order, 1):
        s = x["s"]
        md.append(f"| {i} | {x['name']} | {score(s)} | {s['value']} | {s['feasibility']} | {s['differentiation']} | "
                  f"{s['recurring']} | {s['risk']} | {x['ai']} |")
    md += ["", "## Details", ""]
    for x in order:
        md += [f"### {x['name']}", ""] + [f"- **{n}:** {x[f]}" for f, n in zip(FIELDS, FIELD_NAMES)] + [""]
    (OUT / "services.md").write_text("\n".join(md))
    for i, x in enumerate(order, 1):
        print(f"{i:>2} {x['name']:<62} {score(x['s']):>5}")


if __name__ == "__main__":
    main()
