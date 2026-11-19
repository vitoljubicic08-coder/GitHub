"""Optional AI interpreter (off by default).

The rules parser always runs first. When enabled (QB_ENABLE_LLM=1, `pip install anthropic`,
ANTHROPIC_API_KEY set), Claude is asked to fill only the fields the rules left empty, using a
strict JSON schema. Every value it returns is validated against the business configuration;
names and phone numbers are accepted only if they appear in the customer's own text. On any
error, timeout, refusal or invalid output the rules result is used unchanged, and after several
failures in a row the AI step is skipped for a few minutes (circuit breaker).

Phone numbers and e-mail addresses are removed from the text before it is sent.

Not verified against the live API in this repository (no API key, no spending); the tests use a
fake client. Verify with a real key before relying on it.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import time

from . import parser as rules

log = logging.getLogger("quotebook.llm")

INTENTS = ["book", "quote", "cancel", "reschedule", "human", "complaint", "hours", "location", "greeting", "thanks",
           "yes", "no"]

SYSTEM = ("You extract booking details from one customer message to a small service business in Croatia. "
          "Messages are in Croatian or English. Return only what the message states; use null when it does not "
          "say. Dates are ISO (YYYY-MM-DD) resolved against the given 'today'; times are 24-hour HH:MM.")


def schema(service_ids, size_ids):
    return {
        "type": "object",
        "properties": {
            "language": {"type": "string", "enum": ["hr", "en"]},
            "intents": {"type": "array", "items": {"type": "string", "enum": INTENTS}},
            "service_id": {"type": ["string", "null"], "enum": list(service_ids) + [None]},
            "size": {"type": ["string", "null"], "enum": list(size_ids) + [None]},
            "area_m2": {"type": ["integer", "null"]},
            "date": {"type": ["string", "null"]},
            "time": {"type": ["string", "null"]},
            "name": {"type": ["string", "null"]},
        },
        "required": ["language", "intents", "service_id", "size", "area_m2", "date", "time", "name"],
        "additionalProperties": False,
    }


def redact(text: str) -> str:
    text = rules.RE_EMAIL.sub("[email]", text)
    return rules.RE_PHONE.sub(lambda m: "[phone]" if sum(c.isdigit() for c in m.group(0)) >= 8 else m.group(0), text)


class LLMInterpreter:
    def __init__(self, cfg, client=None, failure_threshold: int = 3, cooldown_s: float = 300.0, clock=time.monotonic):
        self.cfg = cfg
        self.model = cfg.assistant["llm_model"]
        self.timeout = float(cfg.assistant["llm_timeout_s"])
        self.client = client
        self.failure_threshold = failure_threshold
        self.cooldown_s = cooldown_s
        self.clock = clock
        self.failures = 0
        self.open_until = 0.0
        self.calls = 0

    @classmethod
    def from_env(cls, cfg):
        import anthropic  # optional dependency
        return cls(cfg, client=anthropic.Anthropic(timeout=float(cfg.assistant["llm_timeout_s"]), max_retries=2))

    def available(self) -> bool:
        return self.client is not None and self.clock() >= self.open_until

    def _call(self, text: str, today: dt.date) -> dict:
        cfg = self.cfg
        services = "; ".join(f"{s.id} = {s.name('en')} / {s.name('hr')}" for s in cfg.services)
        sizes = "; ".join(f"{k} = {v.get('en', k)}" for k, v in cfg.sizes.items()) or "none"
        prompt = (f"today: {today.isoformat()} ({today.strftime('%A')})\nservices: {services}\nsizes: {sizes}\n"
                  f"message:\n{redact(text)[:1000]}")
        resp = self.client.beta.messages.create(
            model=self.model,
            max_tokens=2048,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM,
            output_config={"effort": "low",
                           "format": {"type": "json_schema", "schema": schema([s.id for s in cfg.services],
                                                                               list(cfg.sizes))}},
            messages=[{"role": "user", "content": prompt}],
        )
        self.calls += 1
        if resp.stop_reason in ("refusal", "max_tokens"):
            raise ValueError(f"stop_reason={resp.stop_reason}")
        out = next(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return json.loads(out)

    def parse(self, text: str, *, today: dt.date, services=(), sizes=None, lang_default="hr", offered=0):
        base = rules.parse(text, today=today, services=services, sizes=sizes, lang_default=lang_default, offered=offered)
        complete = base.service_id and (base.size or base.area_m2 or self.cfg.measure == "none") and base.has_when()
        if complete or base.choice or not self.available():
            return base
        try:
            data = self._call(text, today)
        except Exception as e:  # network, timeout, API error, refusal, bad JSON: fall back to rules
            self.failures += 1
            if self.failures >= self.failure_threshold:
                self.open_until = self.clock() + self.cooldown_s
                log.warning("AI interpreter failing (%s); using rules only for %.0f s", e, self.cooldown_s)
            else:
                log.warning("AI interpreter error, using rules: %s", e)
            return base
        self.failures = 0
        return merge(base, data, text, today, self.cfg)


def merge(base, data: dict, text: str, today: dt.date, cfg):
    """Fill empty fields of the rules result with validated AI values."""
    p = base
    ids = {s.id for s in cfg.services}
    if not p.service_id and data.get("service_id") in ids:
        p.service_id = data["service_id"]
    if not p.size and data.get("size") in cfg.sizes:
        p.size = data["size"]
    a = data.get("area_m2")
    if not p.area_m2 and isinstance(a, int) and 10 <= a <= 1000 and str(a) in text:
        p.area_m2 = a
    if p.date is None and not p.date_error and data.get("date"):
        try:
            d = dt.date.fromisoformat(data["date"])
            if today <= d <= today + dt.timedelta(days=366):
                p.date = d
        except ValueError:
            pass
    if p.time is None and p.window is None and data.get("time"):
        if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", data["time"]):
            p.time = dt.time.fromisoformat(data["time"])
    n = data.get("name")
    if not p.name and isinstance(n, str) and 1 < len(n) <= 60 and n in text:
        p.name = n
    for i in data.get("intents") or []:
        if i in INTENTS:
            p.intents.add(i)
    p.source = "rules+llm"
    return p
