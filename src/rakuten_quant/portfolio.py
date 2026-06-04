from __future__ import annotations

import pandas as pd

from .config import StrategyConfig
from .signals import signal_table


def target_weights(
    prices: pd.DataFrame,
    config: StrategyConfig,
    asof: pd.Timestamp | None = None,
    current_drawdown: float = 0.0,
    model_scores: pd.Series | None = None,
    model_weight: float = 0.0,
) -> pd.Series:
    if asof is None:
        asof = prices.index[-1]
    table = signal_table(
        prices,
        config,
        pd.Timestamp(asof),
        model_scores=model_scores,
        model_weight=model_weight,
    )
    weights = pd.Series(0.0, index=config.symbols, dtype=float)
    cash_symbol = config.cash_symbol
    cash_floor = config.portfolio.cash_floor_weight

    if current_drawdown >= config.portfolio.full_defense_drawdown:
        return defensive_weights(config, weights, cash_floor)

    eligible = table[(table["role"] == "risk") & (table["eligible"])].copy()
    if not eligible.empty:
        eligible = eligible[eligible["symbol"].map(lambda symbol: is_affordable(symbol, table, config))]
    if eligible.empty:
        return defensive_weights(config, weights, cash_floor)

    selected = eligible.sort_values("score", ascending=False).head(config.portfolio.max_positions)
    raw = (1.0 / selected.set_index("symbol")["volatility"].clip(lower=0.01)).astype(float)
    raw = raw / raw.sum()
    invest_weight = 1.0 - cash_floor
    risk_weights = raw * invest_weight

    caps = {asset.symbol: asset.max_weight for asset in config.enabled_assets}
    capped = cap_weights(risk_weights, caps, invest_weight)
    weights.loc[capped.index] = capped
    weights[cash_symbol] = 1.0 - weights.sum()

    if current_drawdown >= config.portfolio.risk_reduce_drawdown:
        risk_symbols = [asset.symbol for asset in config.by_role("risk")]
        reduction = weights.loc[risk_symbols].sum() * 0.5
        weights.loc[risk_symbols] *= 0.5
        weights = add_to_defensive_or_cash(config, weights, reduction)

    return normalize_weights(weights)


def defensive_weights(config: StrategyConfig, weights: pd.Series, cash_floor: float) -> pd.Series:
    weights[:] = 0.0
    defensive_assets = config.by_role("defensive")
    target_defensive = 1.0 - cash_floor
    if defensive_assets:
        asset = defensive_assets[0]
        weights[asset.symbol] = min(target_defensive, asset.max_weight)
    weights[config.cash_symbol] = 1.0 - weights.sum()
    return normalize_weights(weights)


def is_affordable(symbol: str, signal_table: pd.DataFrame, config: StrategyConfig) -> bool:
    asset = config.asset(symbol)
    row = signal_table.loc[signal_table["symbol"] == symbol]
    if row.empty:
        return False
    min_lot_value = float(row.iloc[0]["close"]) * asset.min_trade_unit
    return min_lot_value <= config.portfolio.capital_jpy * asset.max_weight


def add_to_defensive_or_cash(config: StrategyConfig, weights: pd.Series, amount: float) -> pd.Series:
    remaining = amount
    for asset in config.by_role("defensive"):
        capacity = max(asset.max_weight - weights.get(asset.symbol, 0.0), 0.0)
        add = min(capacity, remaining)
        weights[asset.symbol] += add
        remaining -= add
        if remaining <= 1e-12:
            break
    weights[config.cash_symbol] += remaining
    return weights


def cap_weights(raw: pd.Series, caps: dict[str, float], total_weight: float) -> pd.Series:
    raw = raw.astype(float).copy()
    if raw.empty:
        return raw

    result = pd.Series(0.0, index=raw.index, dtype=float)
    remaining_symbols = list(raw.index)
    remaining_weight = total_weight

    while remaining_symbols and remaining_weight > 1e-12:
        subset = raw.loc[remaining_symbols]
        subset = subset / subset.sum() * remaining_weight
        capped_symbols = []
        for symbol, weight in subset.items():
            cap = caps.get(symbol, 1.0)
            if weight > cap:
                result[symbol] = cap
                remaining_weight -= cap
                capped_symbols.append(symbol)
        if not capped_symbols:
            result.loc[remaining_symbols] = subset
            break
        remaining_symbols = [symbol for symbol in remaining_symbols if symbol not in capped_symbols]

    return result


def normalize_weights(weights: pd.Series) -> pd.Series:
    weights = weights.clip(lower=0.0)
    total = weights.sum()
    if total <= 0:
        raise ValueError("Target weights sum to zero.")
    return weights / total
