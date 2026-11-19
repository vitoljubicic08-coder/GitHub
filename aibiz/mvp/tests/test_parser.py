import datetime as dt
import unittest

from quotebook.config import load_config
from quotebook.parser import detect_language, fold, normalize_phone, parse
from tests.helpers import ROOT

CFG = load_config(ROOT / "config" / "demo_detailing.json")
CLEAN = load_config(ROOT / "config" / "demo_cleaning.json")
TODAY = dt.date(2026, 11, 19)   # Thursday


def P(text, cfg=CFG, offered=0):
    return parse(text, today=TODAY, services=cfg.services, sizes=cfg.sizes, offered=offered)


class Language(unittest.TestCase):
    def test_croatian_and_english(self):
        self.assertEqual(detect_language("Koliko košta poliranje?"), "hr")
        self.assertEqual(detect_language("koliko kosta poliranje"), "hr")
        self.assertEqual(detect_language("How much is a polish for my car?"), "en")
        self.assertEqual(detect_language("ok", default="en"), "en")

    def test_fold(self):
        self.assertEqual(fold("Četvrtak ŠĐŽĆ"), "cetvrtak sdzc")


class Dates(unittest.TestCase):
    def test_relative(self):
        self.assertEqual(P("sutra").date, dt.date(2026, 11, 20))
        self.assertEqual(P("prekosutra u 10").date, dt.date(2026, 11, 21))
        self.assertEqual(P("tomorrow at 3pm").date, dt.date(2026, 11, 20))
        self.assertEqual(P("danas").date, TODAY)

    def test_weekdays_in_croatian_cases(self):
        self.assertEqual(P("u subotu").date, dt.date(2026, 11, 21))
        self.assertEqual(P("iduće srijede").date, dt.date(2026, 11, 25))
        self.assertEqual(P("ponedjeljak").date, dt.date(2026, 11, 23))
        self.assertEqual(P("on Friday").date, dt.date(2026, 11, 20))
        self.assertEqual(P("u četvrtak").date, dt.date(2026, 11, 26))   # today is Thursday -> next week

    def test_numeric_and_month_names(self):
        self.assertEqual(P("24.11.").date, dt.date(2026, 11, 24))
        self.assertEqual(P("24. 11. 2026.").date, dt.date(2026, 11, 24))
        self.assertEqual(P("3.12. u 10").date, dt.date(2026, 12, 3))
        self.assertEqual(P("5. siječnja").date, dt.date(2027, 1, 5))      # rolls to next year
        self.assertEqual(P("December 3rd").date, dt.date(2026, 12, 3))
        self.assertEqual(P("2026-12-01").date, dt.date(2026, 12, 1))

    def test_invalid_and_past(self):
        self.assertEqual(P("31.02.").date_error, "invalid_date")
        self.assertEqual(P("32.11.").date_error, "invalid_date")
        self.assertEqual(P("15.11.").date_error, "past_date")
        self.assertEqual(P("1.1.2020").date_error, "past_date")


class Times(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(P("u 10").time, dt.time(10, 0))
        self.assertEqual(P("10:30").time, dt.time(10, 30))
        self.assertEqual(P("oko 14h").time, dt.time(14, 0))
        self.assertEqual(P("at 3pm").time, dt.time(15, 0))
        self.assertEqual(P("u 3").time, dt.time(15, 0))          # afternoon assumption for 1-6
        self.assertEqual(P("sutra u 9").time, dt.time(9, 0))

    def test_windows(self):
        self.assertEqual(P("subota ujutro").window, (8, 12))
        self.assertEqual(P("Friday afternoon").window, (12, 17))

    def test_invalid(self):
        self.assertEqual(P("u 25:00").time_error, "invalid_time")
        self.assertEqual(P("at 13pm").time_error, "invalid_time")

    def test_numbers_that_are_not_times(self):
        p = P("generalno čišćenje 70 m2", cfg=CLEAN)
        self.assertIsNone(p.time)
        self.assertEqual(p.area_m2, 70)


class Entities(unittest.TestCase):
    def test_services_and_sizes(self):
        p = P("Koliko košta poliranje za SUV?")
        self.assertEqual((p.service_id, p.size), ("polish", "large"))
        self.assertIn("quote", p.intents)
        self.assertEqual(P("ceramic coating for my Golf").service_id, "ceramic")
        self.assertEqual(P("ceramic coating for my Golf").size, "medium")
        self.assertEqual(P("trebam kombi oprati").size, "van")
        self.assertEqual(P("dubinsko čišćenje 85 kvadrata", cfg=CLEAN).service_id, "deep")

    def test_phone(self):
        self.assertEqual(normalize_phone("091 234 5678"), "+385912345678")
        self.assertEqual(normalize_phone("+385 98 765 4321"), "+385987654321")
        self.assertEqual(normalize_phone("00385 1 2345 678"), "+38512345678")
        self.assertEqual(normalize_phone("12"), "")
        self.assertEqual(P("moj broj je 091/234-5678").phone, "+385912345678")
        self.assertEqual(P("091 23").phone, "")

    def test_name_email_ref(self):
        self.assertEqual(P("Zovem se Maja Kovač").name, "Maja Kovač")
        self.assertEqual(P("My name is Sarah Miller").name, "Sarah Miller")
        self.assertEqual(P("pišite na maja@example.invalid").email, "maja@example.invalid")
        self.assertEqual(P("otkazujem QB-7K2M9").ref, "QB-7K2M9")

    def test_intents(self):
        self.assertIn("complaint", P("Nisam zadovoljan, auto je oštećen").intents)
        self.assertIn("human", P("Možete li me nazvati, želim razgovarati s nekim").intents)
        self.assertIn("cancel", P("Želim otkazati termin").intents)
        self.assertIn("reschedule", P("can I reschedule my booking").intents)
        self.assertIn("yes", P("da").intents)
        self.assertIn("no", P("ne hvala").intents)
        self.assertNotIn("yes", P("ne").intents)

    def test_choice(self):
        self.assertEqual(P("2", offered=3).choice, 2)
        self.assertEqual(P("drugi", offered=3).choice, 2)
        self.assertEqual(P("4", offered=3).choice, 0)
        self.assertEqual(P("2", offered=0).choice, 0)


if __name__ == "__main__":
    unittest.main()
