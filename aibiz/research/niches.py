"""Phase 1: weighted ranking of 15 customer niches, with a weight-sensitivity check.

Every niche carries the 13 analysis criteria from the brief as short text, plus seven 1-5
scores (5 = best for us). The scores are analyst judgements built from the evidence cited in
research/SOURCES.md; they are estimates, not measurements. Interviews in the validation phase
are meant to replace them (see validation/VALIDATION_PLAN.md).

    python3 aibiz/research/niches.py          # writes research/results/niche_ranking.{json,md}
"""
from __future__ import annotations

import json
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent / "results"

# weight of each scored factor (sum 1.0). "regulatory", "competition" and "opcost" are scored
# so that 5 = LOW regulatory risk, LOW competition and LOW operating/support cost.
WEIGHTS = {
    "pain": 0.25,          # strength of the pain and clear money value of solving it
    "acquisition": 0.20,   # ease and cost of reaching and convincing owners
    "ease": 0.15,          # technical ease of implementation and integration
    "recurring": 0.15,     # recurring-revenue potential and retention
    "regulatory": 0.10,    # low GDPR / sector-regulation risk
    "competition": 0.10,   # low competition from existing software
    "opcost": 0.05,        # low operating and support cost per client
}
FACTOR_NAMES = {"pain": "Pain and value", "acquisition": "Acquisition", "ease": "Implementation ease",
                "recurring": "Recurring revenue", "regulatory": "Low regulatory risk",
                "competition": "Low competition", "opcost": "Low running cost"}

CRITERIA = ["customers", "admin_problems", "inquiries", "repetitive_time", "software", "automation",
            "willingness_to_pay", "gdpr", "difficulty", "competition", "acquisition", "mrr", "maintenance"]
CRITERIA_NAMES = ["Number and accessibility", "Admin problems", "Typical inquiries", "Time on repetitive tasks",
                  "Existing software", "Automation already used", "Willingness to pay (evidence)",
                  "GDPR complexity", "Implementation difficulty", "Competition", "Acquisition difficulty",
                  "Potential MRR per client (estimate)", "Maintenance and support"]

U = "unknown: measure in interviews (minutes per day on calls/DMs)"

NICHES = [
    dict(key="hair", name="Hair salons and barbershops",
         scores=dict(pain=3, acquisition=3, ease=3, recurring=4, regulatory=5, competition=1, opcost=4),
         customers="Many; the national hairdressers' and beauticians' guild grew by 1,040 crafts (+10.7%) in 2025. Easy to list from Fresha/Zoyya directories and Instagram",
         admin_problems="Phone bookings while cutting hair, no-shows, last-minute gaps",
         inquiries="Free slot today/tomorrow, prices, cancellations",
         repetitive_time=U,
         software="Fresha, Booksy, Zoyya (Croatian), Treatwell: cheap or free booking with reminders",
         automation="Yes: online booking and reminders are standard; Treatwell launched an AI receptionist in Sept 2026",
         willingness_to_pay="Anchors only: Fresha $19.95/month solo, Booksy GBP 40/month, AI receptionists EUR 59-199 (vendor listings)",
         gdpr="Low (contact and appointment data)",
         difficulty="Low to build, but the booking platforms own the calendar; little open API access (assumption)",
         competition="Very high: platforms bundle what we would sell",
         acquisition="Easy to reach in person, hard to sell: most already have a tool",
         mrr="EUR 30-80 (estimate)", maintenance="Low to medium"),
    dict(key="beauty", name="Beauty salons (nails, lashes, cosmetics)",
         scores=dict(pain=3, acquisition=3, ease=3, recurring=4, regulatory=4, competition=1, opcost=4),
         customers="Many; same guild and directories as hair salons",
         admin_problems="Long appointments, deposits against no-shows, DMs with photos",
         inquiries="Price of a treatment, availability, aftercare questions",
         repetitive_time=U,
         software="Same platforms as hair salons (Fresha, Booksy, Zoyya, Treatwell)",
         automation="Yes, through the platforms",
         willingness_to_pay="Same anchors as hair salons",
         gdpr="Low to medium: skin conditions or allergies can be health data",
         difficulty="Low to build; platform lock-in as above",
         competition="Very high", acquisition="Reachable via Instagram; already served",
         mrr="EUR 30-80 (estimate)", maintenance="Low to medium"),
    dict(key="dental", name="Dental clinics",
         scores=dict(pain=4, acquisition=2, ease=2, recurring=4, regulatory=1, competition=3, opcost=3),
         customers="Hundreds of private practices in Zagreb (estimate); reception staff act as gatekeepers",
         admin_problems="Phone-heavy reception, recall reminders, treatment quotes, dental-tourism inquiries in English",
         inquiries="Pain/emergency slots, prices of implants or crowns, HZZO coverage",
         repetitive_time=U,
         software="Practice-management systems with patient records; HZZO-contracted practices also use the national eHealth system",
         automation="Some (SMS reminders in practice software); depth unknown",
         willingness_to_pay="Higher value per patient; no public evidence of what clinics pay for add-ons",
         gdpr="High: health data is a special category (GDPR Art. 9); excluded from the first MVP",
         difficulty="High: integration with clinical systems and strict data handling",
         competition="Medium: specialised vendors", acquisition="Hard: formal buying, trust needed",
         mrr="EUR 100-300 (estimate)", maintenance="High (compliance, accuracy)"),
    dict(key="medical", name="Private medical practices",
         scores=dict(pain=4, acquisition=2, ease=2, recurring=4, regulatory=1, competition=3, opcost=3),
         customers="Many polyclinics and specialist practices; gatekept",
         admin_problems="Appointment triage, referrals, results questions",
         inquiries="Which specialist, waiting time, price lists, referral rules",
         repetitive_time=U,
         software="Medical practice systems; national eHealth for HZZO work",
         automation="Some reminders; triage must stay human",
         willingness_to_pay="Unknown; high stakes",
         gdpr="Very high: health data, possible medical-device rules if it gives advice",
         difficulty="High", competition="Medium", acquisition="Hard",
         mrr="EUR 100-300 (estimate)", maintenance="High"),
    dict(key="gym", name="Gyms and fitness studios",
         scores=dict(pain=3, acquisition=3, ease=3, recurring=4, regulatory=4, competition=2, opcost=4),
         customers="Dozens to low hundreds in Zagreb (estimate); active on Instagram",
         admin_problems="Trial sign-ups not followed up, class booking, membership renewals",
         inquiries="Prices, trial session, class timetable, personal trainer availability",
         repetitive_time=U,
         software="Gym-management and class-booking apps (international and local)",
         automation="Common for class booking and payments",
         willingness_to_pay="Unknown; lead follow-up has clear value per new member",
         gdpr="Low to medium (health questionnaires are health data)",
         difficulty="Medium", competition="High", acquisition="Medium",
         mrr="EUR 50-150 (estimate)", maintenance="Medium"),
    dict(key="detailing", name="Car detailing",
         scores=dict(pain=4, acquisition=4, ease=4, recurring=3, regulatory=5, competition=4, opcost=4),
         customers="Dozens in the Zagreb area (estimate; the prospect scan counts them). Most show prices, Instagram and WhatsApp publicly",
         admin_problems="Owner is hands-on and cannot answer while working; every quote depends on car size and condition; multi-hour jobs block the bay",
         inquiries="Price of polishing or ceramic coating for my car, free days, how long it takes",
         repetitive_time=U,
         software="Mostly phone, WhatsApp, Instagram and contact forms (to confirm in the prospect scan)",
         automation="Little visible (to confirm)",
         willingness_to_pay="Unknown. Job values on public price lists are high enough that one recovered job a month could cover a EUR 50-100 fee (to test)",
         gdpr="Low: name, phone, car model",
         difficulty="Medium: price ranges, multi-hour slots, one resource (bay)",
         competition="Low to medium locally; generic tools exist but are not tailored",
         acquisition="Medium: owners are busy, but reachable on Instagram or in person; small market per city",
         mrr="EUR 49-99 (estimate)", maintenance="Low"),
    dict(key="realestate", name="Real-estate agencies",
         scores=dict(pain=4, acquisition=3, ease=3, recurring=4, regulatory=3, competition=3, opcost=4),
         customers="Hundreds of agencies in Zagreb (estimate); listed on portals",
         admin_problems="Many portal inquiries, slow replies, scheduling viewings, unqualified leads",
         inquiries="Is it still available, viewing times, price negotiation, financing",
         repetitive_time=U,
         software="Agency CRMs and portal tools",
         automation="Some (portal auto-replies, CRM)",
         willingness_to_pay="Unknown; one sale is worth thousands in commission",
         gdpr="Medium: buyers' financial situation and identity documents",
         difficulty="Medium: portal integrations are limited", competition="Medium",
         acquisition="Medium", mrr="EUR 100-250 (estimate)", maintenance="Medium"),
    dict(key="accommodation", name="Hotels and accommodation",
         scores=dict(pain=3, acquisition=3, ease=3, recurring=4, regulatory=3, competition=2, opcost=4),
         customers="Hundreds of private apartments in Zagreb, many more on the coast (no official Zagreb count found)",
         admin_problems="Repeated guest questions, check-in instructions, guest registration, reviews",
         inquiries="Parking, check-in time, Wi-Fi, directions, late arrival",
         repetitive_time=U,
         software="Channel managers and property systems with automated messaging (e.g. Rentlio, Croatian; Smoobu)",
         automation="Common",
         willingness_to_pay="Anchored by channel-manager prices",
         gdpr="Medium: guest identity documents for registration",
         difficulty="Medium", competition="High", acquisition="Medium (seasonal on the coast)",
         mrr="EUR 20-60 per property (estimate)", maintenance="Medium"),
    dict(key="restaurant", name="Restaurants",
         scores=dict(pain=3, acquisition=3, ease=3, recurring=3, regulatory=5, competition=2, opcost=3),
         customers="Many; easy to find",
         admin_problems="Reservation calls at peak times, group bookings, menu questions",
         inquiries="Table tonight, group menu, opening hours, allergens",
         repetitive_time=U,
         software="Reservation platforms and Google reservations",
         automation="Common in larger venues",
         willingness_to_pay="Low margins; anchored by reservation platforms",
         gdpr="Low (allergen questions can touch health data)",
         difficulty="Medium: table logic, high message volume", competition="High",
         acquisition="Medium: owners busy at service times", mrr="EUR 30-80 (estimate)",
         maintenance="Medium (volume)"),
    dict(key="cleaning", name="Cleaning companies",
         scores=dict(pain=4, acquisition=4, ease=4, recurring=4, regulatory=4, competition=4, opcost=4),
         customers="Dozens of small firms in Zagreb (estimate); most advertise a phone, WhatsApp or form",
         admin_problems="Every job needs a quote (m2, type, extras); staff scheduling; repeat customers rebook by phone",
         inquiries="Price for a 70 m2 deep clean, after-renovation cleaning, regular weekly cleaning, free dates",
         repetitive_time=U,
         software="Mostly phone and messaging (to confirm); field-service tools such as Jobber exist (reported at about $29-199/month)",
         automation="Little visible (to confirm)",
         willingness_to_pay="Unknown; regular customers are worth a lot over a year (to test)",
         gdpr="Low to medium: home addresses, key or access details",
         difficulty="Medium: quote rules, team as the resource, travel time",
         competition="Low to medium locally", acquisition="Medium: reachable online",
         mrr="EUR 49-129 (estimate)", maintenance="Low"),
    dict(key="law", name="Law firms",
         scores=dict(pain=3, acquisition=1, ease=2, recurring=3, regulatory=1, competition=3, opcost=3),
         customers="Many small firms; conservative buyers",
         admin_problems="Intake of new matters, conflict checks, scheduling consultations",
         inquiries="Can you take my case, consultation price, urgency",
         repetitive_time=U,
         software="Practice management and document tools",
         automation="Low", willingness_to_pay="Unknown",
         gdpr="Very high: confidential and often sensitive data; professional secrecy",
         difficulty="High", competition="Medium", acquisition="Very hard for a new 18-year-old supplier",
         mrr="EUR 100-300 (estimate)", maintenance="High"),
    dict(key="accounting", name="Accounting firms",
         scores=dict(pain=4, acquisition=3, ease=2, recurring=5, regulatory=2, competition=3, opcost=3),
         customers="Many small bookkeeping services in Zagreb (estimate)",
         admin_problems="Chasing clients for documents every month, onboarding, deadline reminders; e-invoicing changes (Fiskalizacija 2.0) in 2026-2027",
         inquiries="Did you get my invoices, what do I need to send, deadlines",
         repetitive_time=U,
         software="Accounting packages and e-invoicing services",
         automation="Medium and growing with e-invoicing",
         willingness_to_pay="Unknown; time savings are clear",
         gdpr="High: clients' financial data (the brief excludes financial data from the first MVP)",
         difficulty="High: document processing must be accurate",
         competition="Medium (accounting-software vendors add these features)",
         acquisition="Medium: trust-based", mrr="EUR 80-200 (estimate)", maintenance="Medium to high"),
    dict(key="ecommerce", name="E-commerce shops",
         scores=dict(pain=4, acquisition=2, ease=3, recurring=4, regulatory=4, competition=1, opcost=3),
         customers="Many, reachable online; not tied to Zagreb",
         admin_problems="Order status questions, returns, product questions, abandoned carts",
         inquiries="Where is my order, return policy, size or stock questions",
         repetitive_time=U,
         software="Shop platforms with app stores full of AI support tools",
         automation="High", willingness_to_pay="Proven for tools, but crowded",
         gdpr="Low to medium", difficulty="Medium",
         competition="Very high, international", acquisition="Hard: competing with global SaaS marketing",
         mrr="EUR 50-200 (estimate)", maintenance="Medium"),
    dict(key="tutoring", name="Tutors and education",
         scores=dict(pain=3, acquisition=3, ease=4, recurring=3, regulatory=3, competition=3, opcost=4),
         customers="Many individuals and small schools; seasonal around exams",
         admin_problems="Scheduling lessons, payment reminders, parents' questions",
         inquiries="Free slots, price per hour, subjects, online or in person",
         repetitive_time=U,
         software="Calendars, booking links, school-management apps",
         automation="Medium (free booking links)", willingness_to_pay="Low budgets (individual tutors)",
         gdpr="Medium: many clients are minors", difficulty="Low",
         competition="Medium (free tools)", acquisition="Medium", mrr="EUR 20-60 (estimate)",
         maintenance="Low"),
    dict(key="trades", name="Small service companies and trades",
         scores=dict(pain=4, acquisition=3, ease=3, recurring=3, regulatory=5, competition=4, opcost=4),
         customers="Many plumbers, electricians, HVAC and appliance-repair firms; less active online",
         admin_problems="Missed calls while on a job, quotes, scheduling site visits around travel",
         inquiries="Can you come today, price for a boiler service, emergency call-out",
         repetitive_time=U,
         software="Phone and paper; some field-service apps",
         automation="Low (to confirm)", willingness_to_pay="Unknown; one missed job is worth EUR 50-300 (estimate)",
         gdpr="Low: name, address, phone", difficulty="Medium: variable durations and travel",
         competition="Low to medium locally", acquisition="Medium to hard: owners are on site and less online",
         mrr="EUR 49-99 (estimate)", maintenance="Low"),
]


def total(scores, w=WEIGHTS):
    """Weighted score on a 0-100 scale."""
    return round(100 * sum(w[k] * scores[k] for k in w) / 5, 1)


def rank(w=WEIGHTS):
    return sorted(NICHES, key=lambda n: (-total(n["scores"], w), n["name"]))


def sensitivity(draws=20_000, conc=20.0, seed=7):
    """Share of random weightings in which each niche is ranked in the top 3.

    Weights are Dirichlet draws centred on WEIGHTS (concentration `conc`), i.e. each weight
    varies by roughly +-30-50% of its value. A niche that stays in the top 3 across most draws
    does not owe its rank to the exact weights chosen."""
    rng = random.Random(seed)
    keys = list(WEIGHTS)
    top3 = {n["key"]: 0 for n in NICHES}
    first = {n["key"]: 0 for n in NICHES}
    for _ in range(draws):
        g = [rng.gammavariate(conc * WEIGHTS[k], 1.0) for k in keys]
        s = sum(g)
        w = {k: x / s for k, x in zip(keys, g)}
        order = rank(w)
        first[order[0]["key"]] += 1
        for n in order[:3]:
            top3[n["key"]] += 1
    return {k: top3[k] / draws for k in top3}, {k: first[k] / draws for k in first}


def equal_weights():
    return {k: 1 / len(WEIGHTS) for k in WEIGHTS}


def main():
    OUT.mkdir(exist_ok=True)
    order = rank()
    t3, f1 = sensitivity()
    eq = {n["key"]: i + 1 for i, n in enumerate(rank(equal_weights()))}
    rows = []
    for i, n in enumerate(order, 1):
        rows.append(dict(rank=i, key=n["key"], name=n["name"], score=total(n["scores"]), scores=n["scores"],
                         top3_share=round(t3[n["key"]], 3), first_share=round(f1[n["key"]], 3),
                         rank_equal_weights=eq[n["key"]]))
    (OUT / "niche_ranking.json").write_text(json.dumps(dict(weights=WEIGHTS, ranking=rows, niches=NICHES), indent=1))

    md = ["# Niche ranking (Phase 1)", "",
          "Scores 1-5 are analyst estimates from the cited evidence (5 = best for us; for regulation, competition and "
          "running cost 5 means LOW). Weighted score is on 0-100. 'In top 3' is the share of 20,000 random weightings "
          "(Dirichlet, centred on the base weights) that keep the niche in the top 3.", "",
          "| Rank | Niche | Score | " + " | ".join(f"{FACTOR_NAMES[k]} ({int(WEIGHTS[k]*100)}%)" for k in WEIGHTS)
          + " | In top 3 | Rank, equal weights |",
          "| --- " * (5 + len(WEIGHTS)) + "|"]
    for r in rows:
        md.append(f"| {r['rank']} | {r['name']} | {r['score']} | " + " | ".join(str(r['scores'][k]) for k in WEIGHTS)
                  + f" | {r['top3_share']*100:.0f}% | {r['rank_equal_weights']} |")
    md += ["", "## The 13 criteria per niche", ""]
    for n in order:
        md.append(f"### {n['name']}")
        md.append("")
        for c, cn in zip(CRITERIA, CRITERIA_NAMES):
            md.append(f"- **{cn}:** {n[c]}")
        md.append("")
    (OUT / "niche_ranking.md").write_text("\n".join(md))
    for r in rows:
        print(f"{r['rank']:>2} {r['name']:<40} {r['score']:>5}  top3 {r['top3_share']*100:5.1f}%  first {r['first_share']*100:5.1f}%  eq-rank {r['rank_equal_weights']}")


if __name__ == "__main__":
    main()
