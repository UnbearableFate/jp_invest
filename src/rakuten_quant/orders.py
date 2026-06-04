from __future__ import annotations

from pathlib import Path
import math

import pandas as pd

from .config import StrategyConfig
from .portfolio import target_weights


def load_positions(path: str | Path | None, config: StrategyConfig) -> pd.Series:
    positions = pd.Series(0.0, index=config.symbols, dtype=float)
    if path is None:
        return positions
    raw = pd.read_csv(path)
    if not {"symbol", "units"}.issubset(raw.columns):
        raise ValueError("positions CSV must contain symbol,units columns.")
    for _, row in raw.iterrows():
        symbol = str(row["symbol"])
        if symbol in positions.index:
            positions[symbol] = float(row["units"])
    return positions


def build_orders(
    prices: pd.DataFrame,
    config: StrategyConfig,
    positions: pd.Series | None = None,
    current_drawdown: float = 0.0,
    model_scores: pd.Series | None = None,
    model_weight: float = 0.0,
) -> pd.DataFrame:
    latest_prices = prices.iloc[-1]
    weights = target_weights(
        prices,
        config,
        prices.index[-1],
        current_drawdown,
        model_scores=model_scores,
        model_weight=model_weight,
    )
    if positions is None:
        positions = pd.Series(0.0, index=config.symbols, dtype=float)

    current_values = positions.reindex(config.symbols).fillna(0.0) * latest_prices.reindex(config.symbols)
    cash_value = config.portfolio.capital_jpy - float(current_values.drop(labels=[config.cash_symbol], errors="ignore").sum())
    current_values[config.cash_symbol] = max(cash_value, 0.0)
    portfolio_value = float(current_values.sum())

    rows: list[dict[str, object]] = []
    for asset in config.enabled_assets:
        if asset.role == "cash":
            continue
        price = float(latest_prices[asset.symbol])
        current_units = float(positions.get(asset.symbol, 0.0))
        target_value = portfolio_value * float(weights[asset.symbol])
        raw_units = target_value / price
        target_units = floor_to_unit(raw_units, asset.min_trade_unit)
        trade_units = target_units - current_units
        trade_value = trade_units * price
        current_weight = float(current_values.get(asset.symbol, 0.0) / portfolio_value) if portfolio_value else 0.0
        target_weight = float(weights[asset.symbol])
        weight_gap = target_weight - current_weight

        if abs(weight_gap) < config.portfolio.rebalance_threshold:
            action = "HOLD"
        elif abs(trade_value) < config.portfolio.min_trade_jpy:
            action = "HOLD_SMALL"
        elif trade_units > 0:
            action = "BUY"
        elif trade_units < 0:
            action = "SELL"
        else:
            action = "HOLD"

        rows.append(
            {
                "date": prices.index[-1].date().isoformat(),
                "symbol": asset.symbol,
                "name": asset.name,
                "action": action,
                "price": price,
                "current_units": current_units,
                "target_units": target_units,
                "trade_units": trade_units if action in {"BUY", "SELL"} else 0.0,
                "trade_value_jpy": trade_value if action in {"BUY", "SELL"} else 0.0,
                "current_weight": current_weight,
                "target_weight": target_weight,
                "weight_gap": weight_gap,
            }
        )

    return pd.DataFrame(rows)


def floor_to_unit(units: float, min_trade_unit: int) -> float:
    if min_trade_unit <= 0:
        raise ValueError("min_trade_unit must be positive.")
    return math.floor(units / min_trade_unit) * min_trade_unit
