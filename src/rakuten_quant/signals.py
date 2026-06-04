from __future__ import annotations

import numpy as np
import pandas as pd

from .config import StrategyConfig


def latest_signal_table(
    prices: pd.DataFrame,
    config: StrategyConfig,
    model_scores: pd.Series | None = None,
    model_weight: float = 0.0,
) -> pd.DataFrame:
    return signal_table(prices, config, prices.index[-1], model_scores=model_scores, model_weight=model_weight)


def signal_table(
    prices: pd.DataFrame,
    config: StrategyConfig,
    asof: pd.Timestamp,
    model_scores: pd.Series | None = None,
    model_weight: float = 0.0,
) -> pd.DataFrame:
    history = prices.loc[:asof]
    if len(history) < config.signals.min_history_days:
        raise ValueError(
            f"Need at least {config.signals.min_history_days} rows for signals; got {len(history)}."
        )

    rows: list[dict[str, object]] = []
    for asset in config.enabled_assets:
        if asset.role == "cash":
            continue
        close = history[asset.symbol].dropna()
        if len(close) < config.signals.min_history_days:
            continue

        skip = config.signals.skip_days
        fast = config.signals.momentum_fast_days
        slow = config.signals.momentum_slow_days
        vol_window = config.signals.volatility_days
        trend_window = config.signals.trend_days

        current = close.iloc[-1]
        fast_start = close.iloc[-skip - fast]
        fast_end = close.iloc[-skip]
        slow_start = close.iloc[-skip - slow]
        slow_end = close.iloc[-skip]
        fast_momentum = fast_end / fast_start - 1.0
        slow_momentum = slow_end / slow_start - 1.0
        volatility = close.pct_change().dropna().iloc[-vol_window:].std() * np.sqrt(252)
        trend_ma = close.iloc[-trend_window:].mean()

        eligible = bool(current > trend_ma and slow_momentum > 0)
        rows.append(
            {
                "date": pd.Timestamp(asof).date().isoformat(),
                "symbol": asset.symbol,
                "name": asset.name,
                "role": asset.role,
                "asset_class": asset.asset_class,
                "close": current,
                "momentum_fast": fast_momentum,
                "momentum_slow": slow_momentum,
                "volatility": volatility,
                "trend_ma": trend_ma,
                "eligible": eligible,
            }
        )

    table = pd.DataFrame(rows)
    if table.empty:
        return table

    risk_mask = table["role"] == "risk"
    table["score"] = np.nan
    if risk_mask.any():
        risk = table.loc[risk_mask].copy()
        fast_rank = risk["momentum_fast"].rank(pct=True)
        slow_rank = risk["momentum_slow"].rank(pct=True)
        vol_rank = risk["volatility"].rank(pct=True)
        table.loc[risk.index, "score"] = 0.5 * fast_rank + 0.5 * slow_rank - 0.25 * vol_rank
        table.loc[risk.index, "rule_score"] = table.loc[risk.index, "score"]

    if model_scores is not None and model_weight > 0:
        weight = min(max(float(model_weight), 0.0), 1.0)
        score_map = model_scores.astype(float).to_dict()
        table["model_score"] = table["symbol"].map(score_map)
        model_mask = risk_mask & table["model_score"].notna() & table["score"].notna()
        table.loc[model_mask, "score"] = (
            (1.0 - weight) * table.loc[model_mask, "score"].astype(float)
            + weight * table.loc[model_mask, "model_score"].astype(float)
        )
    else:
        table["model_score"] = np.nan

    if "rule_score" not in table.columns:
        table["rule_score"] = table["score"]
    return table.sort_values(["eligible", "score"], ascending=[False, False])


def rebalance_dates(prices: pd.DataFrame, frequency: str) -> pd.DatetimeIndex:
    if prices.empty:
        return pd.DatetimeIndex([])
    if frequency == "M":
        frequency = "ME"
    dates = []
    for _, frame in prices.resample(frequency):
        frame = frame.dropna(how="all")
        if not frame.empty:
            dates.append(frame.index[-1])
    return pd.DatetimeIndex(dates)
