#!/usr/bin/env python3
"""Turn backtest/results_props/*.csv into the markdown tables used in the report (SUMMARY.md)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

R = Path(sys.argv[1] if len(sys.argv) > 1 else "backtest/results_props")
FIRMS = ["tradeify", "topstep", "lucid", "alpha"]
NAMES = {"tradeify": "Tradeify Growth", "topstep": "Topstep", "lucid": "Lucid Flex", "alpha": "Alpha Std (manual)"}
SCEN = ["A_oos_edge", "B_75pct_edge", "C_50pct_edge", "D_25pct_edge", "E_no_edge", "F_exec_stress",
        "G_current_vol_A", "H_current_vol_B", "A_full_history"]
SNAME = {"A_oos_edge": "A  out-of-sample edge (+0.27R)", "B_75pct_edge": "B  75% of edge", "C_50pct_edge": "C  50% of edge",
         "D_25pct_edge": "D  25% of edge", "E_no_edge": "E  no edge (0 gross)", "F_exec_stress": "F  execution stress",
         "G_current_vol_A": "A at today's volatility", "H_current_vol_B": "B at today's volatility",
         "A_full_history": "Full 2023-26 history (partly in-sample)"}
RISKS = ["conservative", "moderate", "original", "aggressive", "very_aggressive"]
RNAME = {"conservative": "$150 / $100", "moderate": "$250 / $150", "original": "$350 / $250",
         "aggressive": "$500 / $300", "very_aggressive": "$750 / $400"}


def money(x):
    return f"{'+' if x > 0 else '−' if x < 0 else ''}${abs(x):,.0f}"


def load():
    L = pd.concat([pd.read_csv(R / "lifecycles.csv"), pd.read_csv(R / "lifecycles_curvol.csv")])
    B = pd.concat([pd.read_csv(R / "budgets.csv"), pd.read_csv(R / "budgets_curvol.csv")])
    return L, B


def table(rows, header):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def main() -> None:
    L, B = load()
    bs = L[L.method == "bootstrap"]
    md = ["# Prop-firm lifecycle simulation summary", ""]
    pick = lambda df, f, s, r, p: df[(df.firm == f) & (df.scenario == s) & (df.risk == r) & (df.policy == p)]

    md += ["## Mean net profit per attempt (P(profit)), $350 / $250, keep $2,000 cushion", ""]
    rows = []
    for s in SCEN:
        pol = "max_earliest" if s == "A_full_history" else "above_cushion"
        row = [SNAME[s]]
        for f in FIRMS:
            x = pick(bs, f, s, "original", pol)
            row.append(f"{money(x.mean_net_profit.iloc[0])} ({x.p_profit.iloc[0]:.0%})" if len(x) else "")
        rows.append(row)
    md += [table(rows, ["Scenario"] + [NAMES[f] for f in FIRMS]), ""]

    md += ["## Pass / first payout / median days to pass, $350 / $250, keep $2,000 cushion", ""]
    rows = []
    for s in SCEN[:8]:
        row = [SNAME[s]]
        for f in FIRMS:
            x = pick(bs, f, s, "original", "above_cushion")
            row.append(f"{x.pass_prob.iloc[0]:.0%} / {x.p_first_payout.iloc[0]:.0%} / {x.median_days_to_pass.iloc[0]:.0f}d")
        rows.append(row)
    md += [table(rows, ["Scenario"] + [NAMES[f] for f in FIRMS]), ""]

    for s in ("B_75pct_edge", "H_current_vol_B", "E_no_edge"):
        md += [f"## Risk configurations — {SNAME[s]}, keep $2,000 cushion: mean net per attempt (P(profit))", ""]
        rows = []
        for r in RISKS:
            row = [RNAME[r]]
            for f in FIRMS:
                x = pick(bs, f, s, r, "above_cushion")
                row.append(f"{money(x.mean_net_profit.iloc[0])} ({x.p_profit.iloc[0]:.0%})" if len(x) else "")
            rows.append(row)
        md += [table(rows, ["Eval / funded risk"] + [NAMES[f] for f in FIRMS]), ""]

    md += ["## Payout policy, $350 / $250, scenario B: mean net per attempt (P(profit))", ""]
    rows = []
    for p in ("max_earliest", "above_cushion", "extra_buffer", "lower_funded_risk"):
        row = [p]
        for f in FIRMS:
            x = pick(bs, f, "B_75pct_edge", "original", p)
            row.append(f"{money(x.mean_net_profit.iloc[0])} ({x.p_profit.iloc[0]:.0%})")
        rows.append(row)
    md += [table(rows, ["Policy"] + [NAMES[f] for f in FIRMS]), ""]

    md += ["## Full lifecycle metrics, $350 / $250, keep $2,000 cushion, scenario B", ""]
    mets = [("pass_prob", "Pass probability", "{:.0%}"), ("median_days_to_pass", "Median trading days to pass", "{:.0f}"),
            ("p_pass_1_month", "Pass within 1 month (21 trading days)", "{:.0%}"),
            ("p_pass_2_months", "Pass within 2 months", "{:.0%}"),
            ("mean_fees_per_attempt", "Mean fees per attempt", "${:,.0f}"), ("p_first_payout", "P(first payout)", "{:.0%}"),
            ("funded_lifespan_mean_days", "Funded lifespan, mean (trading days)", "{:.0f}"),
            ("funded_lifespan_median_days", "Funded lifespan, median", "{:.0f}"), ("mean_payouts", "Payouts per attempt", "{:.2f}"),
            ("median_payout", "Median payout (gross)", "${:,.0f}"), ("mean_gross_payouts", "Gross payouts per attempt", "${:,.0f}"),
            ("mean_net_payouts", "Net payouts per attempt (after split, $30 transfer)", "${:,.0f}"),
            ("mean_net_profit", "Mean net profit per attempt", "${:,.0f}"), ("median_net_profit", "Median net profit", "${:,.0f}"),
            ("p5_net_profit", "5th percentile", "${:,.0f}"), ("p95_net_profit", "95th percentile", "${:,.0f}"),
            ("max_loss", "Worst attempt", "${:,.0f}"), ("p_profit", "P(profit)", "{:.0%}"), ("p_loss", "P(loss)", "{:.0%}"),
            ("profit_per_fee_dollar", "Net profit per $1 of fees", "{:.1f}"), ("attempts_per_payout", "Attempts per payout", "{:.2f}"),
            ("p_moved_live", "Moved to live (not modelled further)", "{:.0%}")]
    rows = []
    for k, label, fmt in mets:
        row = [label]
        for f in FIRMS:
            v = pick(bs, f, "B_75pct_edge", "original", "above_cushion")[k].iloc[0]
            row.append(fmt.format(v))
        rows.append(row)
    md += [table(rows, ["Metric"] + [NAMES[f] for f in FIRMS]), ""]

    bb = B[(B.method == "bootstrap") & (B.risk == "original") & (B.policy == "above_cushion")]
    for s in ("B_75pct_edge", "H_current_vol_B", "E_no_edge"):
        md += [f"## Repeated attempts — {SNAME[s]}: mean net (median) / P(profit) by budget and horizon", ""]
        for f in FIRMS:
            rows = []
            for bud in (1, 5, 10, 25, 50):
                row = [bud]
                for h in ("3m", "6m", "12m", "24m"):
                    x = bb[(bb.firm == f) & (bb.scenario == s) & (bb.budget == bud) & (bb.horizon == h)]
                    row.append(f"{money(x.mean_net.iloc[0])} ({money(x.median_net.iloc[0])}) / {x.p_profit.iloc[0]:.0%}" if len(x) else "")
                rows.append(row)
            md += [f"**{NAMES[f]}**", "", table(rows, ["Budget (attempts)", "3 months", "6 months", "12 months", "24 months"]), ""]

    md += ["## Loss risk, budget 10 attempts, 12 months, $350 / $250, keep $2,000 cushion", ""]
    rows = []
    for s in ("A_oos_edge", "B_75pct_edge", "C_50pct_edge", "E_no_edge", "H_current_vol_B"):
        for f in FIRMS:
            x = bb[(bb.firm == f) & (bb.scenario == s) & (bb.budget == 10) & (bb.horizon == "12m")]
            if not len(x):
                continue
            x = x.iloc[0]
            rows.append([SNAME[s], NAMES[f], money(x.mean_net), money(x.p5_net), money(x.worst_net), f"{x.p_profit:.0%}",
                         f"${x.cash_before_first_payout_median:,.0f} / ${x.cash_before_first_payout_p95:,.0f}",
                         money(x.worst_cash_drawdown_p5), f"{x.p_budget_lost_no_payout:.0%}", money(x.mean_monthly_cashflow)])
    md += [table(rows, ["Scenario", "Firm", "Mean net", "5th pct", "Worst", "P(profit)", "Cash before 1st payout (median / 95th)",
                        "Cash drawdown (5th pct)", "P(no payout at all)", "Mean per month"]), ""]

    md += ["## Audit of the earlier estimate (generic $130 rules, $350 / $250, keep $2,000 cushion)", ""]
    rows = []
    for f, s, m, lab in (("audit_old", "A_full_history", "iid", "Earlier method: full history, daily iid, exact $ sizing, closed-trade drawdown"),
                         ("audit_fixed", "A_full_history", "bootstrap", "Same rules, corrected method, full history"),
                         ("audit_fixed", "A_oos_edge", "bootstrap", "Same rules, corrected method, holdout edge"),
                         ("audit_fixed", "E_no_edge", "bootstrap", "Same rules, corrected method, no edge")):
        x = L[(L.firm == f) & (L.scenario == s) & (L.method == m) & (L.risk == "original")].iloc[0]
        rows.append([lab, f"{x.pass_prob:.0%}", f"{x.p_first_payout:.0%}", money(x.mean_net_profit), money(x.median_net_profit), f"{x.p_profit:.0%}"])
    md += [table(rows, ["Method", "Pass", "First payout", "Mean net / attempt", "Median", "P(profit)"]), ""]

    md += ["## Intraday-trailing sensitivity (Topstep rules, scenario A, take max at earliest date)", ""]
    rows = []
    for r in RISKS[1:]:
        a = pick(bs, "topstep", "A_oos_edge", r, "max_earliest").iloc[0]
        b = L[(L.firm == "topstep_intraday") & (L.risk == r)].iloc[0]
        rows.append([RNAME[r], f"{a.pass_prob:.0%} → {b.pass_prob:.0%}", f"{money(a.mean_net_profit)} → {money(b.mean_net_profit)}"])
    md += [table(rows, ["Risk", "Pass (EOD → intraday trailing)", "Mean net (EOD → intraday)"]), ""]

    md += ["## Replay vs bootstrap, $350 / $250, take max at earliest date: mean net per attempt", ""]
    rows = []
    for s in SCEN[:6]:
        row = [SNAME[s]]
        for f in FIRMS:
            a = L[(L.firm == f) & (L.scenario == s) & (L.risk == "original") & (L.policy == "max_earliest")]
            row.append(" / ".join(money(a[a.method == m].mean_net_profit.iloc[0]) for m in ("bootstrap", "replay")))
        rows.append(row)
    md += [table(rows, ["Scenario (bootstrap / replay)"] + [NAMES[f] for f in FIRMS]), ""]
    (R / "SUMMARY.md").write_text("\n".join(md))
    print("\n".join(md))


if __name__ == "__main__":
    main()
