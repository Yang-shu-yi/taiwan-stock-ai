from __future__ import annotations

import os
import uuid
from dataclasses import asdict, dataclass
from typing import Any


SIGNAL_SCHEMA_VERSION = 2
PERFORMANCE_SCHEMA_VERSION = 2
STRATEGY_VERSION = os.getenv("STRATEGY_VERSION", "tw-entry-v1").strip() or "tw-entry-v1"
FEATURE_VERSION = "tw-unified-features-v2"
MODEL_VERSION = "logistic-ranking-v1"

PRIMARY_CHANNEL = "primary"
SHADOW_CHANNEL = "shadow"
EARLY_WATCH_CHANNEL = "early_watch"
LIVE_ENVIRONMENT = "live"
RESEARCH_ENVIRONMENT = "research"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class CostAssumptions:
    """Rates are decimal fractions of notional, not percentage points."""

    buy_commission_rate: float
    sell_commission_rate: float
    sell_tax_rate: float
    buy_slippage_rate: float
    sell_slippage_rate: float

    @classmethod
    def from_env(cls) -> "CostAssumptions":
        commission = max(0.0, _env_float("BROKER_COMMISSION_RATE", 0.001425))
        slippage = max(0.0, _env_float("SLIPPAGE_RATE", 0.0005))
        return cls(
            buy_commission_rate=max(
                0.0,
                _env_float("BUY_COMMISSION_RATE", commission),
            ),
            sell_commission_rate=max(
                0.0,
                _env_float("SELL_COMMISSION_RATE", commission),
            ),
            sell_tax_rate=max(0.0, _env_float("STOCK_SELL_TAX_RATE", 0.003)),
            buy_slippage_rate=max(
                0.0,
                _env_float("BUY_SLIPPAGE_RATE", slippage),
            ),
            sell_slippage_rate=max(
                0.0,
                _env_float("SELL_SLIPPAGE_RATE", slippage),
            ),
        )

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


def resolve_run_context(*, dry_run: bool = False) -> dict[str, str]:
    if dry_run:
        return {
            "execution_environment": RESEARCH_ENVIRONMENT,
            "run_type": "dry_run",
            "strategy_version": STRATEGY_VERSION,
            "feature_version": FEATURE_VERSION,
        }

    environment = os.getenv("EXECUTION_ENVIRONMENT", LIVE_ENVIRONMENT).strip().lower()
    if environment not in {LIVE_ENVIRONMENT, RESEARCH_ENVIRONMENT}:
        environment = LIVE_ENVIRONMENT
    run_type = os.getenv("RUN_TYPE", "scheduled").strip().lower() or "scheduled"
    if run_type not in {"scheduled", "manual", "backfill", "research"}:
        run_type = "manual"
    return {
        "execution_environment": environment,
        "run_type": run_type,
        "strategy_version": STRATEGY_VERSION,
        "feature_version": FEATURE_VERSION,
    }


def build_run_id(
    *,
    decision_at: str,
    mode: str,
    execution_environment: str,
    run_type: str,
    strategy_version: str,
) -> str:
    payload = "|".join(
        [
            decision_at,
            mode.upper(),
            execution_environment.lower(),
            run_type.lower(),
            strategy_version,
        ]
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"taiwan-stock-ai/run/{payload}"))


def build_signal_id(
    *,
    run_id: str,
    code: str,
    candidate_channel: str,
    strategy_version: str,
) -> str:
    payload = "|".join([run_id, code, candidate_channel, strategy_version])
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"taiwan-stock-ai/signal/{payload}"))


def entry_rule_for_mode(mode: str) -> str:
    return "next_session_open" if str(mode).upper() == "POST" else "decision_session_open"


def calculate_net_trade_return(
    entry_price: float,
    exit_price: float,
    assumptions: CostAssumptions | None = None,
) -> dict[str, float]:
    assumptions = assumptions or CostAssumptions.from_env()
    if entry_price <= 0 or exit_price <= 0:
        raise ValueError("entry_price and exit_price must be positive")

    gross_return_pct = (exit_price / entry_price - 1.0) * 100.0
    cash_paid = entry_price * (
        1.0
        + assumptions.buy_commission_rate
        + assumptions.buy_slippage_rate
    )
    cash_received = exit_price * (
        1.0
        - assumptions.sell_commission_rate
        - assumptions.sell_tax_rate
        - assumptions.sell_slippage_rate
    )
    net_return_pct = (cash_received / cash_paid - 1.0) * 100.0
    return {
        "gross_return_pct": gross_return_pct,
        "net_return_pct": net_return_pct,
        "transaction_cost_pct": gross_return_pct - net_return_pct,
    }


def public_cost_assumptions(
    assumptions: CostAssumptions | None = None,
) -> dict[str, Any]:
    assumptions = assumptions or CostAssumptions.from_env()
    values = assumptions.to_dict()
    values["rates_unit"] = "decimal_fraction_of_notional"
    values["round_trip_cost_at_flat_price_pct"] = round(
        calculate_net_trade_return(100.0, 100.0, assumptions)["transaction_cost_pct"],
        4,
    )
    values["commission_note"] = "券商費率可自訂；請以實際帳戶費率覆寫環境變數"
    return values
