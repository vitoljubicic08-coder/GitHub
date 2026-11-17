"""Paper broker: simulated fills on real (or replayed) futures minute bars. Never sends anything out.

Fill rules are the backtest's (see strategy/bracket.py):
  * market entry: open of the first minute bar starting at/after the order time, +/- slippage ticks;
  * protective stop (stop-market) and take-profit (limit) are attached as an OCO pair on the fill;
    stop checked first, gap-through fills at the bar open, no target fill in the entry minute;
  * flatten (close_position): last completed minute close +/- slippage (the backtest's 15:55 rule);
  * commission per contract per side.
Optional failure injection lets the tests rehearse rejections, lost acknowledgements and missing stops.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from nb3bot.broker.base import (AccountInfo, BracketEntry, Broker, BrokerError, ContractInfo, FillInfo, OrderInfo,
                                PositionInfo, UncertainOrderState)
from nb3bot.data.base import MinuteBar


@dataclass
class _Order:
    info: OrderInfo
    oco: str | None = None
    entry_bracket: tuple[int, int] | None = None   # (stop_ticks, target_ticks) to attach on fill
    placed: datetime | None = None
    entry_minute: datetime | None = None


@dataclass
class _Pos:
    size: int = 0
    avg: float = 0.0
    opened_minute: datetime | None = None


class PaperBroker(Broker):
    name = "paper"
    places_real_orders = False

    def __init__(self, contract: ContractInfo, starting_balance: float, slip_ticks: float = 1.0,
                 commission_per_side: float = 0.61, clock=None):
        self.c = contract
        self.balance = starting_balance
        self.slip = slip_ticks * contract.tick_size
        self.comm = commission_per_side
        self.clock = clock
        self.orders: dict[str, _Order] = {}
        self.pos = _Pos()
        self._fills: list[FillInfo] = []
        self._ids = itertools.count(1)
        self.tags: set[str] = set()
        self.last_bar: MinuteBar | None = None
        self.connected = True
        self.fail_next: str | None = None     # 'reject' | 'uncertain' | 'no_brackets' | 'down'

    # ------------------------------------------------------------------ helpers
    def _now(self) -> datetime:
        return self.clock.now()

    def _need(self) -> None:
        if not self.connected:
            raise UncertainOrderState("paper broker disconnected (simulated)")

    def _new_order(self, tag, typ, side, size, stop=None, limit=None, oco=None, bracket=None) -> _Order:
        oid = str(next(self._ids))
        o = _Order(OrderInfo(oid, tag, self.c.id, "open", typ, side, size, 0, None, limit, stop, self._now()),
                   oco=oco, entry_bracket=bracket, placed=self._now())
        self.orders[oid] = o
        return o

    def _fill(self, o: _Order, price: float, ts: datetime) -> None:
        info = o.info
        info.status, info.filled_size, info.fill_price = "filled", info.size, price
        pnl = None
        signed = info.side * info.size
        if self.pos.size == 0 or (self.pos.size > 0) == (signed > 0):
            new = self.pos.size + signed
            self.pos.avg = (self.pos.avg * abs(self.pos.size) + price * abs(signed)) / abs(new)
            self.pos.size = new
            self.pos.opened_minute = ts
        else:
            closed = min(abs(signed), abs(self.pos.size))
            direction = 1 if self.pos.size > 0 else -1
            pnl = direction * (price - self.pos.avg) * closed * self.c.tick_value / self.c.tick_size
            self.pos.size += signed
            if self.pos.size == 0:
                self.pos.avg = 0.0
        fees = self.comm * info.size
        self.balance += (pnl or 0.0) - fees
        self._fills.append(FillInfo(info.id, self.c.id, info.side, info.size, price, pnl, fees, ts))
        if o.oco:
            for other in self.orders.values():
                if other.oco == o.oco and other is not o and other.info.status == "open":
                    other.info.status = "cancelled"

    # ------------------------------------------------------------------ Broker API
    def connect(self) -> None:
        self.connected = True

    def account(self) -> AccountInfo:
        self._need()
        return AccountInfo(0, "PAPER", self.balance, True, True)

    def contracts(self, search: str) -> list[ContractInfo]:
        return [self.c]

    def place_bracket_entry(self, req: BracketEntry) -> str:
        self._need()
        if req.tag in self.tags:
            raise BrokerError(f"duplicate customTag {req.tag}")
        mode, self.fail_next = self.fail_next, None
        if mode == "reject":
            raise BrokerError("order rejected (simulated)")
        self.tags.add(req.tag)
        bracket = None if mode == "no_brackets" else (req.stop_ticks, req.target_ticks)
        o = self._new_order(req.tag, "market", req.side, req.size, bracket=bracket)
        if mode == "uncertain":
            raise UncertainOrderState("acknowledgement lost (simulated)")
        return o.info.id

    def place_stop(self, contract_id: str, side: int, size: int, stop_price: float, tag: str) -> str:
        self._need()
        if tag in self.tags:
            raise BrokerError(f"duplicate customTag {tag}")
        self.tags.add(tag)
        return self._new_order(tag, "stop", side, size, stop=stop_price).info.id

    def place_limit(self, contract_id: str, side: int, size: int, limit_price: float, tag: str) -> str:
        self._need()
        if tag in self.tags:
            raise BrokerError(f"duplicate customTag {tag}")
        self.tags.add(tag)
        return self._new_order(tag, "limit", side, size, limit=limit_price).info.id

    def find_order_by_tag(self, tag: str, since: datetime) -> OrderInfo | None:
        self._need()
        for o in self.orders.values():
            if o.info.tag == tag:
                return o.info
        return None

    def order(self, order_id: str, since: datetime) -> OrderInfo | None:
        self._need()
        o = self.orders.get(order_id)
        return o.info if o else None

    def open_orders(self) -> list[OrderInfo]:
        self._need()
        return [o.info for o in self.orders.values() if o.info.status == "open"]

    def positions(self) -> list[PositionInfo]:
        self._need()
        return [PositionInfo(self.c.id, self.pos.size, self.pos.avg)] if self.pos.size else []

    def cancel(self, order_id: str) -> None:
        self._need()
        o = self.orders.get(order_id)
        if o is None:
            raise BrokerError(f"order {order_id} not found")
        if o.info.status == "open":
            o.info.status = "cancelled"

    def close_position(self, contract_id: str) -> None:
        self._need()
        if self.pos.size == 0:
            raise BrokerError("no open position")
        if self.last_bar is None:
            raise BrokerError("no price available")
        side = -1 if self.pos.size > 0 else 1
        o = self._new_order(None, "market", side, abs(self.pos.size))
        self._fill(o, self.last_bar.c + side * self.slip, self._now())

    def fills(self, since: datetime) -> list[FillInfo]:
        self._need()
        return [f for f in self._fills if f.ts >= since]

    # ------------------------------------------------------------------ market simulation
    def on_minute(self, bar: MinuteBar) -> None:
        """Process one completed futures minute bar (called in time order)."""
        self.last_bar = bar
        o_, h, l = bar.o, bar.h, bar.l
        for o in list(self.orders.values()):
            i = o.info
            if i.status != "open" or i.type != "market" or o.placed is None:
                continue
            if bar.ts < o.placed.replace(second=0, microsecond=0):    # bar must start at/after the order minute
                continue
            price = o_ + i.side * self.slip
            self._fill(o, price, bar.ts)
            if o.entry_bracket is not None:
                st, tt = o.entry_bracket
                grp = f"oco-{i.id}"
                stop_px = price - i.side * st * self.c.tick_size
                tgt_px = price + i.side * tt * self.c.tick_size
                s = self._new_order(None, "stop", -i.side, i.size, stop=stop_px, oco=grp)
                t = self._new_order(None, "limit", -i.side, i.size, limit=tgt_px, oco=grp)
                s.entry_minute = t.entry_minute = bar.ts
        # protective orders: stop first (conservative), gap-through at the open, no target in the entry minute
        for o in list(self.orders.values()):
            i = o.info
            if i.status != "open" or i.type != "stop" or math.isnan(h):
                continue
            hit = (l <= i.stop_price) if i.side < 0 else (h >= i.stop_price)
            if hit:
                gap = o.entry_minute != bar.ts and ((o_ <= i.stop_price) if i.side < 0 else (o_ >= i.stop_price))
                raw = o_ if gap else i.stop_price
                self._fill(o, raw + i.side * self.slip, bar.ts)
        for o in list(self.orders.values()):
            i = o.info
            if i.status != "open" or i.type != "limit" or o.entry_minute == bar.ts:
                continue
            hit = (h >= i.limit_price) if i.side < 0 else (l <= i.limit_price)
            if hit:
                gap = (o_ >= i.limit_price) if i.side < 0 else (o_ <= i.limit_price)
                self._fill(o, o_ if gap else i.limit_price, bar.ts)
