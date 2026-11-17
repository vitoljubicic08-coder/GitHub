"""Bot configuration (TOML). Secrets never go in the file: only the NAMES of environment variables.

Safety defaults: mode "replay", paper broker, and both order-sending switches OFF. Sending orders to a
practice account or a real evaluation/funded account requires the matching switch in the file, the
matching --mode on the command line, and a signed authorization file (see nb3bot/safety.py).
"""
from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path

MODES = ("replay", "paper", "practice", "live")


@dataclass
class BotCfg:
    profile: str = ""                     # e.g. tradingview_50k_demo (shown on the dashboard)
    banner: str = ""                      # one-line notice shown at the top of the dashboard
    mode: str = "replay"
    state_dir: str = "state"
    log_dir: str = "logs"
    display_timezone: str = "Europe/Zagreb"
    loop_interval_seconds: float = 1.0


@dataclass
class StrategyCfg:
    signal_source: str = "QQQ"            # QQQ (validated) | MNQ (97% same bar; not the validated source)
    early_close_policy: str = "skip"      # NB3 V2 has no early-close rule; the bot does not trade those days
    max_signal_delay_seconds: float = 45  # entry must be sent within this long after the 5-minute bar closes
    warmup_sessions: int = 250            # sessions replayed at start-up for the noise band and ATR
    reward_risk: float = 3.0              # NB3 V2: 3. Lucid "steady" profile (research round 5): 1.5
    max_trades_per_day: int = 1           # NB3 V2: 1. Lucid "steady": 2 (next signal after the first closes)


@dataclass
class InstrumentCfg:
    symbol: str = "MNQ"
    tick_size: float = 0.25
    tick_value: float = 0.50
    point_value: float = 2.0
    stop_conversion: str = "qqq_ratio"    # qqq_ratio: QQQ stop x (MNQ/QQQ price) | native_atr (MNQ source)
    roll_days_before_expiry: int = 8      # switch to the next quarterly contract this many days before expiry


@dataclass
class CostsCfg:
    commission_round_turn: float = 1.22   # per MNQ, Topstep all-in (help centre)
    slippage_ticks_per_side: float = 1.0  # included in per-contract risk
    extra_stop_slippage_ticks: float = 4.0  # extra allowance in the worst-case (gap) check


@dataclass
class RiskCfg:
    phase: str = "evaluation"             # evaluation | funded
    evaluation_risk_per_trade: float = 350.0
    funded_risk_per_trade: float = 250.0
    max_contracts: int = 1                # hard cap; start with one MNQ
    max_daily_loss: float = 400.0         # personal limit (stricter than the firm's): checked before every
                                          # entry, and while a trade is open (see flatten_on_daily_loss)
    flatten_on_daily_loss: bool = True    # close the open trade and stop for the day if today's P&L incl. open
                                          # P&L reaches -max_daily_loss (or the firm's daily limit, if lower)
    max_daily_profit: float = 0.0         # 0 = off. Once today's P&L reaches this, no new entries today
    flatten_on_daily_profit: bool = False # also close the open trade when max_daily_profit is reached
    consistency_day_cap: bool = True      # evaluation with a best-day rule (Lucid 40%, Topstep 55%): no entry
                                          # whose full target would push today above rule x profit target
    max_weekly_loss: float = 800.0
    max_total_drawdown: float = 2000.0    # from the account's high-water mark (= the firm's limit by default)
    safety_reserve: float = 100.0         # must remain above the firm loss limit after the worst case
    halt_after_consecutive_losses: int = 0  # 0 = off (not part of the tested strategy)
    edge_stop_rules: bool = True          # pre-registered stop rules from the research report
    edge_min_mean_200: float = 0.05       # 200-trade rule: stop if the mean R is below this (NB3 V2: +0.05R)


@dataclass
class AccountCfg:
    preset: str = "topstep_combine_50k"   # see nb3bot/risk/account.py PRESETS, or "custom"
    starting_balance: float = 50000.0
    max_loss_limit: float = 2000.0
    trailing: str = "eod"                 # eod | intraday | static
    lock_profit: float | None = 0.0       # floor stops trailing at starting balance + this (None = never)
    daily_loss_limit: float | None = 1000.0
    max_contracts_firm: int = 50
    payout_rules: str = ""                # "" = not tracked | lucid_flex_50k (nb3bot/risk/payout.py)
    payout_keep_above_floor: float = 500.0  # recommended request leaves at least this above the loss limit


@dataclass
class BrokerCfg:
    name: str = "paper"                   # paper | projectx
    api_base: str = "https://api.topstepx.com"
    market_hub: str = "https://rtc.topstepx.com/hubs/market"
    user_hub: str = "https://rtc.topstepx.com/hubs/user"
    account_id: int = 0
    account_name: str = ""
    username_env: str = "PROJECTX_USERNAME"
    api_key_env: str = "PROJECTX_API_KEY"
    live_data: bool = False               # ProjectX 'live' flag for bars/contracts (data subscription)
    auto_oco_brackets_confirmed: bool = False  # you set Auto OCO Brackets in the platform risk settings
    fill_timeout_seconds: float = 10.0
    bracket_check_seconds: float = 5.0


@dataclass
class DataCfg:
    qqq_provider: str = "massive"         # massive (Polygon-compatible REST) | alpaca | replay
    qqq_api_base: str = "https://api.massive.com"
    qqq_api_key_env: str = "MASSIVE_API_KEY"
    alpaca_api_base: str = "https://data.alpaca.markets"
    alpaca_key_id_env: str = "ALPACA_API_KEY_ID"
    alpaca_secret_env: str = "ALPACA_API_SECRET_KEY"
    alpaca_live_feed: str = "iex"         # free plan: real-time IEX only
    alpaca_history_feed: str = "sip"      # free plan: consolidated (SIP) bars older than 15 minutes
    mnq_provider: str = "projectx"        # projectx | synthetic (QQQ x ratio, paper/replay only) | replay
    synthetic_ratio: float = 41.3         # MNQ/QQQ price ratio for synthetic futures prices
    bar_grace_seconds: float = 3.0        # wait this long after a minute ends before asking for it
    max_bar_delay_seconds: float = 20.0   # a finished minute still missing after this -> data problem
    allow_empty_minutes: bool = False     # true for single-exchange feeds (IEX): a minute with no trades
                                          # has no bar; then freshness is checked instead
    stale_after_seconds: float = 180.0    # with allow_empty_minutes: no new bar for this long -> data problem
    eod_rebuild_delay_minutes: float = 3.0  # wait after the close before re-downloading final bars
    max_ratio_deviation: float = 0.01     # MNQ/QQQ ratio vs its session median before entries halt
    replay_source: str = ""               # npz cache dir or CSV for replay / simulated-live runs
    replay_mnq_source: str = ""           # optional MNQ minute data for paper fills in replay


@dataclass
class AuthorizationCfg:
    practice_orders_enabled: bool = False
    live_orders_enabled: bool = False


@dataclass
class AlertsCfg:
    telegram_bot_token_env: str = "NB3_TELEGRAM_TOKEN"
    telegram_chat_id: str = ""
    webhook_url: str = ""
    email_smtp_host: str = ""
    email_to: str = ""
    email_user_env: str = "NB3_SMTP_USER"
    email_password_env: str = "NB3_SMTP_PASSWORD"


@dataclass
class DashboardCfg:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8765


@dataclass
class Config:
    bot: BotCfg = field(default_factory=BotCfg)
    strategy: StrategyCfg = field(default_factory=StrategyCfg)
    instrument: InstrumentCfg = field(default_factory=InstrumentCfg)
    costs: CostsCfg = field(default_factory=CostsCfg)
    risk: RiskCfg = field(default_factory=RiskCfg)
    account: AccountCfg = field(default_factory=AccountCfg)
    broker: BrokerCfg = field(default_factory=BrokerCfg)
    data: DataCfg = field(default_factory=DataCfg)
    authorization: AuthorizationCfg = field(default_factory=AuthorizationCfg)
    alerts: AlertsCfg = field(default_factory=AlertsCfg)
    dashboard: DashboardCfg = field(default_factory=DashboardCfg)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def risk_budget(self) -> float:
        return self.risk.funded_risk_per_trade if self.risk.phase == "funded" else self.risk.evaluation_risk_per_trade


def _fill(obj, data: dict, path: str) -> None:
    names = {f.name: f for f in fields(obj)}
    for k, v in data.items():
        if k not in names:
            raise ValueError(f"unknown setting {path}{k}")
        cur = getattr(obj, k)
        if is_dataclass(cur):
            if not isinstance(v, dict):
                raise ValueError(f"{path}{k} must be a table")
            _fill(cur, v, f"{path}{k}.")
        else:
            setattr(obj, k, v)


def validate(cfg: Config) -> list[str]:
    """Return a list of configuration errors (empty = valid)."""
    e = []
    if cfg.bot.mode not in MODES:
        e.append(f"bot.mode must be one of {MODES}")
    if cfg.strategy.signal_source not in ("QQQ", "MNQ"):
        e.append("strategy.signal_source must be QQQ or MNQ")
    if cfg.strategy.early_close_policy != "skip":
        e.append("strategy.early_close_policy: only 'skip' is supported (NB3 V2 defines no early-close rule)")
    if cfg.risk.phase not in ("evaluation", "funded"):
        e.append("risk.phase must be evaluation or funded")
    if cfg.risk.max_daily_profit < 0:
        e.append("risk.max_daily_profit must be 0 (off) or positive")
    if not cfg.strategy.reward_risk > 0:
        e.append("strategy.reward_risk must be positive")
    if cfg.strategy.max_trades_per_day not in (1, 2):
        e.append("strategy.max_trades_per_day must be 1 or 2 (the tested settings)")
    if cfg.account.payout_rules not in ("", "lucid_flex_50k"):
        e.append("account.payout_rules must be empty or lucid_flex_50k")
    if cfg.risk.max_contracts < 1:
        e.append("risk.max_contracts must be at least 1")
    for k in ("evaluation_risk_per_trade", "funded_risk_per_trade", "max_daily_loss", "max_weekly_loss",
              "max_total_drawdown", "safety_reserve"):
        if getattr(cfg.risk, k) <= 0:
            e.append(f"risk.{k} must be positive")
    if cfg.account.trailing not in ("eod", "intraday", "static"):
        e.append("account.trailing must be eod, intraday or static")
    if cfg.broker.name not in ("paper", "projectx"):
        e.append("broker.name must be paper or projectx")
    if cfg.bot.mode in ("practice", "live") and cfg.broker.name != "projectx":
        e.append(f"mode {cfg.bot.mode} needs broker.name = projectx")
    if cfg.bot.mode in ("practice", "live") and not cfg.broker.auto_oco_brackets_confirmed:
        e.append("set broker.auto_oco_brackets_confirmed = true after switching the account to Auto OCO Brackets")
    if cfg.instrument.tick_size <= 0 or cfg.instrument.point_value <= 0:
        e.append("instrument tick_size and point_value must be positive")
    if cfg.data.qqq_provider not in ("massive", "alpaca", "replay"):
        e.append("data.qqq_provider must be massive, alpaca or replay")
    if cfg.data.mnq_provider not in ("projectx", "synthetic", "replay"):
        e.append("data.mnq_provider must be projectx, synthetic or replay")
    if cfg.data.mnq_provider == "synthetic":
        if cfg.bot.mode in ("practice", "live") or cfg.broker.name != "paper":
            e.append("synthetic MNQ prices are only allowed with the paper broker (paper/replay modes)")
        if cfg.strategy.signal_source != "QQQ":
            e.append("synthetic MNQ prices are derived from QQQ: strategy.signal_source must be QQQ")
        if not cfg.data.synthetic_ratio > 0:
            e.append("data.synthetic_ratio must be positive")
    if cfg.data.alpaca_live_feed not in ("iex", "sip") or cfg.data.alpaca_history_feed not in ("iex", "sip"):
        e.append("alpaca feeds must be iex or sip")
    if cfg.strategy.signal_source == "MNQ" and cfg.instrument.stop_conversion != "native_atr":
        e.append("signal_source MNQ requires instrument.stop_conversion = native_atr")
    return e


def load(path: str | Path | None) -> Config:
    cfg = Config()
    if path:
        with open(path, "rb") as fh:
            _fill(cfg, tomllib.load(fh), "")
    errs = validate(cfg)
    if errs:
        raise ValueError("invalid configuration:\n  " + "\n  ".join(errs))
    return cfg
