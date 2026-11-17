"""Minute-bar providers: Massive/Polygon REST (QQQ), ProjectX History API (MNQ), historical replay.

Only official, documented APIs are used:
  * Massive (formerly Polygon.io) aggregates: GET /v2/aggs/ticker/{T}/range/1/minute/{from_ms}/{to_ms}.
    The response `status` is "DELAYED" on plans without real-time data; the bot then treats QQQ as
    NOT real-time and will not trade on it. Bar `t` = bar start (ms since epoch, UTC).
  * ProjectX Gateway: POST /api/History/retrieveBars (unit 2 = minute, includePartialBar false,
    at most 20,000 bars, 50 requests / 30 s). The documentation does not state whether `t` is the bar
    start; the bot assumes it is (standard) and the practice-account checklist verifies it.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import requests

from nb3bot.data.base import MinuteBar, ensure_utc
from nb3bot.replay.data import Session
from nb3bot.timeutil import UTC, minute_start


class ProviderError(RuntimeError):
    pass


class MassiveMinutes:
    def __init__(self, ticker: str, api_base: str, api_key_env: str, session: requests.Session | None = None,
                 timeout: float = 10.0):
        self.name = f"massive:{ticker}"
        self.ticker = ticker
        self.base = api_base.rstrip("/")
        self.key = os.environ.get(api_key_env, "")
        self.http = session or requests.Session()
        self.timeout = timeout
        self.realtime = True

    def fetch(self, start: datetime, end: datetime) -> list[MinuteBar]:
        start, end = ensure_utc(start), ensure_utc(end)
        url = (f"{self.base}/v2/aggs/ticker/{self.ticker}/range/1/minute/"
               f"{int(start.timestamp() * 1000)}/{int(end.timestamp() * 1000) - 1}")
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        out: list[MinuteBar] = []
        params = {"adjusted": "true", "sort": "asc", "limit": 50000}
        while url:
            try:
                r = self.http.get(url, params=params, headers=headers, timeout=self.timeout)
            except requests.RequestException as e:
                raise ProviderError(f"{self.name}: {e}") from e
            if r.status_code != 200:
                raise ProviderError(f"{self.name}: HTTP {r.status_code} {r.text[:200]}")
            j = r.json()
            self.realtime = j.get("status") != "DELAYED"
            for x in j.get("results") or []:
                ts = datetime.fromtimestamp(x["t"] / 1000, UTC)
                if start <= ts < end:
                    out.append(MinuteBar(ts, float(x["o"]), float(x["h"]), float(x["l"]), float(x["c"]), float(x.get("v", 0))))
            url, params = j.get("next_url"), None
        out.sort(key=lambda b: b.ts)
        return out


class ProjectXMinutes:
    def __init__(self, client, contract_id: str, live: bool = False):
        self.name = f"projectx:{contract_id}"
        self.client = client
        self.contract_id = contract_id
        self.live = live
        self.realtime = True

    def fetch(self, start: datetime, end: datetime) -> list[MinuteBar]:
        start, end = ensure_utc(start), ensure_utc(end)
        out: dict[datetime, MinuteBar] = {}
        cur = start
        while cur < end:
            chunk_end = min(end, cur + timedelta(minutes=19000))
            bars = self.client.retrieve_bars(self.contract_id, cur, chunk_end, unit=2, unit_number=1,
                                             limit=20000, live=self.live, include_partial=False)
            for x in bars:
                ts = datetime.fromisoformat(x["t"]).astimezone(UTC)
                if start <= ts < end:
                    out[ts] = MinuteBar(ts, float(x["o"]), float(x["h"]), float(x["l"]), float(x["c"]), float(x.get("v", 0)))
            cur = chunk_end
        return [out[k] for k in sorted(out)]


class ReplayMinutes:
    """Serves historical sessions as if live: only bars that have finished by the clock's time."""

    def __init__(self, name: str, sessions: list[Session], clock, scale: float = 1.0):
        self.name = name
        self.realtime = True
        self.clock = clock
        self.scale = scale             # multiply prices (e.g. QQQ x 41.3 = synthetic MNQ for paper fills)
        self.by_key = {s.key: s for s in sessions}

    def fetch(self, start: datetime, end: datetime) -> list[MinuteBar]:
        start, end = ensure_utc(start), ensure_utc(end)
        now = self.clock.now()
        out = []
        d = start.date() - timedelta(days=1)
        while d <= end.date():
            s = self.by_key.get(d.year * 10000 + d.month * 100 + d.day)
            if s is not None:
                for m, o, h, l, c, v in s.minutes():
                    ts = minute_start(s.key, m)
                    if start <= ts < end and ts + timedelta(minutes=1) <= now:
                        k = self.scale
                        out.append(MinuteBar(ts, o * k, h * k, l * k, c * k, v))
            d += timedelta(days=1)
        return out
