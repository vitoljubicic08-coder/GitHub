"""Every customer-facing sentence, in Croatian and English. Owners can override any key in the
business JSON under "texts": {"hr": {...}, "en": {...}}."""
from __future__ import annotations

import datetime as dt

TEXTS = {
    "hr": {
        "greeting": "Pozdrav! Ja sam automatski asistent tvrtke {business}. Mogu vam dati okvirnu cijenu i "
                    "pronaći slobodan termin; vlasnik potvrđuje svaku rezervaciju.",
        "ask_service": "Koju uslugu trebate?",
        "ask_service_first": "Za koju uslugu ste zainteresirani?",
        "ask_size": "Koje je vozilo? ({options})",
        "ask_area": "Koliko otprilike kvadrata (m²) ima prostor?",
        "bad_area": "Površinu mogu procijeniti između 10 i 1000 m². Koliko kvadrata ima prostor?",
        "estimate": "{service}: okvirno {low}–{high} € (procjena; konačnu cijenu vlasnik potvrđuje nakon pregleda). "
                    "Traje oko {duration}.",
        "ask_when": "Koji dan i vrijeme vam odgovaraju?",
        "offer": "Slobodni termini:\n{options}\nOdaberite broj (1–{n}) ili napišite drugi dan.",
        "offer_other_day": "Na taj dan nema slobodnog termina za ovu uslugu. Najbliži slobodni:\n{options}\n"
                           "Odaberite broj (1–{n}) ili napišite drugi dan.",
        "no_slots": "Nažalost, u sljedećih {days} dana nema slobodnog termina za ovu uslugu. Proslijedio sam upit "
                    "vlasniku, javit će vam se.",
        "closed_day": "Taj dan ne radimo.",
        "invalid_date": "Taj datum ne postoji. Možete li ga napisati ponovno (npr. 24.11.)?",
        "past_date": "Taj je datum već prošao. Koji vam drugi dan odgovara?",
        "invalid_time": "To vrijeme ne razumijem (npr. 10:30 ili \"u 14\"). Koje vrijeme vam odgovara?",
        "held": "Držim vam termin {when} sljedećih {minutes} minuta. Kako se zovete i koji je vaš broj mobitela?",
        "ask_name": "Kako se zovete?",
        "ask_phone": "Koji je vaš broj mobitela (npr. 091 234 5678)?",
        "bad_phone": "Taj broj ne izgleda ispravno. Možete li ga napisati ponovno (npr. 091 234 5678)?",
        "ask_consent": "Želite li podsjetnik dan prije termina? (da/ne)",
        "pending": "Hvala, {name}! Zahtjev za termin {when} ({ref}) je zaprimljen, ali JOŠ NIJE POTVRĐEN. "
                   "Vlasnik će ga potvrditi i javiti vam se.",
        "confirmed_now": "Hvala, {name}! Termin {when} je potvrđen. Broj rezervacije: {ref}.",
        "slot_gone": "Taj termin je u međuvremenu zauzet. Evo drugih:\n{options}\nOdaberite broj (1–{n}).",
        "hold_expired": "Isteklo je vrijeme za držanje termina. Provjeravam ponovno slobodne termine.",
        "choose_number": "Odaberite jedan od ponuđenih brojeva (1–{n}) ili napišite drugi dan.",
        "unclear": "Nisam siguran da sam razumio. Možete li napisati uslugu i dan koji vam odgovara?",
        "handoff": "Proslijedio sam vašu poruku vlasniku, javit će vam se osobno što prije.",
        "paused": "Hvala na poruci! Vlasnik će vam odgovoriti osobno.",
        "hours": "Radno vrijeme: {hours}.",
        "location": "{location}",
        "cancel_ask_ref": "Za otkazivanje mi trebaju broj rezervacije (npr. QB-7K2M9) i broj mobitela s kojim ste "
                          "rezervirali.",
        "cancel_done": "Rezervacija {ref} ({when}) je otkazana.",
        "cancel_not_found": "Ne mogu pronaći aktivnu rezervaciju s tim brojem i telefonom. Proslijedio sam upit vlasniku.",
        "resched_ask_when": "Na koji dan i vrijeme želite pomaknuti rezervaciju {ref}?",
        "resched_done": "Rezervacija {ref} je pomaknuta na {when}. {status_note}",
        "status_pending_note": "Vlasnik još mora potvrditi novi termin.",
        "status_confirmed_note": "Termin je potvrđen.",
        "thanks": "Hvala vama! Ako trebate još nešto, slobodno pišite.",
        "hold_released": "U redu, taj termin više ne držim.",
        "anything_else": "Mogu li još nekako pomoći?",
        # outbound messages (outbox)
        "msg_confirmed": "{business}: vaš termin {when} je potvrđen ({ref}). Za promjene odgovorite na ovu poruku.",
        "msg_declined": "{business}: nažalost ne možemo potvrditi termin {when} ({ref}). Javite nam se za drugi termin.",
        "msg_cancelled": "{business}: rezervacija {ref} ({when}) je otkazana.",
        "msg_rescheduled": "{business}: rezervacija {ref} je pomaknuta na {when}.",
        "msg_reminder": "{business}: podsjetnik na vaš termin sutra, {when} ({ref}).",
        "msg_followup": "{business}: zanima li vas još termin za {service}? Slobodno odgovorite ili rezervirajte na našoj stranici.",
        "msg_owner_new": "Novi zahtjev {ref}: {service}, {when}, {name} {phone}. Potvrdite u administraciji.",
    },
    "en": {
        "greeting": "Hi! I'm the automated assistant for {business}. I can give you a price estimate and find a free "
                    "time; the owner confirms every booking.",
        "ask_service": "Which service do you need?",
        "ask_service_first": "Which service are you interested in?",
        "ask_size": "What kind of vehicle is it? ({options})",
        "ask_area": "Roughly how many square metres (m²) is the space?",
        "bad_area": "I can estimate areas between 10 and 1000 m². How many square metres is it?",
        "estimate": "{service}: about €{low}–{high} (an estimate; the owner confirms the final price after "
                    "inspection). It takes about {duration}.",
        "ask_when": "Which day and time suit you?",
        "offer": "Free times:\n{options}\nReply with a number (1–{n}) or name another day.",
        "offer_other_day": "There is no free time that day for this service. The nearest free times:\n{options}\n"
                           "Reply with a number (1–{n}) or name another day.",
        "no_slots": "Sorry, there is no free time for this service in the next {days} days. I've passed your request "
                    "to the owner, who will get back to you.",
        "closed_day": "We're closed that day.",
        "invalid_date": "That date doesn't exist. Could you write it again (e.g. 24 November)?",
        "past_date": "That date has already passed. Which other day suits you?",
        "invalid_time": "I didn't understand that time (e.g. 10:30 or 2pm). Which time suits you?",
        "held": "I'm holding {when} for you for the next {minutes} minutes. What's your name and mobile number?",
        "ask_name": "What's your name?",
        "ask_phone": "What's your mobile number (e.g. +385 91 234 5678)?",
        "bad_phone": "That number doesn't look right. Could you write it again (e.g. +385 91 234 5678)?",
        "ask_consent": "Would you like a reminder the day before? (yes/no)",
        "pending": "Thanks, {name}! Your request for {when} ({ref}) has been received but is NOT CONFIRMED YET. "
                   "The owner will confirm it and get back to you.",
        "confirmed_now": "Thanks, {name}! Your booking for {when} is confirmed. Reference: {ref}.",
        "slot_gone": "That time was just taken. Here are others:\n{options}\nReply with a number (1–{n}).",
        "hold_expired": "The hold on that time ran out. Let me check free times again.",
        "choose_number": "Please reply with one of the numbers shown (1–{n}) or name another day.",
        "unclear": "I'm not sure I understood. Could you tell me the service and a day that suits you?",
        "handoff": "I've passed your message to the owner, who will reply personally as soon as possible.",
        "paused": "Thanks for your message! The owner will reply personally.",
        "hours": "Opening hours: {hours}.",
        "location": "{location}",
        "cancel_ask_ref": "To cancel I need your booking reference (e.g. QB-7K2M9) and the mobile number you booked with.",
        "cancel_done": "Booking {ref} ({when}) has been cancelled.",
        "cancel_not_found": "I can't find an active booking with that reference and phone number. I've passed this to "
                            "the owner.",
        "resched_ask_when": "Which day and time would you like to move booking {ref} to?",
        "resched_done": "Booking {ref} has been moved to {when}. {status_note}",
        "status_pending_note": "The owner still has to confirm the new time.",
        "status_confirmed_note": "It is confirmed.",
        "thanks": "You're welcome! Write any time if you need anything else.",
        "hold_released": "OK, I've released that time.",
        "anything_else": "Is there anything else I can help with?",
        "msg_confirmed": "{business}: your booking for {when} is confirmed ({ref}). Reply to this message to change it.",
        "msg_declined": "{business}: sorry, we can't confirm {when} ({ref}). Please get in touch for another time.",
        "msg_cancelled": "{business}: booking {ref} ({when}) has been cancelled.",
        "msg_rescheduled": "{business}: booking {ref} has been moved to {when}.",
        "msg_reminder": "{business}: reminder of your booking tomorrow, {when} ({ref}).",
        "msg_followup": "{business}: are you still interested in {service}? Just reply or book on our website.",
        "msg_owner_new": "New request {ref}: {service}, {when}, {name} {phone}. Confirm it in the admin page.",
    },
}

DAY_NAMES = {"hr": ["ponedjeljak", "utorak", "srijeda", "četvrtak", "petak", "subota", "nedjelja"],
             "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]}
DAY_SHORT = {"hr": ["pon", "uto", "sri", "čet", "pet", "sub", "ned"], "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}


def t(cfg, lang: str, key: str, **kw) -> str:
    lang = lang if lang in TEXTS else "hr"
    over = (cfg.raw.get("texts", {}) if cfg else {}).get(lang, {})
    s = over.get(key) or TEXTS[lang][key]
    return s.format(**kw)


def when(cfg, start_utc: dt.datetime, lang: str) -> str:
    lt = start_utc.astimezone(cfg.tz)
    if lang == "en":
        return f"{DAY_NAMES['en'][lt.weekday()]} {lt.day} {lt.strftime('%B')} at {lt:%H:%M}"
    return f"{DAY_NAMES['hr'][lt.weekday()]} {lt.day}.{lt.month}. u {lt:%H:%M}"


def duration(minutes: int, lang: str) -> str:
    h, m = divmod(minutes, 60)
    return " ".join(x for x in (f"{h} h" if h else "", f"{m} min" if m else "") if x) or "0 min"


def hours_text(cfg, lang: str) -> str:
    parts = []
    from .config import DAYS
    for i, d in enumerate(DAYS):
        ivs = cfg.hours.get(d) or []
        label = DAY_SHORT[lang if lang in DAY_SHORT else "hr"][i]
        if ivs:
            parts.append(f"{label} " + ", ".join(f"{a:%H:%M}–{z:%H:%M}" for a, z in ivs))
        else:
            parts.append(f"{label} " + ("zatvoreno" if lang != "en" else "closed"))
    return "; ".join(parts)
