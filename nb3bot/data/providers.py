"""Minute-bar providers: Massive/Polygon REST (QQQ), ProjectX History API (MNQ), historical replay.

Only official, documented APIs are used:
  * Massive (formerly Polygon.io) aggregates: GET /v2/aggs/ticker/{T}/range/1/minute/{from_ms}/{to_ms}.
    The response `status` is "DELAYED" on plans without real-time data; the bot then treats QQQ as
    NOT real-time and will not trade on it. Bar `t` = bar start (ms since epoch, UTC).
  * ProjectX Gateway: POST /api/History/retrieveBars (unit 2 = minute, includePartialBar false,
    at most 20,000 bars, 50 requests / 30 s). The documentation does not state whether `t` is the bar
    start; the bot assumes it is (standard) and the practice-account checklist verifies it.
  * Alpaca Market Data: GET https://data.alpaca.markets/v2/stocks/{symbol}/bars (timeframe 1Min, feed
    iex|sip, start/end RFC-3339, limit <= 10,000, next_page_token paging; headers APCA-API-KEY-ID and
    APCA-API-SECRET-KEY; docs read 2026-11-17). Bar `t` is the LEFT edge of the minute. A minute with
    no trades has no bar. The free Basic plan has real-time IEX bars (one exchange, ~2.5% of volume)
    and consolidated SIP bars only when the requested end is at least 15 minutes old; 200 calls/min.
"""
from __future__ import annotations

import os
import time
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

    def __init__(self, name: str, sessions: list[Session], clock, scale: float = 1.0, tick: float | None = None):
        self.name = name
        self.realtime = True
        self.clock = clock
        self.scale = scale             # multiply prices (e.g. QQQ x 41.3 = synthetic MNQ for paper fills)
        self.tick = tick if scale != 1.0 else None   # synthetic prices are put on the contract's tick grid
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
                        k, tk = self.scale, self.tick
                        r = (lambda x: round(x * k / tk) * tk) if tk else (lambda x: x * k)
                        lo, hi = r(l), r(h)
                        oo, cc = min(max(r(o), lo), hi), min(max(r(c), lo), hi)
                        out.append(MinuteBar(ts, oo, hi, lo, cc, v))
            d += timedelta(days=1)
        return out


class AlpacaMinutes:
    """QQQ minute bars from Alpaca. Live (recent) requests use the real-time feed (IEX on the free plan);
    requests that end more than 16 minutes ago use the history feed (SIP = all exchanges, the same kind
    of data as the backtest). If the account may not use SIP history, it falls back to IEX and says so."""

    def __init__(self, symbol: str, api_base: str, key_id_env: str, secret_env: str, live_feed: str = "iex",
                 history_feed: str = "sip", session: requests.Session | None = None, timeout: float = 10.0, clock=None):
        self.symbol = symbol
        self.base = api_base.rstrip("/")
        self.key_id = os.environ.get(key_id_env, "")
        self.secret = os.environ.get(secret_env, "")
        self.key_names = (key_id_env, secret_env)
        self.live_feed, self.history_feed = live_feed, history_feed
        self.http = session or requests.Session()
        self.timeout = timeout
        self.clock = clock
        self.realtime = True
        self.notes: list[str] = []
        self._calls: list[float] = []
        self.name = f"alpaca:{symbol}:{live_feed}"

    def _now(self) -> datetime:
        return self.clock.now() if self.clock is not None else datetime.now(UTC)

    def _throttle(self) -> None:
        now = time.monotonic()
        self._calls = [t for t in self._calls if now - t < 60]
        if len(self._calls) >= 180:                     # free plan: 200 calls / minute
            time.sleep(max(0.0, 60 - (now - self._calls[0])))
        self._calls.append(time.monotonic())

    def feed_for(self, end: datetime) -> str:
        return self.history_feed if end <= self._now() - timedelta(minutes=16) else self.live_feed

    def fetch(self, start: datetime, end: datetime) -> list[MinuteBar]:
        if not self.key_id or not self.secret:
            raise ProviderError(f"Alpaca keys missing: set {self.key_names[0]} and {self.key_names[1]}")
        start, end = ensure_utc(start), ensure_utc(end)
        feed = self.feed_for(end)
        try:
            return self._fetch(start, end, feed)
        except ProviderError as e:
            if feed == "sip" and "403" in str(e):
                self.notes.append("SIP history not permitted for this account; using IEX history instead")
                self.history_feed = "iex"
                return self._fetch(start, end, "iex")
            raise

    def _fetch(self, start: datetime, end: datetime, feed: str) -> list[MinuteBar]:
        url = f"{self.base}/v2/stocks/{self.symbol}/bars"
        headers = {"APCA-API-KEY-ID": self.key_id, "APCA-API-SECRET-KEY": self.secret}
        params = {"timeframe": "1Min", "start": start.isoformat().replace("+00:00", "Z"),
                  "end": (end - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
                  "feed": feed, "limit": 10000, "adjustment": "raw", "sort": "asc"}
        out: list[MinuteBar] = []
        while True:
            self._throttle()
            try:
                r = self.http.get(url, params=params, headers=headers, timeout=self.timeout)
            except requests.RequestException as e:
                raise ProviderError(f"{self.name}: {e}") from e
            if r.status_code != 200:
                raise ProviderError(f"{self.name}: HTTP {r.status_code} {r.text[:200]}")
            j = r.json()
            for x in j.get("bars") or []:
                ts = datetime.fromisoformat(x["t"].replace("Z", "+00:00")).astimezone(UTC)
                if start <= ts < end:
                    out.append(MinuteBar(ts, float(x["o"]), float(x["h"]), float(x["l"]), float(x["c"]), float(x.get("v", 0))))
            tok = j.get("next_page_token")
            if not tok:
                break
            params = {**params, "page_token": tok}
        out.sort(key=lambda b: b.ts)
        return out


class SyntheticFutures:
    """SIMULATED futures prices for paper trading without a futures data licence:
    QQQ bar x ratio, rounded to the contract tick. Never used for real orders (config validation)."""

    def __init__(self, source, ratio: float, tick: float, symbol: str = "MNQ"):
        self.src, self.ratio, self.tick = source, ratio, tick
        self.name = f"synthetic:{symbol}=QQQx{ratio:g}"
        self.realtime = True

    def fetch(self, start: datetime, end: datetime) -> list[MinuteBar]:
        out = []
        for b in self.src.fetch(start, end):
            r = lambda x: round(x * self.ratio / self.tick) * self.tick
            lo, hi = r(b.l), r(b.h)
            out.append(MinuteBar(b.ts, min(max(r(b.o), lo), hi), hi, lo, min(max(r(b.c), lo), hi), b.v))
        self.realtime = getattr(self.src, "realtime", True)
        return out
