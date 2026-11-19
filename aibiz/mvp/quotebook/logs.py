"""JSON-lines logging with phone numbers and e-mail addresses masked."""
from __future__ import annotations

import json
import logging
import re
import sys
import time

PHONE = re.compile(r"(\+?\d[\d \-/]{6,}\d)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")


def redact(s: str) -> str:
    s = EMAIL.sub("[email]", s)
    return PHONE.sub(lambda m: m.group(0)[:4] + "***" if sum(c.isdigit() for c in m.group(0)) >= 8 else m.group(0), s)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)), "level": record.levelname,
               "logger": record.name, "msg": redact(record.getMessage())}
        if record.exc_info:
            rec["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(rec, ensure_ascii=False)


def setup(level="INFO", path=None):
    handlers = [logging.StreamHandler(sys.stderr)]
    if path:
        handlers.append(logging.FileHandler(path, encoding="utf-8"))
    for h in handlers:
        h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = handlers
    root.setLevel(level)
