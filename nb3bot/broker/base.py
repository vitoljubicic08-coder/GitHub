"""Broker interface used by the execution manager. Implementations: PaperBroker, ProjectXBroker."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


class BrokerError(RuntimeError):
    """The broker answered and refused (rejection, validation error)."""


class UncertainOrderState(BrokerError):
    """The request may or may not have reached the broker (timeout, dropped connection).
    Never resend: look the order up by its unique tag first."""


class BrokerUnavailable(BrokerError):
    """No connection / authentication failure."""


@dataclass
class ContractInfo:
    id: str
    name: str
    tick_size: float
    tick_value: float
    active: bool


@dataclass
class AccountInfo:
    id: int
    name: str
    balance: float
    can_trade: bool
    simulated: bool | None = None


@dataclass
class OrderInfo:
    id: str
    tag: str | None
    contract_id: str
    status: str           # open | filled | cancelled | expired | rejected | pending
    type: str             # market | limit | stop | stop_limit | trailing | other
    side: int             # +1 buy / -1 sell
    size: int
    filled_size: int
    fill_price: float | None
    limit_price: float | None
    stop_price: float | None
    created: datetime | None = None


@dataclass
class PositionInfo:
    contract_id: str
    size: int             # signed: + long / - short
    avg_price: float


@dataclass
class FillInfo:
    order_id: str
    contract_id: str
    side: int
    size: int
    price: float
    pnl: float | None     # gross P&L of a closing leg, None for an opening leg
    fees: float
    ts: datetime
    voided: bool = False


@dataclass
class BracketEntry:
    contract_id: str
    side: int             # +1 buy / -1 sell
    size: int
    stop_ticks: int
    target_ticks: int
    tag: str              # unique per account: the idempotency key


class Broker(ABC):
    name = "broker"
    places_real_orders = False

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def account(self) -> AccountInfo: ...

    @abstractmethod
    def contracts(self, search: str) -> list[ContractInfo]: ...

    @abstractmethod
    def place_bracket_entry(self, req: BracketEntry) -> str:
        """Market entry with broker-side stop-loss and take-profit (OCO). Returns the entry order id."""

    @abstractmethod
    def place_stop(self, contract_id: str, side: int, size: int, stop_price: float, tag: str) -> str: ...

    @abstractmethod
    def place_limit(self, contract_id: str, side: int, size: int, limit_price: float, tag: str) -> str: ...

    @abstractmethod
    def find_order_by_tag(self, tag: str, since: datetime) -> OrderInfo | None: ...

    @abstractmethod
    def order(self, order_id: str, since: datetime) -> OrderInfo | None: ...

    @abstractmethod
    def open_orders(self) -> list[OrderInfo]: ...

    @abstractmethod
    def positions(self) -> list[PositionInfo]: ...

    @abstractmethod
    def cancel(self, order_id: str) -> None: ...

    @abstractmethod
    def close_position(self, contract_id: str) -> None: ...

    @abstractmethod
    def fills(self, since: datetime) -> list[FillInfo]: ...
