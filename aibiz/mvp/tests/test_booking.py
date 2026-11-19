import datetime as dt
import sqlite3
import threading
import unittest

from quotebook import availability as av
from quotebook import booking as bk
from quotebook.pricing import InvalidInfo, MissingInfo, estimate
from quotebook.timeutil import UTC, croatian_holidays, easter, to_iso
from tests.helpers import AppCase


class Holidays(unittest.TestCase):
    def test_easter_and_moving_holidays(self):
        self.assertEqual(easter(2026), dt.date(2026, 4, 5))
        self.assertEqual(easter(2027), dt.date(2027, 3, 28))
        h = croatian_holidays(2026)
        self.assertIn(dt.date(2026, 6, 4), h)       # Tijelovo = Easter + 60
        self.assertIn(dt.date(2026, 11, 18), h)
        self.assertEqual(len(h), 14)


class Pricing(AppCase):
    def test_vehicle_estimates(self):
        polish = self.cfg.get_service("polish")
        e = estimate(polish, "vehicle_size", "large", slot_step=30)
        self.assertEqual((e.low, e.high, e.minutes), (205.0, 315.0, 420))
        with self.assertRaises(MissingInfo):
            estimate(polish, "vehicle_size", "")
        with self.assertRaises(InvalidInfo):
            estimate(polish, "vehicle_size", "tank")


class PricingArea(AppCase):
    config = "demo_cleaning.json"

    def test_area_minimum_and_bounds(self):
        deep = self.cfg.get_service("deep")
        e = estimate(deep, "area_m2", area_m2=70, slot_step=60)
        self.assertEqual((e.low, e.high, e.minutes), (145.0, 205.0, 360))
        small = estimate(deep, "area_m2", area_m2=20, slot_step=60)
        self.assertGreaterEqual(small.low, 75.0)       # minimum price 90 minus 15%
        for bad in (5, 5000):
            with self.assertRaises(InvalidInfo):
                estimate(deep, "area_m2", area_m2=bad)
        win = estimate(self.cfg.get_service("windows"), "area_m2", slot_step=60)
        self.assertEqual(win.minutes, 120)


class Availability(AppCase):
    def wash(self):
        return self.cfg.get_service("wash")

    def test_opening_hours_notice_and_sunday(self):
        today = dt.date(2026, 11, 19)
        slots = av.day_slots(self.conn, self.cfg, self.wash(), 90, today, self.app.now())
        self.assertEqual(slots, [])                    # 12 h minimum notice from 09:00 leaves nothing today
        fri = av.day_slots(self.conn, self.cfg, self.wash(), 90, dt.date(2026, 11, 20), self.app.now())
        self.assertEqual(fri[0].start.astimezone(self.cfg.tz).time(), dt.time(8, 0))
        self.assertEqual(fri[-1].start.astimezone(self.cfg.tz).time(), dt.time(15, 30))   # ends 17:00
        self.assertEqual(av.day_slots(self.conn, self.cfg, self.wash(), 90, dt.date(2026, 11, 22), self.app.now()), [])

    def test_holidays_and_closed_dates(self):
        self.clock.t = dt.datetime(2026, 12, 20, 8, 0, tzinfo=UTC)
        for d in (dt.date(2026, 12, 24), dt.date(2026, 12, 25), dt.date(2026, 12, 26)):
            self.assertEqual(av.day_slots(self.conn, self.cfg, self.wash(), 90, d, self.app.now()), [])

    def test_job_longer_than_saturday_hours(self):
        polish = self.cfg.get_service("polish")
        self.assertEqual(av.day_slots(self.conn, self.cfg, polish, 420, dt.date(2026, 11, 21), self.app.now()), [])

    def test_dst_change_keeps_wall_clock_slots(self):
        self.clock.t = dt.datetime(2027, 3, 25, 8, 0, tzinfo=UTC)
        slots = av.day_slots(self.conn, self.cfg, self.wash(), 90, dt.date(2027, 3, 30), self.app.now())  # after DST (29th is Easter Monday)
        lt = slots[0].start.astimezone(self.cfg.tz)
        self.assertEqual((lt.hour, lt.minute, lt.utcoffset()), (8, 0, dt.timedelta(hours=2)))

    def test_buffer_and_blocks(self):
        start = self.local(2026, 11, 20, 10, 0)
        for rid in ("box1", "box2"):
            bk.owner_create(self.conn, self.cfg, self.wash(), start, 90, rid, self.app.now())
        slots = av.day_slots(self.conn, self.cfg, self.wash(), 90, dt.date(2026, 11, 20), self.app.now())
        times = [s.start.astimezone(self.cfg.tz).time() for s in slots]
        self.assertNotIn(dt.time(11, 30), times)       # the 10:00-11:30 jobs plus a 30 min buffer end at 12:00
        self.assertIn(dt.time(12, 0), times)
        self.assertNotIn(dt.time(8, 30), times)        # would end 10:00, inside the buffer before 10:00
        self.assertIn(dt.time(8, 0), times)            # ends 09:30, exactly where the buffer starts
        self.app.block_time(self.local(2026, 11, 20, 12, 0), self.local(2026, 11, 20, 17, 0), None, "servis opreme")
        slots = av.day_slots(self.conn, self.cfg, self.wash(), 90, dt.date(2026, 11, 20), self.app.now())
        self.assertTrue(all(s.end.astimezone(self.cfg.tz).time() <= dt.time(12, 0) for s in slots))

    def test_suggest_prefers_requested_time_and_spreads(self):
        s = av.suggest(self.conn, self.cfg, self.wash(), 90, self.app.now(), date=dt.date(2026, 11, 23),
                       time=dt.time(11, 0), n=3)
        times = [x.start.astimezone(self.cfg.tz).time() for x in s]
        self.assertIn(dt.time(11, 0), times)
        gaps = [(b.start - a.start).total_seconds() for a, b in zip(s, s[1:])]
        self.assertTrue(all(g >= 90 * 60 for g in gaps))


class Booking(AppCase):
    def slot(self, h, rid="box1", minutes=90, day=20):
        s = self.local(2026, 11, day, h).astimezone(UTC)
        return av.Slot(s, s + dt.timedelta(minutes=minutes), rid)

    def test_hold_is_idempotent_and_blocks_others(self):
        wash = self.cfg.get_service("wash")
        a = bk.hold(self.conn, self.cfg, wash, self.slot(10), self.app.now(), idempotency_key="k1")
        b = bk.hold(self.conn, self.cfg, wash, self.slot(10), self.app.now(), idempotency_key="k1")
        self.assertEqual(a["id"], b["id"])
        with self.assertRaises(bk.SlotTaken):
            bk.hold(self.conn, self.cfg, wash, self.slot(10), self.app.now(), idempotency_key="k2")
        with self.assertRaises(bk.SlotTaken):          # overlaps, including the 30 min buffer
            bk.hold(self.conn, self.cfg, wash, self.slot(11), self.app.now(), idempotency_key="k3")

    def test_expired_hold_frees_the_slot(self):
        wash = self.cfg.get_service("wash")
        h = bk.hold(self.conn, self.cfg, wash, self.slot(10), self.app.now(), idempotency_key="k1")
        self.clock.advance(minutes=21)
        b = bk.hold(self.conn, self.cfg, wash, self.slot(10), self.app.now(), idempotency_key="k2")
        self.assertNotEqual(h["id"], b["id"])
        with self.assertRaises(bk.HoldExpired):
            bk.submit(self.conn, self.cfg, h["id"], 1, self.app.now())

    def test_rejects_outside_hours_and_short_notice(self):
        wash = self.cfg.get_service("wash")
        with self.assertRaises(bk.OutsideHours):
            bk.hold(self.conn, self.cfg, wash, self.slot(16), self.app.now(), idempotency_key="late")   # ends 17:30
        with self.assertRaises(bk.OutsideHours):
            bk.hold(self.conn, self.cfg, wash, self.slot(10, day=22), self.app.now(), idempotency_key="sunday")
        s = self.app.now() + dt.timedelta(hours=3)
        with self.assertRaises(bk.SlotTaken):
            bk.hold(self.conn, self.cfg, wash, av.Slot(s, s + dt.timedelta(minutes=90), "box1"), self.app.now(),
                    idempotency_key="soon")

    def test_transitions(self):
        wash = self.cfg.get_service("wash")
        h = bk.hold(self.conn, self.cfg, wash, self.slot(10), self.app.now(), idempotency_key="k")
        cid = bk.upsert_customer(self.conn, "Ana", "+385990001000", "hr", self.app.now())
        b = bk.submit(self.conn, self.cfg, h["id"], cid, self.app.now())
        self.assertEqual(b["status"], "pending_owner")
        with self.assertRaises(bk.InvalidTransition):
            bk.complete(self.conn, b["id"], self.app.now())
        self.assertEqual(bk.confirm(self.conn, b["id"], self.app.now())["status"], "confirmed")
        self.assertEqual(bk.cancel(self.conn, b["id"], self.app.now())["status"], "cancelled")
        with self.assertRaises(bk.InvalidTransition):
            bk.confirm(self.conn, b["id"], self.app.now())

    def test_database_trigger_blocks_overlaps_from_any_code_path(self):
        ts = to_iso(self.app.now())
        sql = ("INSERT INTO bookings(ref, service_id, resource_id, start_utc, end_utc, status, created_at, updated_at) "
               "VALUES (?, 'wash', 'box1', ?, ?, 'confirmed', ?, ?)")
        self.conn.execute(sql, ("QB-AAAAA", "2026-11-20T09:00:00Z", "2026-11-20T10:30:00Z", ts, ts))
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(sql, ("QB-BBBBB", "2026-11-20T10:00:00Z", "2026-11-20T11:00:00Z", ts, ts))
        self.conn.execute(sql, ("QB-CCCCC", "2026-11-20T10:30:00Z", "2026-11-20T11:00:00Z", ts, ts))  # touching is fine
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE bookings SET start_utc = '2026-11-20T10:00:00Z' WHERE ref = 'QB-CCCCC'")

    def test_concurrent_holds_only_one_wins(self):
        wash = self.cfg.get_service("wash")
        results, errors = [], []
        barrier = threading.Barrier(8)

        def worker(i):
            conn = self.app.db.connect()
            try:
                barrier.wait()
                results.append(bk.hold(conn, self.cfg, wash, self.slot(10), self.app.now(), idempotency_key=f"t{i}")["id"])
            except bk.SlotTaken:
                errors.append(i)
            finally:
                conn.close()
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 7)
        n = self.conn.execute("SELECT COUNT(*) FROM bookings WHERE status = 'held'").fetchone()[0]
        self.assertEqual(n, 1)

    def test_reschedule_is_atomic(self):
        wash = self.cfg.get_service("wash")
        a = bk.owner_create(self.conn, self.cfg, wash, self.local(2026, 11, 20, 8), 90, "box1", self.app.now())
        bk.owner_create(self.conn, self.cfg, wash, self.local(2026, 11, 20, 13), 90, "box1", self.app.now())
        with self.assertRaises(bk.SlotTaken):
            bk.reschedule(self.conn, self.cfg, a["id"], self.slot(13), self.app.now())
        self.assertEqual(bk.get(self.conn, a["id"])["start_utc"], to_iso(self.local(2026, 11, 20, 8)))
        moved = bk.reschedule(self.conn, self.cfg, a["id"], self.slot(10), self.app.now(), actor="owner")
        self.assertEqual(moved["start_utc"], to_iso(self.local(2026, 11, 20, 10)))
        moved = bk.reschedule(self.conn, self.cfg, a["id"], self.slot(10, minutes=60), self.app.now(), actor="owner")
        self.assertEqual(moved["status"], "confirmed")   # moving onto its own old time is not a clash

    def test_owner_can_book_outside_hours_but_not_on_top(self):
        wash = self.cfg.get_service("wash")
        b = bk.owner_create(self.conn, self.cfg, wash, self.local(2026, 11, 22, 10), 90, "box1", self.app.now())
        self.assertEqual(b["status"], "confirmed")
        with self.assertRaises(bk.SlotTaken):
            bk.owner_create(self.conn, self.cfg, wash, self.local(2026, 11, 22, 11), 90, "box1", self.app.now())


if __name__ == "__main__":
    unittest.main()
