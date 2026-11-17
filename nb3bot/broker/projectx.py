"""ProjectX Gateway API adapter (TopstepX and other ProjectX-based firms).

Implemented from the official documentation at gateway.docs.projectx.com (read 2026-11-17):
  auth        POST /api/Auth/loginKey {userName, apiKey} -> token (24 h); POST /api/Auth/validate -> newToken
  accounts    POST /api/Account/search {onlyActiveAccounts}
  contracts   POST /api/Contract/search {searchText, live}; /api/Contract/available {live}
  bars        POST /api/History/retrieveBars (unit 2 = minute; <= 20,000 bars; 50 requests / 30 s)
  orders      POST /api/Order/place {accountId, contractId, type, side, size, customTag,
                    stopLossBracket{ticks,type}, takeProfitBracket{ticks,type}}
              type 1 Limit, 2 Market, 4 Stop; side 0 buy (bid), 1 sell (ask);
              customTag must be unique across the account (used here as the idempotency key);
              brackets need the account in "Auto OCO Brackets" mode, otherwise errorCode 2.
              POST /api/Order/search {accountId, startTimestamp}, /api/Order/searchOpen, /api/Order/cancel
  positions   POST /api/Position/searchOpen, /api/Position/closeContract
  trades      POST /api/Trade/search (opening legs have profitAndLoss null; voided legs are ignored)
  status      OrderStatus 1 Open, 2 Filled, 3 Cancelled, 4 Expired, 5 Rejected, 6 Pending
  rate limits 200 requests / 60 s (all other endpoints); HTTP 429 when exceeded
Cancellation and closing through this API are documented as supported for simulated accounts
(evaluations and funded accounts at these firms are simulated). Order placement is never retried
automatically: on a timeout the order is looked up by its customTag.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta

import requests

from nb3bot.broker.base import (AccountInfo, BracketEntry, Broker, BrokerError, BrokerUnavailable, ContractInfo,
                                FillInfo, OrderInfo, PositionInfo, UncertainOrderState)
from nb3bot.timeutil import UTC

TYPE = {1: "limit", 2: "market", 3: "stop_limit", 4: "stop", 5: "trailing", 6: "join_bid", 7: "join_ask"}
STATUS = {0: "none", 1: "open", 2: "filled", 3: "cancelled", 4: "expired", 5: "rejected", 6: "pending"}
SAFE_PATHS = ("/api/Account/search", "/api/Contract/search", "/api/Contract/available", "/api/Contract/searchById",
              "/api/History/retrieveBars", "/api/Order/search", "/api/Order/searchOpen", "/api/Position/searchOpen",
              "/api/Trade/search", "/api/Auth/validate")


def _iso(ts: datetime) -> str:
    return ts.astimezone(UTC).isoformat()


def _ts(x: str | None) -> datetime | None:
    return datetime.fromisoformat(x).astimezone(UTC) if x else None


class ProjectXClient:
    def __init__(self, api_base: str, username: str, api_key: str, session: requests.Session | None = None,
                 timeout: float = 8.0):
        self.base = api_base.rstrip("/")
        self.username = username
        self.api_key = api_key
        self.http = session or requests.Session()
        self.timeout = timeout
        self.token: str | None = None
        self.token_time = 0.0
        self.calls: list[float] = []

    @classmethod
    def from_env(cls, cfg) -> "ProjectXClient":
        u, k = os.environ.get(cfg.username_env, ""), os.environ.get(cfg.api_key_env, "")
        if not u or not k:
            raise BrokerUnavailable(f"set the environment variables {cfg.username_env} and {cfg.api_key_env} "
                                    "(never put the API key in the config file)")
        return cls(cfg.api_base, u, k)

    # ------------------------------------------------------------------ transport
    def _throttle(self) -> None:
        now = time.monotonic()
        self.calls = [t for t in self.calls if now - t < 60]
        if len(self.calls) >= 180:                       # stay under the documented 200 / 60 s
            time.sleep(max(0.0, 60 - (now - self.calls[0])))
        self.calls.append(time.monotonic())

    def login(self) -> None:
        try:
            r = self.http.post(f"{self.base}/api/Auth/loginKey", json={"userName": self.username, "apiKey": self.api_key},
                               timeout=self.timeout)
        except requests.RequestException as e:
            raise BrokerUnavailable(f"login failed: {e}") from e
        j = r.json() if r.status_code == 200 else {}
        if not j.get("success") or not j.get("token"):
            raise BrokerUnavailable(f"login refused: HTTP {r.status_code}, errorCode {j.get('errorCode')} {j.get('errorMessage')}")
        self.token, self.token_time = j["token"], time.time()

    def _ensure_token(self) -> None:
        if self.token is None:
            self.login()
        elif time.time() - self.token_time > 20 * 3600:          # tokens last 24 h; refresh early
            try:
                j = self.post("/api/Auth/validate", {}, _refreshing=True)
                if j.get("newToken"):
                    self.token, self.token_time = j["newToken"], time.time()
            except BrokerError:
                self.login()

    def post(self, path: str, body: dict, _refreshing: bool = False) -> dict:
        if not _refreshing:
            self._ensure_token()
        safe = path in SAFE_PATHS
        for attempt in range(4 if safe else 1):
            self._throttle()
            try:
                r = self.http.post(f"{self.base}{path}", json=body, timeout=self.timeout,
                                   headers={"Authorization": f"Bearer {self.token}", "accept": "text/plain"})
            except requests.RequestException as e:
                if safe and attempt < 3:
                    time.sleep(0.5 * 2 ** attempt)
                    continue
                if safe:
                    raise BrokerUnavailable(f"{path}: {e}") from e
                raise UncertainOrderState(f"{path}: no reliable answer ({e}); look the order up before doing anything else") from e
            if r.status_code == 401 and not _refreshing:
                self.login()
                if safe:
                    continue
                raise UncertainOrderState(f"{path}: HTTP 401 (token expired); verify order state before retrying")
            if r.status_code == 429:
                if safe and attempt < 3:
                    time.sleep(2 * 2 ** attempt)
                    continue
                raise BrokerError(f"{path}: rate limited (HTTP 429)")
            if r.status_code >= 500:
                if safe and attempt < 3:
                    time.sleep(0.5 * 2 ** attempt)
                    continue
                if safe:
                    raise BrokerUnavailable(f"{path}: HTTP {r.status_code}")
                raise UncertainOrderState(f"{path}: HTTP {r.status_code}; verify order state")
            if r.status_code != 200:
                raise BrokerError(f"{path}: HTTP {r.status_code} {r.text[:200]}")
            return r.json()
        raise BrokerUnavailable(f"{path}: retries exhausted")

    @staticmethod
    def check(j: dict, what: str) -> dict:
        if not j.get("success", False):
            raise BrokerError(f"{what}: errorCode {j.get('errorCode')} {j.get('errorMessage')}")
        return j

    # ------------------------------------------------------------------ endpoints
    def accounts(self, only_active: bool = True) -> list[dict]:
        return self.check(self.post("/api/Account/search", {"onlyActiveAccounts": only_active}), "Account/search")["accounts"]

    def search_contracts(self, text: str, live: bool) -> list[dict]:
        return self.check(self.post("/api/Contract/search", {"searchText": text, "live": live}), "Contract/search")["contracts"]

    def retrieve_bars(self, contract_id: str, start: datetime, end: datetime, unit: int, unit_number: int,
                      limit: int, live: bool, include_partial: bool) -> list[dict]:
        j = self.post("/api/History/retrieveBars", {"contractId": contract_id, "live": live, "startTime": _iso(start),
                                                    "endTime": _iso(end), "unit": unit, "unitNumber": unit_number,
                                                    "limit": limit, "includePartialBar": include_partial})
        return self.check(j, "History/retrieveBars")["bars"] or []


class ProjectXBroker(Broker):
    name = "projectx"
    places_real_orders = True

    def __init__(self, client: ProjectXClient, account_id: int, live_data: bool = False):
        self.cl = client
        self.account_id = account_id
        self.live_data = live_data

    def connect(self) -> None:
        self.cl.login()
        ids = [a["id"] for a in self.cl.accounts(True)]
        if self.account_id not in ids:
            raise BrokerUnavailable(f"account {self.account_id} not among active accounts {ids}")

    def account(self) -> AccountInfo:
        for a in self.cl.accounts(True):
            if a["id"] == self.account_id:
                return AccountInfo(a["id"], a.get("name", ""), float(a.get("balance", 0.0)), bool(a.get("canTrade")),
                                   a.get("simulated"))
        raise BrokerUnavailable(f"account {self.account_id} not found")

    def contracts(self, search: str) -> list[ContractInfo]:
        return [ContractInfo(c["id"], c.get("name", ""), float(c["tickSize"]), float(c["tickValue"]),
                             bool(c.get("activeContract"))) for c in self.cl.search_contracts(search, self.live_data)]

    def place_bracket_entry(self, req: BracketEntry) -> str:
        body = {"accountId": self.account_id, "contractId": req.contract_id, "type": 2,
                "side": 0 if req.side > 0 else 1, "size": int(req.size), "limitPrice": None, "stopPrice": None,
                "trailPrice": None, "customTag": req.tag,
                "stopLossBracket": {"ticks": int(req.stop_ticks), "type": 4},
                "takeProfitBracket": {"ticks": int(req.target_ticks), "type": 1}}
        j = self.cl.post("/api/Order/place", body)
        if not j.get("success"):
            raise BrokerError(f"entry rejected: errorCode {j.get('errorCode')} {j.get('errorMessage')} "
                              f"(order id {j.get('orderId')})")
        return str(j["orderId"])

    def place_stop(self, contract_id: str, side: int, size: int, stop_price: float, tag: str) -> str:
        body = {"accountId": self.account_id, "contractId": contract_id, "type": 4, "side": 0 if side > 0 else 1,
                "size": int(size), "limitPrice": None, "stopPrice": stop_price, "trailPrice": None, "customTag": tag,
                "stopLossBracket": None, "takeProfitBracket": None}
        j = self.cl.post("/api/Order/place", body)
        if not j.get("success"):
            raise BrokerError(f"stop rejected: errorCode {j.get('errorCode')} {j.get('errorMessage')}")
        return str(j["orderId"])

    def place_limit(self, contract_id: str, side: int, size: int, limit_price: float, tag: str) -> str:
        body = {"accountId": self.account_id, "contractId": contract_id, "type": 1, "side": 0 if side > 0 else 1,
                "size": int(size), "limitPrice": limit_price, "stopPrice": None, "trailPrice": None, "customTag": tag,
                "stopLossBracket": None, "takeProfitBracket": None}
        j = self.cl.post("/api/Order/place", body)
        if not j.get("success"):
            raise BrokerError(f"limit rejected: errorCode {j.get('errorCode')} {j.get('errorMessage')}")
        return str(j["orderId"])

    @staticmethod
    def _order(o: dict) -> OrderInfo:
        return OrderInfo(str(o["id"]), o.get("customTag"), o["contractId"], STATUS.get(o.get("status"), "other"),
                         TYPE.get(o.get("type"), "other"), 1 if o.get("side") == 0 else -1, int(o.get("size", 0)),
                         int(o.get("fillVolume") or 0), o.get("filledPrice"), o.get("limitPrice"), o.get("stopPrice"),
                         _ts(o.get("creationTimestamp")))

    def _search(self, since: datetime) -> list[OrderInfo]:
        j = self.cl.check(self.cl.post("/api/Order/search", {"accountId": self.account_id,
                                                              "startTimestamp": _iso(since - timedelta(minutes=1))}),
                          "Order/search")
        return [self._order(o) for o in j.get("orders") or []]

    def find_order_by_tag(self, tag: str, since: datetime) -> OrderInfo | None:
        for o in self._search(since):
            if o.tag == tag:
                return o
        return None

    def order(self, order_id: str, since: datetime) -> OrderInfo | None:
        for o in self._search(since):
            if o.id == order_id:
                return o
        return None

    def open_orders(self) -> list[OrderInfo]:
        j = self.cl.check(self.cl.post("/api/Order/searchOpen", {"accountId": self.account_id}), "Order/searchOpen")
        return [self._order(o) for o in j.get("orders") or []]

    def positions(self) -> list[PositionInfo]:
        j = self.cl.check(self.cl.post("/api/Position/searchOpen", {"accountId": self.account_id}), "Position/searchOpen")
        out = []
        for p in j.get("positions") or []:
            sign = 1 if p.get("type") == 1 else -1
            out.append(PositionInfo(p["contractId"], sign * int(p.get("size", 0)), float(p.get("averagePrice", 0.0))))
        return out

    def cancel(self, order_id: str) -> None:
        j = self.cl.post("/api/Order/cancel", {"accountId": self.account_id, "orderId": int(order_id)})
        if not j.get("success"):
            raise BrokerError(f"cancel {order_id}: errorCode {j.get('errorCode')} {j.get('errorMessage')}")

    def close_position(self, contract_id: str) -> None:
        j = self.cl.post("/api/Position/closeContract", {"accountId": self.account_id, "contractId": contract_id})
        if not j.get("success"):
            raise BrokerError(f"close {contract_id}: errorCode {j.get('errorCode')} {j.get('errorMessage')}")

    def fills(self, since: datetime) -> list[FillInfo]:
        j = self.cl.check(self.cl.post("/api/Trade/search", {"accountId": self.account_id, "startTimestamp": _iso(since)}),
                          "Trade/search")
        out = []
        for t in j.get("trades") or []:
            out.append(FillInfo(str(t.get("orderId")), t["contractId"], 1 if t.get("side") == 0 else -1, int(t.get("size", 0)),
                                float(t["price"]), t.get("profitAndLoss"), float(t.get("fees") or 0) + float(t.get("commissions") or 0),
                                _ts(t.get("creationTimestamp")), bool(t.get("voided"))))
        return out
