#!/usr/bin/env python3
"""Download official web pages through the session proxy and save readable text (for rule verification).

Usage: python3 backtest/fetch_pages.py <out_dir> <url> [<url> ...]
Each page is saved as <out_dir>/<slug>.html and <out_dir>/<slug>.txt (scripts/styles stripped).
"""
from __future__ import annotations

import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self.skip += 1
        if tag in ("p", "li", "br", "tr", "h1", "h2", "h3", "h4", "div", "td", "th"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def slug(url: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", url.split("://", 1)[-1]).strip("_")[:120]


def main() -> None:
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    for url in sys.argv[2:]:
        html_path = out / f"{slug(url)}.html"
        code = subprocess.run(["curl", "-sS", "-L", "--max-time", "45", "-A", UA, "-o", str(html_path),
                               "-w", "%{http_code}", url], capture_output=True, text=True).stdout
        text = ""
        if html_path.exists():
            p = _Text(); p.feed(html_path.read_text(errors="ignore")); text = "".join(p.parts)
            text = re.sub(r"[ \t\r\f\v]+", " ", text); text = re.sub(r"\n\s*\n+", "\n", text).strip()
        (out / f"{slug(url)}.txt").write_text(text)
        print(f"{code} {len(text):>7} chars  {url}", flush=True)


if __name__ == "__main__":
    main()
