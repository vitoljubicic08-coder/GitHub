"""Phase 7 and 13: pricing tiers, delivery cost, 12-month scenarios and income-target feasibility.

Every input is listed in ASSUMPTIONS with its source or marked as an estimate. Official figures:
paušalni obrt tax classes and 2026 contributions (Porezna uprava, "Vodič namijenjen obrtnicima
paušalistima", fetched 2026-11-19), student-contract limit EUR 12,000 (Porezna uprava, "Učenici i
studenti"). Everything else is an estimate to be replaced with real pilot numbers.

    python3 aibiz/finance/model.py      # writes finance/results/model.json and model.md
"""
from __future__ import annotations

import json
import math
from pathlib import Path

OUT = Path(__file__).resolve().parent / "results"

TIERS = {   # hypotheses to test with real customers, anchored to competitor list prices
    "starter": dict(setup=199, monthly=59, onboarding_h=4, support_h=1.0, messages=0, msg_cost=0.0, ai=0.0,
                    note="Web chat + estimates + owner confirmation + e-mail notices; reminders by e-mail"),
    "pro": dict(setup=399, monthly=99, onboarding_h=8, support_h=1.5, messages=120, msg_cost=0.05, ai=2.0,
                note="Starter + WhatsApp Business Platform reminders (client's own number) + monthly report"),
    "premium": dict(setup=799, monthly=179, onboarding_h=16, support_h=3.0, messages=250, msg_cost=0.05, ai=4.0,
                    note="Pro + several teams/locations, calendar sync, custom integration, priority support"),
}
PILOT_PRICE = 149          # one-off for set-up + first 30 days, credited against set-up if they continue

ASSUMPTIONS = {
    "tier_mix": {"starter": 0.6, "pro": 0.3, "premium": 0.1},        # estimate
    "hosting_fixed": 8.0,            # EUR/month, one small VPS for all pilots (estimate)
    "hosting_per_client": 0.5,       # EUR/month extra disk/backup per client (estimate)
    "software_fixed": 15.0,          # domain, e-mail, off-site backup, uptime monitor (estimate)
    "chamber_fee": 10.0,             # Croatian Chamber of Trades contribution (estimate; verify amount)
    "payment_fee_pct": 0.0,          # invoices paid by bank transfer (bank fees ignored; estimate)
    "foreign_vat": 0.25,             # non-VAT paušalist self-assesses 25% HR VAT on services bought from the EU
                                     # (secondary sources; verify with Porezna uprava / accountant)
    "contributions_month": 290.98,   # 2026 official: 15% + 5% + 16.5% of EUR 797.20, when the obrt is the only insurance
    "marketing_cash": 20.0,          # EUR/month: printed one-pagers, a demo-video tool (estimate)
    "funnel": {"contacts": 30, "conversations": 5, "demos": 2, "customers": 1},   # the validation targets, not evidence
    "hours": {"contact": 0.25, "conversation": 0.75, "demo": 1.5, "proposal": 1.0},
    "churn_month": {"conservative": 0.05, "base": 0.03, "optimistic": 0.02},
    "customers_per_30_contacts": {"conservative": 0.5, "base": 1.0, "optimistic": 2.0},
    "max_contacts_month": 60,        # personalised outreach is slow: ~3 per working day (estimate)
}

# Paušalni obrt 2026 (official table): (upper receipts bound, annual tax)
PAUSAL_CLASSES = [(11300, 203.40), (15300, 275.40), (19900, 358.20), (30600, 550.80), (40000, 720.00),
                  (50000, 900.00), (60000, 1080.00)]
STUDENT_TAX_FREE = 12000           # EUR/year through student contracts (official)


def pausal_tax(annual_receipts: float) -> float:
    for limit, tax in PAUSAL_CLASSES:
        if annual_receipts <= limit:
            return tax
    return float("nan")            # above EUR 60,000: VAT registration and leaving the flat-rate scheme


def per_client_month(tier: str) -> dict:
    t, a = TIERS[tier], ASSUMPTIONS
    foreign = (t["messages"] * t["msg_cost"] + t["ai"]) * (1 + a["foreign_vat"])
    direct = foreign + a["hosting_per_client"] + t["monthly"] * a["payment_fee_pct"]
    return dict(revenue=t["monthly"], direct=round(direct, 2), gross=round(t["monthly"] - direct, 2),
                gross_margin=round(1 - direct / t["monthly"], 3), support_h=t["support_h"])


def mix_value(key: str) -> float:
    return sum(ASSUMPTIONS["tier_mix"][k] * TIERS[k][key] for k in TIERS)


def hours_per_customer_acquired(per30: float) -> float:
    a = ASSUMPTIONS
    f, h = a["funnel"], a["hours"]
    per_cycle = f["contacts"] * h["contact"] + f["conversations"] * h["conversation"] + f["demos"] * h["demo"] + h["proposal"]
    return per_cycle / per30


def scenario(target_n: int, case: str = "base", months: int = 12) -> dict:
    """Month 1 is validation (no revenue). Customers are added evenly from month 2 so that roughly
    target_n are active at month 12 after churn. The first two customers pay the pilot price
    instead of a set-up fee. Returns month-by-month figures."""
    a = ASSUMPTIONS
    churn = a["churn_month"][case]
    per30 = a["customers_per_30_contacts"][case]
    if target_n == 0:
        adds = [0.0] * months
    else:
        # constant monthly additions x from month 2: active_12 = x * sum_{k=0}^{10} (1-churn)^k
        x = target_n / sum((1 - churn) ** k for k in range(months - 1))
        adds = [0.0] + [x] * (months - 1)
    mrr_mix, setup_mix = mix_value("monthly"), mix_value("setup")
    direct_mix = sum(ASSUMPTIONS["tier_mix"][k] * per_client_month(k)["direct"] for k in TIERS)
    onboard_mix, support_mix = mix_value("onboarding_h"), mix_value("support_h")
    acq_h = hours_per_customer_acquired(per30)
    contacts_needed = [n * 30 / per30 for n in adds]
    active, total_added, rows = 0.0, 0.0, []
    for m in range(months):
        lost = active * churn
        active = active - lost + adds[m]
        new = adds[m]
        pilots = max(0.0, min(new, 2 - total_added)) if total_added < 2 else 0.0
        total_added += new
        setup_rev = pilots * PILOT_PRICE + (new - pilots) * setup_mix
        recurring = active * mrr_mix
        direct = active * direct_mix
        fixed = a["hosting_fixed"] + a["software_fixed"] + a["marketing_cash"]
        hours = new * onboard_mix + active * support_mix + new * acq_h
        rows.append(dict(month=m + 1, new=round(new, 2), churned=round(lost, 2), active=round(active, 2),
                         setup_revenue=round(setup_rev, 2), recurring_revenue=round(recurring, 2),
                         revenue=round(setup_rev + recurring, 2), direct_costs=round(direct, 2),
                         gross_profit=round(setup_rev + recurring - direct, 2), fixed_costs=round(fixed, 2),
                         hours=round(hours, 1), contacts=round(contacts_needed[m], 1)))
    revenue = sum(r["revenue"] for r in rows)
    tax = pausal_tax(revenue) if revenue > 0 else 0.0
    contrib = a["contributions_month"] * months
    chamber = a["chamber_fee"] * months
    gross = sum(r["gross_profit"] for r in rows)
    fixed = sum(r["fixed_costs"] for r in rows)
    op_before = gross - fixed                         # operating profit before tax and contributions
    take_obrt = op_before - tax - contrib - chamber   # paušalni obrt, insured through the obrt
    hours = sum(r["hours"] for r in rows)
    last = rows[-1]
    m12_profit = last["recurring_revenue"] - last["direct_costs"] - last["fixed_costs"] - a["contributions_month"] \
        - a["chamber_fee"] - (pausal_tax(12 * last["recurring_revenue"]) / 12 if last["recurring_revenue"] else 0)
    return dict(target=target_n, case=case, months=rows, totals=dict(
        revenue=round(revenue, 0), setup_revenue=round(sum(r["setup_revenue"] for r in rows), 0),
        recurring_revenue=round(sum(r["recurring_revenue"] for r in rows), 0),
        direct_costs=round(sum(r["direct_costs"] for r in rows), 0), gross_profit=round(gross, 0),
        gross_margin=round(gross / revenue, 3) if revenue else None, fixed_costs=round(fixed, 0),
        operating_profit_before_tax=round(op_before, 0), pausal_tax=round(tax, 0), contributions=round(contrib, 0),
        chamber=round(chamber, 0), take_home_obrt=round(take_obrt, 0),
        take_home_student_contracts=round(op_before, 0) if revenue <= STUDENT_TAX_FREE else None,
        hours=round(hours, 0), hourly_take_home_obrt=round(take_obrt / hours, 2) if hours else None,
        contacts=round(sum(r["contacts"] for r in rows), 0),
        mrr_month12=round(last["recurring_revenue"], 0), active_month12=round(last["active"], 1),
        monthly_take_home_run_rate_m12=round(m12_profit, 0)))


def targets(case: str) -> list:
    """Customers and hours needed for a monthly recurring revenue target, plus months to get there."""
    a = ASSUMPTIONS
    arpu = mix_value("monthly")
    direct_mix = sum(a["tier_mix"][k] * per_client_month(k)["direct"] for k in TIERS)
    churn = a["churn_month"][case]
    per30 = a["customers_per_30_contacts"][case]
    max_adds = a["max_contacts_month"] * per30 / 30
    out = []
    for goal in (500, 1000, 2000, 3000, 5000):
        n = math.ceil(goal / arpu)
        # steady state: replacing churn needs n*churn new customers a month
        if max_adds <= n * churn:
            months = None
        else:
            months = math.ceil(math.log(1 - n * churn / max_adds) / math.log(1 - churn)) if churn else math.ceil(n / max_adds)
        support = n * mix_value("support_h")
        acq = n * churn * hours_per_customer_acquired(per30)
        fixed = a["hosting_fixed"] + a["software_fixed"] + a["marketing_cash"] + a["chamber_fee"] + a["contributions_month"]
        tax_m = pausal_tax(goal * 12) / 12
        take = goal - n * direct_mix - fixed - tax_m
        by_price = {p: math.ceil(goal / p) for p in (59, 99, 179)}
        out.append(dict(goal=goal, customers=n, customers_at_price=by_price, months_to_reach=months,
                        support_h_month=round(support, 1), acquisition_h_month=round(acq, 1),
                        take_home_month=round(take, 0)))
    return out


def main():
    OUT.mkdir(exist_ok=True)
    tiers = {k: dict(TIERS[k], **per_client_month(k)) for k in TIERS}
    scen = {case: [scenario(n, case) for n in (0, 1, 3, 5, 10, 20, 30)] for case in ("conservative", "base", "optimistic")}
    tg = {case: targets(case) for case in ("conservative", "base", "optimistic")}
    res = dict(assumptions=ASSUMPTIONS, tiers=tiers, pilot_price=PILOT_PRICE, pausal_classes=PAUSAL_CLASSES,
               arpu_mix=round(mix_value("monthly"), 2), setup_mix=round(mix_value("setup"), 2),
               hours_per_customer_acquired={c: round(hours_per_customer_acquired(v), 1)
                                            for c, v in ASSUMPTIONS["customers_per_30_contacts"].items()},
               scenarios=scen, targets=tg)
    (OUT / "model.json").write_text(json.dumps(res, indent=1))

    md = ["# Financial model (estimates)", "", "Inputs and sources are in `finance/model.py`. All amounts in EUR.", "",
          "## Per-client economics (per month)", "",
          "| Tier | Set-up | Monthly | Direct cost | Gross margin | Onboarding h | Support h/month |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    for k, t in tiers.items():
        md.append(f"| {k} | {t['setup']} | {t['monthly']} | {t['direct']:.2f} | {t['gross_margin']*100:.0f}% | "
                  f"{t['onboarding_h']} | {t['support_h']} |")
    md += ["", "## 12-month scenarios (base case)", "",
           "| Active at month 12 | Revenue | of which set-up | Gross profit | Operating profit before tax | "
           "Paušal tax | Contributions | Take-home (obrt) | Take-home if on student contracts | Hours | Take-home per hour | "
           "Month-12 monthly take-home |",
           "| --- " * 12 + "|"]
    for s in scen["base"]:
        t = s["totals"]
        st = "n/a (over 12,000)" if t["take_home_student_contracts"] is None else f"{t['take_home_student_contracts']:.0f}"
        hr = "—" if t["hourly_take_home_obrt"] is None else f"{t['hourly_take_home_obrt']:.2f}"
        md.append(f"| {s['target']} | {t['revenue']:.0f} | {t['setup_revenue']:.0f} | {t['gross_profit']:.0f} | "
                  f"{t['operating_profit_before_tax']:.0f} | {t['pausal_tax']:.0f} | {t['contributions']:.0f} | "
                  f"{t['take_home_obrt']:.0f} | {st} | {t['hours']:.0f} | {hr} | {t['monthly_take_home_run_rate_m12']:.0f} |")
    md += ["", "## Monthly recurring revenue targets", ""]
    for case, rows in tg.items():
        md += [f"### {case}", "", "| MRR goal | Customers (mix) | at €59 / €99 / €179 | Months to reach | Support h/month | "
               "Acquisition h/month | Monthly take-home |", "| --- " * 7 + "|"]
        for r in rows:
            p = r["customers_at_price"]
            mt = "not reachable at 60 contacts/month" if r["months_to_reach"] is None else r["months_to_reach"]
            md.append(f"| {r['goal']} | {r['customers']} | {p[59]} / {p[99]} / {p[179]} | {mt} | {r['support_h_month']} | "
                      f"{r['acquisition_h_month']} | {r['take_home_month']:.0f} |")
        md.append("")
    (OUT / "model.md").write_text("\n".join(md))
    print("\n".join(md))


if __name__ == "__main__":
    main()
