"""Rules-based understanding of short Croatian and English customer messages.

It extracts what the booking flow needs (intent, service, size or floor area, date, time, name,
phone, e-mail, slot choice) and reports problems such as an impossible date instead of guessing.
Anything it is not confident about is left empty so the dialogue asks again or hands over to the
owner. No AI is involved; see llm.py for the optional AI interpreter that produces the same result.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field

FOLD = str.maketrans({"č": "c", "ć": "c", "š": "s", "ž": "z", "đ": "d", "Č": "c", "Ć": "c", "Š": "s", "Ž": "z", "Đ": "d"})


def fold(s: str) -> str:
    """Lower-case and strip Croatian diacritics so 'Sutra', 'četvrtak' and 'cetvrtak' match alike."""
    s = s.translate(FOLD).lower()
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


@dataclass
class Parsed:
    lang: str = ""
    intents: set = field(default_factory=set)
    service_id: str = ""
    size: str = ""
    area_m2: int = 0
    date: dt.date = None
    date_error: str = ""          # 'invalid_date' | 'past_date'
    time: dt.time = None
    window: tuple = None          # (start hour, end hour) for "morning" etc.
    time_error: str = ""          # 'invalid_time'
    phone: str = ""
    phone_error: str = ""         # 'invalid_phone'
    email: str = ""
    name: str = ""
    choice: int = 0               # 1-based index of an offered option
    ref: str = ""                 # booking reference such as QB-7K2M9
    source: str = "rules"

    def has_when(self) -> bool:
        return self.date is not None or self.time is not None or self.window is not None


# --------------------------------------------------------------------------- vocabularies (folded)
HR_HINTS = {"je", "li", "koliko", "kosta", "termin", "sutra", "danas", "molim", "hvala", "trebam", "imate", "cijena",
            "bok", "pozdrav", "moze", "zelim", "zelio", "zeljela", "auto", "auta", "stan", "stana", "ciscenje", "poliranje",
            "kad", "kada", "slobodno", "slobodan", "ujutro", "popodne", "zovem", "dobar", "dan", "da", "ne", "u", "za",
            "subotu", "petak", "ponedjeljak", "utorak", "srijedu", "cetvrtak", "nedjelju", "sati", "otkazati", "otkazi"}
EN_HINTS = {"the", "price", "how", "much", "tomorrow", "today", "please", "thanks", "thank", "available", "need",
            "hi", "hello", "can", "my", "car", "flat", "apartment", "cleaning", "polish", "when", "book", "booking",
            "appointment", "morning", "afternoon", "name", "is", "yes", "no", "at", "on", "for", "cancel", "want",
            "would", "like", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "what"}

INTENT_WORDS = {
    "human": ["covjek", "osoba", "vlasnik", "vlasnika", "nazovite me", "nazovi me", "zovite me", "razgovarati s nekim",
              "human", "real person", "call me", "speak to someone", "talk to someone", "operator", "agent"],
    "complaint": ["zalba", "zalim", "reklamacij", "nezadovolj", "nisam zadovolj", "nismo zadovolj", "ostecen",
                  "ostetili", "unistili", "povrat novca", "lose obavljen", "losa usluga", "lose ste",
                  "complain", "damaged", "refund", "not happy", "unhappy", "terrible", "angry"],
    "cancel": ["otkaz", "otkazati", "otkazujem", "ne mogu doci", "cancel"],
    "reschedule": ["pomakn", "promijeniti termin", "promjena termina", "drugi termin", "premjestiti", "prebaciti",
                   "reschedule", "move my", "change my booking", "change my appointment", "different time"],
    "book": ["termin", "rezerv", "naruc", "slobodn", "dogovoriti", "book", "appointment", "available", "availability",
             "schedule", "free slot"],
    "quote": ["cijen", "kosta", "kostalo", "koliko", "ponud", "price", "cost", "quote", "how much", "estimate"],
    "hours": ["radno vrijeme", "kada radite", "do kad radite", "otvoreni", "opening hours", "open on", "are you open", "hours"],
    "location": ["adresa", "gdje ste", "lokacija", "gdje se nalazite", "address", "where are you", "location"],
    "greeting": ["bok", "pozdrav", "dobar dan", "dobro jutro", "dobra vecer", "hej", "hello", "hi ", "hey", "good morning"],
    "thanks": ["hvala", "zahvaljujem", "thanks", "thank you"],
}
YES = {"da", "moze", "potvrdjujem", "potvrdujem", "potvrdi", "ok", "okej", "u redu", "vazi", "naravno", "svakako",
       "yes", "yep", "yeah", "sure", "confirm", "okay", "correct", "tocno", "slazem se", "i agree", "agree"}
NO = {"ne", "nemoj", "ne hvala", "nikako", "no", "nope", "no thanks", "dont", "do not", "ne zelim"}

WEEKDAYS = {  # folded stems -> weekday index (Mon=0); full words only to avoid 'pet' = five
    0: ["ponedjeljak", "ponedjeljka", "ponedeljak", "monday"],
    1: ["utorak", "utorka", "tuesday"],
    2: ["srijeda", "srijedu", "srijede", "srijedi", "wednesday"],
    3: ["cetvrtak", "cetvrtka", "thursday"],
    4: ["petak", "petka", "friday"],
    5: ["subota", "subotu", "subote", "suboti", "saturday"],
    6: ["nedjelja", "nedjelju", "nedjelje", "nedjelji", "sunday"],
}
MONTHS = {
    1: ["sijecnja", "sijecanj", "january", "jan"], 2: ["veljace", "veljaca", "february", "feb"],
    3: ["ozujka", "ozujak", "march", "mar"], 4: ["travnja", "travanj", "april", "apr"],
    5: ["svibnja", "svibanj", "may"], 6: ["lipnja", "lipanj", "june", "jun"], 7: ["srpnja", "srpanj", "july", "jul"],
    8: ["kolovoza", "kolovoz", "august", "aug"], 9: ["rujna", "rujan", "september", "sep", "sept"],
    10: ["listopada", "listopad", "october", "oct"], 11: ["studenoga", "studenog", "studeni", "november", "nov"],
    12: ["prosinca", "prosinac", "december", "dec"],
}
MONTH_LOOKUP = {w: m for m, ws in MONTHS.items() for w in ws}
WINDOWS = {"ujutro": (8, 12), "jutro": (8, 12), "jutarnj": (8, 12), "prijepodne": (8, 12), "morning": (8, 12),
           "popodne": (12, 17), "poslijepodne": (12, 17), "poslije podne": (12, 17), "afternoon": (12, 17),
           "navecer": (17, 21), "uvecer": (17, 21), "evening": (17, 21)}
ORDINALS = {"prvi": 1, "prva": 1, "prvo": 1, "first": 1, "drugi": 2, "druga": 2, "drugo": 2, "second": 2,
            "treci": 3, "treca": 3, "trece": 3, "third": 3, "cetvrti": 4, "fourth": 4}

RE_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(\.[\w-]+)+\b")
RE_PHONE = re.compile(r"(?<![\w+])(\+|00)?\d[\d \-/()]{6,}\d")   # no dots: "24. 11. 2026." is a date
RE_REF = re.compile(r"\bQB-[A-HJ-NP-Z2-9]{5}\b", re.I)
RE_AREA = re.compile(r"\b(\d{1,4})(?:[.,]\d+)?\s*(m2|m²|m\^2|kvadrat\w*|kvm|sqm|square met\w*)", re.I)
RE_DATE_NUM = re.compile(r"(?<![\d.:])(\d{1,2})\s*[./]\s*(\d{1,2})(?:\s*[./]\s*(\d{4}|\d{2})(?!\d)|\s*\.?\s+(\d{4})(?!\d))?\s*\.?(?![\d:])")
RE_DATE_ISO = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
RE_DATE_WORD = re.compile(r"\b(\d{1,2})\s*\.?\s*(?:of\s+)?([a-z]{3,10})\b")
RE_DATE_WORD_EN = re.compile(r"\b([a-z]{3,10})\s+(\d{1,2})(?:st|nd|rd|th)?\b")
RE_TIME_COLON = re.compile(r"\b(\d{1,2})\s*[:h]\s*(\d{2})\b")
RE_TIME_AMPM = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b")
RE_TIME_MARK = re.compile(r"\b(?:u|oko|at|around|za|from|od)\s+(\d{1,2})(?:\s*(?:h|sati|sat|ura|o'?clock))?\b(?!\s*(?:m2|kvadrat|m²|\.|/|min))")
RE_TIME_H = re.compile(r"\b(\d{1,2})\s*(?:h|sati|o'?clock)\b")
RE_NAME = [re.compile(r"\b(?i:zovem se|ja sam|moje ime je|ime(?: i prezime)?\s*[:\-])\s+([A-ZČĆŠŽĐ][\w'’-]+(?:\s+[A-ZČĆŠŽĐ][\w'’-]+)?)"),
           re.compile(r"\b(?i:my name is|name\s*[:\-]|this is)\s+([A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+)?)")]


def detect_language(text: str, default: str = "hr") -> str:
    raw = text.lower()
    if any(c in raw for c in "čćšžđ"):
        return "hr"
    words = re.findall(r"[a-z']+", fold(text))
    hr = sum(w in HR_HINTS for w in words)
    en = sum(w in EN_HINTS for w in words)
    if en > hr:
        return "en"
    if hr > en:
        return "hr"
    return default


def _has(text: str, phrases) -> bool:
    for p in phrases:
        if p.endswith(" ") or " " in p:
            if p in text:
                return True
        elif re.search(r"\b" + re.escape(p), text):
            return True
    return False


def normalize_phone(s: str) -> str:
    """Return the number in +385... form, or '' if it does not look like a valid phone number."""
    digits = re.sub(r"[^\d+]", "", s)
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if digits.startswith("0") and not digits.startswith("00"):
        digits = "+385" + digits[1:]
    if not digits.startswith("+"):
        return ""
    n = digits[1:]
    if not n.isdigit() or not 8 <= len(n) <= 15:
        return ""
    if n.startswith("385") and not 11 <= len(n) <= 12:
        return ""
    return "+" + n


def _resolve_date(day: int, month: int, year, today: dt.date):
    """Return (date, error). Dates without a year roll to next year only if clearly in the past."""
    try:
        if year is not None:
            year = int(year)
            if year < 100:
                year += 2000
            d = dt.date(year, month, day)
        else:
            d = dt.date(today.year, month, day)
            if d < today:
                if (today - d).days > 31:
                    d = dt.date(today.year + 1, month, day)
    except ValueError:
        return None, "invalid_date"
    if d < today:
        return d, "past_date"
    return d, ""


def parse_date(t: str, today: dt.date):
    """t is folded text. Returns (date or None, error, matched text to remove before time parsing)."""
    if re.search(r"\bprekosutra\b|\bday after tomorrow\b", t):
        return today + dt.timedelta(days=2), "", ""
    if re.search(r"\bsutra\b|\btomorrow\b", t):
        return today + dt.timedelta(days=1), "", ""
    if re.search(r"\bdanas\b|\btoday\b|\btonight\b|\bvecer?as\b", t):
        return today, "", ""
    m = RE_DATE_ISO.search(t)
    if m:
        return (*_resolve_date(int(m.group(3)), int(m.group(2)), m.group(1), today), m.group(0))
    for m in RE_DATE_NUM.finditer(t):
        a, b = int(m.group(1)), int(m.group(2))
        year = m.group(3) or m.group(4)
        tail = t[m.end():m.end() + 6]
        if year is None and re.match(r"\s*(h|sati|am|pm)\b", tail):
            continue                       # "10.30h" is a time
        if not (1 <= b <= 12):
            if year is None and b in (0, 15, 30, 45) and a <= 23:
                continue                   # "10.30" with no date context is a time
            return None, "invalid_date", m.group(0)
        return (*_resolve_date(a, b, year, today), m.group(0))
    for m in RE_DATE_WORD.finditer(t):
        mon = MONTH_LOOKUP.get(m.group(2))
        if mon:
            return (*_resolve_date(int(m.group(1)), mon, None, today), m.group(0))
    for m in RE_DATE_WORD_EN.finditer(t):
        mon = MONTH_LOOKUP.get(m.group(1))
        if mon and len(m.group(1)) >= 3:
            return (*_resolve_date(int(m.group(2)), mon, None, today), m.group(0))
    nxt = bool(re.search(r"\b(iduc\w*|sljedec\w*|next)\b", t))
    for wd, words in WEEKDAYS.items():
        if any(re.search(r"\b" + w + r"\b", t) for w in words):
            ahead = (wd - today.weekday()) % 7
            if ahead == 0:
                ahead = 7
            elif nxt and ahead <= 1:
                ahead += 7
            return today + dt.timedelta(days=ahead), "", ""
    return None, "", ""


def _hour(h: int, minute: int = 0):
    if not (0 <= h <= 23 and 0 <= minute <= 59):
        return None, "invalid_time"
    if 1 <= h <= 6:                       # "u 3" for a service business means 15:00
        h += 12
    return dt.time(h, minute), ""


def parse_time(t: str):
    """t is folded text with dates already removed. Returns (time, window, error)."""
    m = RE_TIME_AMPM.search(t)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if not 1 <= h <= 12 or mi > 59:
            return None, None, "invalid_time"
        if m.group(3) == "pm" and h != 12:
            h += 12
        if m.group(3) == "am" and h == 12:
            h = 0
        return dt.time(h, mi), None, ""
    m = RE_TIME_COLON.search(t)
    if m:
        tm, err = _hour(int(m.group(1)), int(m.group(2)))
        return tm, None, err
    m = RE_TIME_MARK.search(t) or RE_TIME_H.search(t)
    if m:
        tm, err = _hour(int(m.group(1)))
        return tm, None, err
    for w, win in WINDOWS.items():
        if re.search(r"\b" + w, t):
            return None, win, ""
    return None, None, ""


def parse(text: str, *, today: dt.date, services=(), sizes=None, lang_default: str = "hr", offered: int = 0) -> Parsed:
    """Parse one customer message. `services` are config.Service objects; `sizes` maps size id ->
    {"keywords": [...]}; `offered` is how many numbered options the customer was just shown."""
    p = Parsed()
    raw = text.strip()
    t = fold(raw)
    p.lang = detect_language(raw, lang_default)

    m = RE_EMAIL.search(raw)
    if m:
        p.email = m.group(0)
    m = RE_REF.search(raw)
    if m:
        p.ref = m.group(0).upper()
    scrub = RE_EMAIL.sub(" ", t)
    scrub = RE_REF.sub(" ", scrub)
    for m in RE_PHONE.finditer(scrub):
        cand = m.group(0)
        if re.fullmatch(r"\s*\d{1,4}\s*[-/]\s*\d{1,2}\s*[-/]\s*\d{1,4}\s*", cand):
            continue                       # 2026-12-01 or 1/12/2026 is a date, not a phone number
        if sum(c.isdigit() for c in cand) >= 8:
            num = normalize_phone(cand)
            if num:
                p.phone = num
            else:
                p.phone_error = "invalid_phone"
            scrub = scrub.replace(cand, " ")
            break
    for rx in RE_NAME:
        m = rx.search(raw)
        if m:
            p.name = m.group(1).strip()
            break

    for intent, words in INTENT_WORDS.items():
        if _has(t + " ", words):
            p.intents.add(intent)
    words = re.findall(r"[a-z']+", t)
    short = " ".join(words)
    if short in YES or (len(words) <= 4 and any(w in YES for w in words) and not any(w in NO for w in words)):
        p.intents.add("yes")
    if short in NO or (len(words) <= 3 and words and words[0] in ("ne", "no", "nope")):
        p.intents.add("no")
        p.intents.discard("yes")

    m = RE_AREA.search(t)
    if m:
        p.area_m2 = int(m.group(1))
        scrub = scrub.replace(m.group(0), " ")

    for s in services:
        if any(re.search(r"\b" + re.escape(k), t) for k in s.keywords):
            p.service_id = s.id
            break
    for sid, spec in (sizes or {}).items():
        if any(re.search(r"\b" + re.escape(fold(k)), t) for k in spec.get("keywords", [])):
            p.size = sid
            break

    d, err, matched = parse_date(scrub, today)
    p.date, p.date_error = d, err
    p.time, p.window, p.time_error = parse_time(scrub.replace(matched, " ", 1) if matched else scrub)

    if offered:
        bare = re.fullmatch(r"\s*(?:opcij\w*|option|broj|number|#)?\s*(\d)\s*[.)]?\s*", t)
        if bare and 1 <= int(bare.group(1)) <= offered:
            p.choice = int(bare.group(1))
            p.time = None
        else:
            for w, n in ORDINALS.items():
                if re.search(r"\b" + w + r"\b", t) and n <= offered:
                    p.choice = n
                    break
    return p

