from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import BacktestResult, run_backtest, write_backtest_outputs
from .config import StrategyConfig
from .portfolio import add_to_defensive_or_cash, cap_weights, defensive_weights, is_affordable, normalize_weights
from .signals import signal_table


@dataclass(frozen=True)
class BasicStrategyProvider:
    name: str
    mode: str
    trend_window: int = 200
    volatility_window: int = 63
    momentum_window: int = 252
    fast_momentum_window: int = 126

    def target_weights(
        self,
        prices: pd.DataFrame,
        config: StrategyConfig,
        asof: pd.Timestamp | None = None,
        current_drawdown: float = 0.0,
    ) -> pd.Series:
        if asof is None:
            asof = prices.index[-1]
        asof = pd.Timestamp(asof)
        weights = pd.Series(0.0, index=config.symbols, dtype=float)
        cash_floor = config.portfolio.cash_floor_weight

        if current_drawdown >= config.portfolio.full_defense_drawdown:
            return defensive_weights(config, weights, cash_floor)

        candidates = candidate_table(prices.loc[:asof], config, self)
        if candidates.empty:
            return defensive_weights(config, weights, cash_floor)

        candidates = apply_mode_filters(candidates, self.mode)
        if candidates.empty:
            return defensive_weights(config, weights, cash_floor)

        candidates = candidates.sort_values("score", ascending=False).head(config.portfolio.max_positions)
        if self.mode in {"inverse_volatility", "trend_inverse_volatility", "dual_momentum"}:
            raw = 1.0 / candidates.set_index("symbol")["volatility"].clip(lower=0.01)
        else:
            raw = pd.Series(1.0, index=candidates["symbol"], dtype=float)
        raw = raw / raw.sum()

        invest_weight = 1.0 - cash_floor
        caps = {asset.symbol: asset.max_weight for asset in config.enabled_assets}
        capped = cap_weights(raw * invest_weight, caps, invest_weight)
        weights.loc[capped.index] = capped
        weights[config.cash_symbol] = 1.0 - weights.sum()

        if current_drawdown >= config.portfolio.risk_reduce_drawdown:
            risk_symbols = [asset.symbol for asset in config.by_role("risk")]
            reduction = weights.loc[risk_symbols].sum() * 0.5
            weights.loc[risk_symbols] *= 0.5
            weights = add_to_defensive_or_cash(config, weights, reduction)
        return normalize_weights(weights)


def candidate_table(prices: pd.DataFrame, config: StrategyConfig, provider: BasicStrategyProvider) -> pd.DataFrame:
    try:
        table = signal_table(prices, config, prices.index[-1])
    except ValueError:
        return pd.DataFrame()

    risk = table[(table["role"] == "risk") & table["symbol"].map(lambda symbol: is_affordable(symbol, table, config))].copy()
    if risk.empty:
        return risk

    rows: list[dict[str, float | str | bool]] = []
    for _, row in risk.iterrows():
        symbol = str(row["symbol"])
        close = prices[symbol].dropna()
        if len(close) <= max(provider.trend_window, provider.momentum_window, provider.volatility_window):
            continue
        current = float(close.iloc[-1])
        trend_ma = float(close.iloc[-provider.trend_window :].mean())
        trend_ok = current > trend_ma
        momentum = current / float(close.iloc[-provider.momentum_window - 1]) - 1.0
        fast_momentum = current / float(close.iloc[-provider.fast_momentum_window - 1]) - 1.0
        volatility = float(close.pct_change().dropna().iloc[-provider.volatility_window :].std() * np.sqrt(252))
        rows.append(
            {
                "symbol": symbol,
                "trend_ok": trend_ok,
                "momentum": momentum,
                "fast_momentum": fast_momentum,
                "volatility": volatility,
                "score": fast_momentum + momentum - 0.25 * volatility,
            }
        )
    return pd.DataFrame(rows)


def apply_mode_filters(table: pd.DataFrame, mode: str) -> pd.DataFrame:
    if mode == "equal_weight":
        table = table.copy()
        table["score"] = 1.0
        return table
    if mode == "inverse_volatility":
        table = table.copy()
        table["score"] = -table["volatility"]
        return table
    if mode == "trend_equal_weight":
        filtered = table[table["trend_ok"]].copy()
        filtered["score"] = 1.0
        return filtered
    if mode == "trend_inverse_volatility":
        filtered = table[table["trend_ok"]].copy()
        filtered["score"] = -filtered["volatility"]
        return filtered
    if mode == "dual_momentum":
        return table[(table["trend_ok"]) & (table["momentum"] > 0.0)].copy()
    raise ValueError(f"Unknown basic strategy mode: {mode}")


def default_basic_strategy_providers() -> list[BasicStrategyProvider]:
    return [
        BasicStrategyProvider(name="equal_weight", mode="equal_weight"),
        BasicStrategyProvider(name="inverse_volatility", mode="inverse_volatility"),
        BasicStrategyProvider(name="trend_equal_weight", mode="trend_equal_weight"),
        BasicStrategyProvider(name="trend_inverse_volatility", mode="trend_inverse_volatility"),
        BasicStrategyProvider(name="dual_momentum", mode="dual_momentum"),
    ]


def compare_basic_strategies(
    prices: pd.DataFrame,
    config: StrategyConfig,
    out_dir: str | Path,
) -> pd.DataFrame:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, float | str]] = []
    results: dict[str, BacktestResult] = {}
    rule_result = run_backtest(prices, config)
    results["rule_current"] = rule_result
    rows.append({"strategy": "rule_current", **rule_result.summary})

    for provider in default_basic_strategy_providers():
        result = run_backtest(prices, config, weight_provider=provider)
        results[provider.name] = result
        rows.append({"strategy": provider.name, **result.summary})

    summary = pd.DataFrame(rows)
    summary.to_csv(out / "basic_strategy_summary.csv", index=False)
    for name, result in results.items():
        write_backtest_outputs(result, out / name)
    (out / "basic_strategy_report.md").write_text(render_basic_strategy_report(summary), encoding="utf-8")
    return summary


def render_basic_strategy_report(summary: pd.DataFrame) -> str:
    lines = ["# Basic Quant Strategy Comparison", ""]
    display_columns = [
        "strategy",
        "end_value_jpy",
        "total_return",
        "cagr",
        "volatility",
        "sharpe_like",
        "max_drawdown",
        "rebalance_count",
        "excess_return_vs_benchmark",
    ]
    available = [column for column in display_columns if column in summary.columns]
    lines.extend(render_markdown_table(summary[available]))
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- These are simple baselines for comparison, not preferred live strategies by default.",
            "- All variants still use the same configured capital, trade costs, max positions, weight caps, and affordability constraints.",
            "- Use the current rule strategy or ML overlay only if it beats these simple baselines after costs and drawdown checks.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_markdown_table(frame: pd.DataFrame) -> list[str]:
    if frame.empty:
        return ["No results."]
    header = "| " + " | ".join(frame.columns) + " |"
    separator = "| " + " | ".join(["---"] * len(frame.columns)) + " |"
    rows = [header, separator]
    for _, row in frame.iterrows():
        values = [render_table_value(row[column]) for column in frame.columns]
        rows.append("| " + " | ".join(values) + " |")
    return rows


def render_table_value(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)
