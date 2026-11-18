#!/usr/bin/env python3
"""Fetch UCITS ETF / ETC facts from justETF profile pages (name, TER, domicile, replication, distribution,
fund currency, size, inception, listings with trading currency and ticker).

  python3 -I investing/research2026/fetch_etf_facts.py --out <cache dir>

Writes <out>/etf_facts.json and keeps each page under <out>/justetf/. Third-party data, not committed.
"""
import argparse
import json
import re
import subprocess
import time
from pathlib import Path

from bs4 import BeautifulSoup

ISINS = {
    "IE00BK5BQT80": "Vanguard FTSE All-World Acc (VWCE)",
    "IE00B4L5Y983": "iShares Core MSCI World Acc (EUNL)",
    "IE00B6R52259": "iShares MSCI ACWI Acc (IUSQ)",
    "IE00B3YLTY66": "SPDR MSCI ACWI IMI (SPYI)",
    "IE00B5BMR087": "iShares Core S&P 500 Acc (SXR8/CSPX)",
    "IE00BFMXXD54": "Vanguard S&P 500 Acc (VUAA)",
    "IE00BLNMYC90": "Xtrackers S&P 500 Equal Weight (XDEW)",
    "IE00B53SZB19": "iShares Nasdaq 100 Acc (SXRV/CNDX)",
    "IE00BFZXGZ54": "Invesco EQQQ Nasdaq-100 Acc",
    "IE00BMFKG444": "Xtrackers Nasdaq 100 1C (XNAS)",
    "LU1829221024": "Amundi Nasdaq-100 II Acc",
    "IE00BMC38736": "VanEck Semiconductor (VVSM)",
    "IE000I8KRLL9": "iShares MSCI Global Semiconductors (SEC0)",
    "IE00BGV5VN51": "Xtrackers Artificial Intelligence & Big Data (XAIX)",
    "IE00BDVPNG13": "WisdomTree Artificial Intelligence (WTAI)",
    "IE00B3WJKG14": "iShares S&P 500 Information Technology (QDVE)",
    "IE00BM67HT60": "Xtrackers MSCI World Information Technology (XDWT)",
    "IE00BP3QZ601": "iShares Edge MSCI World Quality Factor (IS3Q)",
    "IE00BP3QZ825": "iShares Edge MSCI World Momentum Factor (IS3R)",
    "IE00BSPLC413": "SPDR MSCI USA Small Cap Value Weighted (ZPRV)",
    "IE00BF4RFH31": "iShares MSCI World Small Cap (IUSN)",
    "IE00BKM4GZ66": "iShares Core MSCI EM IMI (IS3N)",
    "IE00B4K48X80": "iShares Core MSCI Europe Acc (SMEA)",
    "LU0908500753": "Amundi Core Stoxx Europe 600 (MEUD)",
    "IE00BM67HK77": "Xtrackers MSCI World Health Care (XDWH)",
    "LU0290358497": "Xtrackers II EUR Overnight Rate Swap (XEON)",
    "IE00BCRY6557": "iShares EUR Ultrashort Bond Dist (IS3M)",
    "IE00B8FHGS14": "iShares Edge MSCI World Minimum Volatility (IQQ0)",
    "IE00BD1F4L37": "iShares Edge MSCI USA Quality Factor (QDVB)",
    "IE00B4L5YC18": "iShares MSCI EM Acc (EUNM; looked up as a mid-cap fund, but justETF shows EM)",
    "IE00BL25JL35": "Xtrackers MSCI World Quality",
    "IE00B4WXJJ64": "iShares Core Euro Government Bond (EUNH)",
    "DE000A0S9GB0": "Xetra-Gold (4GLD)",
    "IE00B4ND3602": "iShares Physical Gold ETC (SGLN/IGLN)",
    "IE00B579F325": "Invesco Physical Gold ETC (SGLD)",
}
FIELDS = ["Total expense ratio", "Replication", "Fund currency", "Currency hedged", "Inception/ Listing Date",
          "Distribution policy", "Fund domicile", "Fund Provider", "Fund size", "Index", "Legal structure"]


def parse(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "svg"]):
        t.decompose()
    lines = [l.strip() for l in soup.get_text("\n").splitlines() if l.strip()]
    rec = {"name": soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else None}
    for f in FIELDS:
        if f in lines:
            i = lines.index(f)
            v = lines[i + 1]
            if f == "Replication" and i + 3 < len(lines) and lines[i + 2] == "(":
                v += " (" + lines[i + 3] + ")"
            rec[f] = v
    listings = []
    for table in soup.find_all("table"):
        head = [th.get_text(" ", strip=True) for th in table.find_all("th")]
        if any("Trade Currency" in h for h in head):
            for tr in table.find_all("tr")[1:]:
                cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
                if len(cells) >= 3:
                    listings.append({"exchange": cells[0], "currency": cells[1], "ticker": cells[2]})
    rec["listings"] = listings
    m = re.search(r"Maximum drawdown since inception\s*\n?(-?[\d.,]+%)", "\n".join(lines))
    rec["max_drawdown_since_inception"] = m.group(1) if m else None
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    raw = Path(a.out) / "justetf"
    raw.mkdir(parents=True, exist_ok=True)
    out = {}
    for isin, label in ISINS.items():
        f = raw / f"{isin}.html"
        if not f.exists():
            subprocess.run(["curl", "-sSL", "--max-time", "40", "-o", str(f),
                            f"https://www.justetf.com/en/etf-profile.html?isin={isin}"], check=False)
            time.sleep(2)
        try:
            rec = parse(f.read_text(errors="replace"))
        except Exception as e:                                        # noqa: BLE001 - reported per fund
            rec = {"error": repr(e)}
        rec["label"] = label
        rec["url"] = f"https://www.justetf.com/en/etf-profile.html?isin={isin}"
        out[isin] = rec
        print(isin, rec.get("name"), rec.get("Total expense ratio"), rec.get("Fund domicile"),
              [l["ticker"] for l in rec.get("listings", []) if l["currency"] == "EUR"][:4], flush=True)
    (Path(a.out) / "etf_facts.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
