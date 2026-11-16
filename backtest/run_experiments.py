#!/usr/bin/env python3
"""Run SIP-ORB strategy variants on one period of the candidate cache and log every run.

Every evaluated variant is appended to the research log (CSV) with its settings, the period and its
metrics, so the total number of variants tried is always visible (a guard against cherry-picking).

Usage (as a module):
  from run_experiments import Lab
  lab = Lab(cache_dir, log_path, period=("dev", 20230301, 20241231))
  lab.run([Variant(...), ...])
"""
from __future__ import annotations

import csv
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import variant_lab as vl  # noqa: E402


class Lab:
    def __init__(self, cache_dir: str, log_path: str, period: tuple[str, int, int]):
        self.label, start, end = period
        t0 = time.time()
        self.data = vl.load_cache(cache_dir, start, end)
        self.log_path = Path(log_path)
        print(f"[{self.label}] {len(self.data['dkey']):,} candidate stock-days "
              f"{start}..{end} loaded in {time.time() - t0:.0f}s")

    def run(self, variants: list[vl.Variant], show: bool = True) -> dict[str, dict]:
        out = {}
        if show:
            print(vl.HEADER)
        new_file = not self.log_path.exists()
        with self.log_path.open("a", newline="") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["period", "variant", "params", "trades", "win_rate", "avg_r", "pf",
                            "pos_months", "pos_years", "sharpe_daily", "max_dd_r", "by_year"])
            for v in variants:
                res = vl.simulate(self.data, v)
                m = vl.metrics(res)
                out[v.name] = {"metrics": m, "result": res}
                if show:
                    print(vl.fmt(v.name, m), flush=True)
                params = {k: val for k, val in asdict(v).items() if k not in ("name", "notes")}
                w.writerow([self.label, v.name, json.dumps(params), m.get("trades", 0),
                            round(m.get("win_rate", 0), 2), round(m.get("avg_r", 0), 4),
                            round(m.get("pf", 0), 3), m.get("pos_months", ""), m.get("pos_years", ""),
                            round(m.get("sharpe_daily", 0), 2), round(m.get("max_dd_r", 0), 1),
                            json.dumps(m.get("by_year", {}))])
        return out
