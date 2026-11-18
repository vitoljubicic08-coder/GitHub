#!/usr/bin/env python3
"""Download macro / rate series used by the research: FRED (Federal Reserve Bank of St. Louis) and the ECB
Data Portal.

  python3 -I investing/research2026/fetch_macro.py --out <cache dir>

FRED: DEXUSEU (USD per EUR, Fed H.10 noon rate, from 1999), DFF, DGS2, DGS10, T10Y2Y, DTB3, UNRATE,
CPIAUCSL, BAMLH0A0HYM2 (US high-yield spread), DCOILBRENTEU (Brent).
ECB: EONIA (1999-2022) and the euro short-term rate EUR STR (from Oct 2019).
"""
import argparse
import subprocess
from pathlib import Path

FRED = ["DEXUSEU", "DFF", "DGS2", "DGS10", "T10Y2Y", "DTB3", "UNRATE", "CPIAUCSL", "BAMLH0A0HYM2", "DCOILBRENTEU"]
ECB = {"ecb_eonia": "EON/D.EONIA_TO.RATE", "ecb_estr": "EST/B.EU000A2X2A25.WT"}


def get(url, dest):
    subprocess.run(["curl", "-sSL", "--max-time", "60", "-o", str(dest), url], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    out = Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    for s in FRED:
        get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={s}", out / f"fred_{s}.csv")
    for name, key in ECB.items():
        get(f"https://data-api.ecb.europa.eu/service/data/{key}?format=csvdata", out / f"{name}.csv")
    print("ok", sorted(p.name for p in out.glob("*.csv")))


if __name__ == "__main__":
    main()
