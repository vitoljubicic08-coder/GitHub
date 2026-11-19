import json
import unittest

from quotebook.assistant import RateLimited
from quotebook.transcripts import SCRIPTS, fresh_app, run_script
from tests.helpers import AppCase


class Flow(AppCase):
    def test_full_booking_never_claims_confirmed_before_owner(self):
        r = self.say("Bok, koliko košta poliranje za SUV?")
        self.assertIn("205–315 €", r["text"])
        self.assertIn("procjena", r["text"])
        self.assertEqual(r["step"], "offered")
        self.assertEqual(r["option_values"], ["1", "2", "3"])
        cid = r["conversation_id"]
        r = self.say("3", "Ivan Horvat", "091 234 5678", "da", cid=cid)   # Monday: far enough ahead for a reminder
        self.assertIn("JOŠ NIJE POTVRĐEN", r["text"])
        self.assertNotIn("je potvrđen", r["text"])
        b = self.conn.execute("SELECT * FROM bookings WHERE conversation_id = ?", (cid,)).fetchone()
        self.assertEqual(b["status"], "pending_owner")
        cust = self.conn.execute("SELECT * FROM customers WHERE id = ?", (b["customer_id"],)).fetchone()
        self.assertEqual((cust["phone"], cust["reminder_consent"]), ("+385912345678", 1))
        kinds = [x["kind"] for x in self.conn.execute("SELECT kind FROM outbox")]
        self.assertEqual(kinds, ["owner_new"])          # nothing goes to the customer until the owner confirms
        self.app.owner_confirm(b["id"])
        kinds = sorted(x["kind"] for x in self.conn.execute("SELECT kind FROM outbox"))
        self.assertEqual(kinds, ["confirmed", "owner_new", "reminder"])

    def test_auto_confirm_mode_says_confirmed_only_when_it_is(self):
        self.cfg.raw.setdefault("booking", {})["require_owner_confirmation"] = False
        cid, b = self.book_via_chat()
        self.assertEqual(b["status"], "confirmed")
        last = self.conn.execute("SELECT text FROM messages WHERE conversation_id = ? AND direction = 'out' "
                                 "ORDER BY id DESC", (cid,)).fetchone()["text"]
        self.assertIn("je potvrđen", last)

    def test_no_reminder_without_consent(self):
        cid, b = self.book_via_chat(consent="ne")
        self.app.owner_confirm(b["id"])
        kinds = [x["kind"] for x in self.conn.execute("SELECT kind FROM outbox")]
        self.assertNotIn("reminder", kinds)
        self.assertIn("confirmed", kinds)              # a confirmation of their own request is transactional

    def test_english(self):
        r = self.say("Hi, how much is a deep interior cleaning for a Golf? Friday afternoon would be ideal")
        self.assertIn("€90–130", r["text"])
        self.assertIn("Friday 20 November at 12:00", r["text"])
        r = self.say("2", "My name is Sarah Miller", "+385 98 765 4321", "no", cid=r["conversation_id"])
        self.assertIn("NOT CONFIRMED YET", r["text"])

    def test_bad_dates_and_times_are_questioned(self):
        r = self.say("Trebam pranje auta, karavan")
        cid = r["conversation_id"]
        self.assertIn("ne postoji", self.say("31.02. u 10", cid=cid)["text"])
        self.assertIn("već prošao", self.say("15.11.", cid=cid)["text"])
        self.assertIn("ne razumijem", self.say("u 25:00", cid=cid)["text"])
        self.assertIn("20.11. u 14:00", self.say("sutra u 14", cid=cid)["text"])

    def test_sunday_and_too_long_for_saturday(self):
        r = self.say("pranje za mali auto u nedjelju")
        self.assertIn("Taj dan ne radimo", r["text"])
        r = self.say("poliranje SUV subota")
        self.assertIn("Na taj dan nema slobodnog termina", r["text"])

    def test_slot_taken_between_offer_and_choice(self):
        lines, cid = run_script(self.app, SCRIPTS[1][2][:3])
        texts = [t for who, t in lines if who == "assistant"]
        self.assertIn("just taken", texts[1])
        held = self.conn.execute("SELECT COUNT(*) FROM bookings WHERE status = 'held'").fetchone()[0]
        self.assertEqual(held, 0)

    def test_duplicate_message_id_does_not_double_book(self):
        r = self.app.handle_message("Koliko košta keramička zaštita za mali auto?", None, "m-1")
        cid = r["conversation_id"]
        a = self.app.handle_message("1", cid, "m-2")
        b = self.app.handle_message("1", cid, "m-2")
        self.assertEqual(a["text"], b["text"])
        self.assertTrue(b.get("duplicate"))
        n = self.conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
        self.assertEqual(n, 1)

    def test_changing_slot_or_cancelling_during_contact_releases_the_hold(self):
        r = self.say("pranje mali auto ponedjeljak u 9")
        cid = r["conversation_id"]
        self.say("1", cid=cid)
        r = self.say("ipak utorak u 10", cid=cid)          # new time instead of a name
        self.assertIn("utorak 24.11.", r["text"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM bookings WHERE status = 'held'").fetchone()[0], 0)
        self.say("1", cid=cid)
        r = self.say("cancel", cid=cid)
        self.assertIn("više ne držim", r["text"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM bookings WHERE status = 'held'").fetchone()[0], 0)
        st = json.loads(self.conn.execute("SELECT state FROM conversations WHERE id = ?", (cid,)).fetchone()["state"])
        self.assertNotIn("name", st)

    def test_cleaning_area(self):
        app = fresh_app("demo_cleaning.json", clock=self.clock, tmp=self.tmp + "/c")
        r = app.handle_message("Dobar dan, trebam generalno čišćenje stana od 70 m2 iduće srijede")
        self.assertIn("145–205 €", r["text"])
        self.assertIn("srijeda 25.11.", r["text"])
        r = app.handle_message("trebam čišćenje nakon renovacije")
        self.assertIn("kvadrata", r["text"])
        r = app.handle_message("5000 m2", r["conversation_id"])
        self.assertIn("između 10 i 1000", r["text"])
        app.close_conn()


class Escalation(AppCase):
    def test_complaint(self):
        r = self.say("Jučer ste mi polirali auto i ima ogrebotine, nisam zadovoljan")
        self.assertIn("vlasniku", r["text"])
        self.assertEqual(r["step"], "handoff")
        e = self.conn.execute("SELECT * FROM escalations").fetchone()
        self.assertEqual(e["reason"], "complaint")
        r = self.say("halo?", cid=r["conversation_id"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM escalations").fetchone()[0], 1)
        self.assertIn("halo?", self.conn.execute("SELECT excerpt FROM escalations").fetchone()[0])

    def test_human_request_and_owner_resolves(self):
        r = self.say("Can someone call me please?")
        self.assertEqual(r["step"], "handoff")
        esc = self.conn.execute("SELECT id FROM escalations").fetchone()["id"]
        self.app.resolve_escalation(esc)
        st = json.loads(self.conn.execute("SELECT state FROM conversations").fetchone()["state"])
        self.assertEqual(st["step"], "start")

    def test_not_understood_three_times(self):
        r = self.say("asdf")
        cid = r["conversation_id"]
        self.say("hmm ?", cid=cid)
        r = self.say("???", cid=cid)
        self.assertEqual(r["step"], "handoff")

    def test_paused_assistant_forwards_everything(self):
        self.app.set_paused(True)
        r = self.say("Koliko košta pranje?")
        self.assertIn("Vlasnik će vam odgovoriti", r["text"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT reason FROM escalations").fetchone()[0], "automation_paused")

    def test_faq_answers(self):
        r = self.say("Koje je vaše radno vrijeme?")
        self.assertIn("pon 08:00–17:00", r["text"])
        self.assertIn("ned zatvoreno", r["text"])
        r = self.say("Where are you located?")
        self.assertIn("Demo ulica 1", r["text"])


class Manage(AppCase):
    def test_cancel_needs_matching_phone(self):
        cid, b = self.book_via_chat()
        self.app.owner_confirm(b["id"])
        r = self.say(f"Želim otkazati {b['ref']}, mob 091 999 9999")
        self.assertIn("Ne mogu pronaći", r["text"])
        self.assertEqual(self.conn.execute("SELECT status FROM bookings WHERE id = ?", (b["id"],)).fetchone()[0], "confirmed")
        r = self.say(f"Želim otkazati {b['ref']}, mob 099 000 1000")
        self.assertIn("je otkazana", r["text"])
        row = self.conn.execute("SELECT status FROM outbox WHERE kind = 'reminder'").fetchone()
        self.assertEqual(row["status"], "skipped")

    def test_cancel_from_same_conversation(self):
        cid, b = self.book_via_chat()
        r = self.say("ipak moram otkazati", cid=cid)
        self.assertIn("je otkazana", r["text"])

    def test_reschedule(self):
        cid, b = self.book_via_chat()
        self.app.owner_confirm(b["id"])
        r = self.say(f"Trebam pomaknuti termin {b['ref']}, broj 099 000 1000")
        self.assertIn("pomaknuti rezervaciju", r["text"])
        r = self.say("utorak u 13", cid=r["conversation_id"])
        self.assertIn("utorak 24.11.", r["text"])
        r = self.say("2", cid=r["conversation_id"])
        self.assertIn("pomaknuta na utorak 24.11. u 13:00", r["text"])
        row = self.conn.execute("SELECT * FROM bookings WHERE id = ?", (b["id"],)).fetchone()
        self.assertEqual(row["status"], "pending_owner")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM bookings WHERE status IN "
                                           "('pending_owner','confirmed','held')").fetchone()[0], 1)


class InputLimits(AppCase):
    def test_validation_and_rate_limit(self):
        for bad in ("", "   ", "x" * 1001, None, 42):
            with self.assertRaises(ValueError):
                self.app.handle_message(bad)
        r = self.say("bok")
        cid = r["conversation_id"]
        with self.assertRaises(RateLimited):
            for _ in range(20):
                self.app.handle_message("bok", cid)

    def test_transcript_scripts_run(self):
        for title, cfg, msgs in SCRIPTS:
            app = fresh_app(cfg, clock=self.clock, tmp=f"{self.tmp}/{abs(hash(title))}")
            lines, _ = run_script(app, msgs)
            self.assertTrue(lines, title)
            app.close_conn()


if __name__ == "__main__":
    unittest.main()
