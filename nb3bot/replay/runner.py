"""Historical replay: stream sessions bar by bar through the live strategy engine.

`replay_backtest` reproduces the verified backtest exactly: the same engine the live bot uses,
plus the backtest's fill assumptions (BracketSim with QQQ ticks, 2 ticks of slippage on market and
stop fills, $0.005 per share per side). Every minute is processed in time order and a 5-minute bar is
completed only after its last minute, so nothing can see the future.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Iterable

from nb3bot.replay.data import Session
from nb3bot.strategy.bracket import BracketSim
from nb3bot.strategy.nb3v2 import NB3V2Engine, NB3V2Params, Signal


@dataclass
class ReplayTrade:
    dkey: int
    direction: int
    signal_bar: int
    entry_min: int
    fill: float
    dist: float
    exit_min: int
    exit_px: float
    reason: str
    r_net: float
    r_gross: float
    stop: float
    target: float

    def to_dict(self) -> dict:
        return asdict(self)


def replay_backtest(sessions: Iterable[Session], params: NB3V2Params = NB3V2Params(), tick: float = 0.01,
                    slip_ticks: float = 2.0, commission: float = 0.005,
                    end_key: int | None = None) -> tuple[list[ReplayTrade], list[Signal]]:
    eng = NB3V2Engine(params)
    slip = slip_ticks * tick
    trades: list[ReplayTrade] = []
    signals: list[Signal] = []
    for s in sessions:
        if end_key is not None and s.key > end_key:
            break
        eng.begin_session(s.key)
        pending: Signal | None = None
        br: BracketSim | None = None
        for m in range(390):
            if pending is not None and br is None and pending.entry_minute <= m < params.eod_minute \
                    and not math.isnan(s.o[m]):
                br = BracketSim(pending.direction, float(s.o[m]), m, pending.stop_distance,
                                params.reward_risk, slip)
                pending_sig, pending = pending, None
            if br is not None and br.result is None and m < params.eod_minute:
                br.on_minute(m, float(s.o[m]), float(s.h[m]), float(s.l[m]))
            if not (math.isnan(s.o[m]) and math.isnan(s.h[m]) and math.isnan(s.l[m]) and math.isnan(s.c[m])):
                eng.on_minute(m, float(s.o[m]), float(s.h[m]), float(s.l[m]), float(s.c[m]))
            if m % 5 == 4:
                sig = eng.complete_bar(m // 5)
                if sig is not None:
                    signals.append(sig)
                    pending = sig
        if br is not None:
            br.end_of_day(params.eod_minute, s.last_close_at_or_before(params.eod_minute - 1))
            net, gross = br.r_multiple(commission)
            r = br.result
            trades.append(ReplayTrade(s.key, br.dir, pending_sig.bar, br.ei, br.fill, br.dist, r.exit_minute,
                                      r.exit_price, r.reason, net, gross, br.stop, br.target))
        eng.end_session()
    return trades, signals
