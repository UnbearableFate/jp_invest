from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd

from .config import StrategyConfig
from .portfolio import target_weights as rule_target_weights
from .signals import latest_signal_table, rebalance_dates


class ModelScoreProvider(Protocol):
    def predict_scores(
        self,
        prices: pd.DataFrame,
        config: StrategyConfig,
        asof: pd.Timestamp | None = None,
    ) -> pd.Series: ...


class WeightProvider(Protocol):
    name: str

    def target_weights(
        self,
        prices: pd.DataFrame,
        config: StrategyConfig,
        asof: pd.Timestamp | None = None,
        current_drawdown: float = 0.0,
    ) -> pd.Series: ...


@dataclass(frozen=True)
class BacktestResult:
    equity_curve: pd.DataFrame
    weights: pd.DataFrame
    trades: pd.DataFrame
    signals: pd.DataFrame
    summary: dict[str, float | str]


def run_backtest(
    prices: pd.DataFrame,
    config: StrategyConfig,
    model_provider: ModelScoreProvider | None = None,
    model_weight: float = 0.0,
    weight_provider: WeightProvider | None = None,
) -> BacktestResult:
    prices = prices.copy().sort_index()
    returns = prices.pct_change().fillna(0.0)
    regular_rebalances = set(rebalance_dates(prices, config.portfolio.rebalance))
    risk_checks = set(rebalance_dates(prices, config.portfolio.risk_check))

    value = float(config.portfolio.capital_jpy)
    weights = pd.Series(0.0, index=config.symbols, dtype=float)
    weights[config.cash_symbol] = 1.0

    peak = value
    equity_rows: list[dict[str, float | str]] = []
    weight_rows: list[dict[str, float | str]] = []
    trade_rows: list[dict[str, float | str]] = []

    for date, day_returns in returns.iterrows():
        value *= float(1.0 + (weights * day_returns.reindex(weights.index).fillna(0.0)).sum())
        peak = max(peak, value)
        drawdown = 1.0 - value / peak if peak > 0 else 0.0

        risk_rebalance = date in risk_checks and drawdown >= config.portfolio.risk_reduce_drawdown
        if (
            (date in regular_rebalances or risk_rebalance)
            and len(prices.loc[:date]) >= config.signals.min_history_days
        ):
            if weight_provider is not None:
                target = weight_provider.target_weights(prices.loc[:date], config, date, drawdown)
            else:
                model_scores = predict_model_scores(model_provider, prices.loc[:date], config, date, model_weight)
                target = rule_target_weights(
                    prices.loc[:date],
                    config,
                    date,
                    drawdown,
                    model_scores=model_scores,
                    model_weight=model_weight,
                )
            turnover_by_asset = (target - weights).abs()
            if float(turnover_by_asset.sum()) <= 1e-10:
                continue
            cost = estimate_trade_cost(value, turnover_by_asset, config)
            value -= cost

            trade_row = {"date": date.date().isoformat(), "portfolio_value": value, "cost_jpy": cost}
            trade_row.update({symbol: turnover_by_asset[symbol] for symbol in config.symbols})
            trade_rows.append(trade_row)

            weights = target
            weight_row = {"date": date.date().isoformat(), "portfolio_value": value}
            weight_row.update({symbol: weights[symbol] for symbol in config.symbols})
            weight_rows.append(weight_row)

        equity_rows.append(
            {
                "date": date.date().isoformat(),
                "portfolio_value": value,
                "drawdown": drawdown,
            }
        )

    equity = pd.DataFrame(equity_rows)
    weights_df = pd.DataFrame(weight_rows)
    trades = pd.DataFrame(trade_rows)
    latest_scores = predict_model_scores(model_provider, prices, config, prices.index[-1], model_weight)
    signals = latest_signal_table(prices, config, model_scores=latest_scores, model_weight=model_weight)
    summary = summarize_backtest(equity, trades, config, prices)
    if weight_provider is not None:
        summary["strategy_name"] = weight_provider.name
    return BacktestResult(equity, weights_df, trades, signals, summary)


def predict_model_scores(
    model_provider: ModelScoreProvider | None,
    prices: pd.DataFrame,
    config: StrategyConfig,
    asof: pd.Timestamp,
    model_weight: float,
) -> pd.Series | None:
    if model_provider is None or model_weight <= 0:
        return None
    return model_provider.predict_scores(prices, config, asof)


def estimate_trade_cost(value: float, turnover_by_asset: pd.Series, config: StrategyConfig) -> float:
    cost = 0.0
    for symbol, turnover in turnover_by_asset.items():
        asset = config.asset(symbol)
        if asset.role == "cash":
            continue
        bps = asset.slippage_bps or config.portfolio.transaction_cost_bps
        cost += value * float(turnover) * bps / 10000.0
    return cost


def summarize_backtest(
    equity: pd.DataFrame,
    trades: pd.DataFrame,
    config: StrategyConfig,
    prices: pd.DataFrame,
) -> dict[str, float | str]:
    start_value = float(config.portfolio.capital_jpy)
    end_value = float(equity["portfolio_value"].iloc[-1])
    daily = equity["portfolio_value"].pct_change().dropna()
    total_return = end_value / start_value - 1.0
    years = max(len(equity) / 252.0, 1e-9)
    cagr = (end_value / start_value) ** (1.0 / years) - 1.0
    volatility = float(daily.std() * np.sqrt(252)) if len(daily) else 0.0
    sharpe = float(cagr / volatility) if volatility > 0 else 0.0
    max_drawdown = float(equity["drawdown"].max())
    total_cost = float(trades["cost_jpy"].sum()) if not trades.empty else 0.0
    rebalance_count = int(len(trades))
    summary: dict[str, float | str] = {
        "start_value_jpy": start_value,
        "end_value_jpy": end_value,
        "total_return": total_return,
        "cagr": cagr,
        "volatility": volatility,
        "sharpe_like": sharpe,
        "max_drawdown": max_drawdown,
        "total_cost_jpy": total_cost,
        "rebalance_count": rebalance_count,
        "pass_drawdown_target": str(max_drawdown <= config.portfolio.max_drawdown_target),
    }
    add_benchmark_summary(summary, equity, prices, config)
    return summary


def add_benchmark_summary(
    summary: dict[str, float | str],
    equity: pd.DataFrame,
    prices: pd.DataFrame,
    config: StrategyConfig,
) -> None:
    benchmark_symbol = config.portfolio.benchmark_symbol
    if not benchmark_symbol or benchmark_symbol not in prices.columns:
        return

    dates = pd.to_datetime(equity["date"])
    benchmark = prices.loc[dates.min() : dates.max(), benchmark_symbol].dropna()
    if benchmark.empty:
        return

    start_value = float(config.portfolio.capital_jpy)
    values = start_value * benchmark / float(benchmark.iloc[0])
    daily = values.pct_change().dropna()
    years = max(len(values) / 252.0, 1e-9)
    end_value = float(values.iloc[-1])
    total_return = end_value / start_value - 1.0
    cagr = (end_value / start_value) ** (1.0 / years) - 1.0
    drawdown = 1.0 - values / values.cummax()
    volatility = float(daily.std() * np.sqrt(252)) if len(daily) else 0.0
    summary.update(
        {
            "benchmark_symbol": benchmark_symbol,
            "benchmark_end_value_jpy": end_value,
            "benchmark_total_return": total_return,
            "benchmark_cagr": cagr,
            "benchmark_volatility": volatility,
            "benchmark_max_drawdown": float(drawdown.max()),
            "excess_return_vs_benchmark": float(summary["total_return"]) - total_return,
        }
    )


def write_backtest_outputs(result: BacktestResult, out_dir: str | Path) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result.equity_curve.to_csv(out / "equity_curve.csv", index=False)
    result.weights.to_csv(out / "weights.csv", index=False)
    result.trades.to_csv(out / "trades.csv", index=False)
    result.signals.to_csv(out / "signals.csv", index=False)
    (out / "backtest_report.md").write_text(render_report(result), encoding="utf-8")


def render_report(result: BacktestResult) -> str:
    lines = ["# Backtest Report", ""]
    for key, value in result.summary.items():
        if isinstance(value, float):
            if "return" in key or "cagr" in key or "volatility" in key or "drawdown" in key:
                rendered = f"{value:.2%}"
            else:
                rendered = f"{value:,.2f}"
        else:
            rendered = str(value)
        lines.append(f"- **{key}**: {rendered}")

    if not result.weights.empty:
        lines.extend(["", "## Last Target Weights", ""])
        last = result.weights.iloc[-1]
        for symbol, value in last.items():
            if symbol in {"date", "portfolio_value"}:
                continue
            lines.append(f"- {symbol}: {float(value):.2%}")

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Costs include configured slippage/spread assumptions only.",
            "- Taxes, fund expense ratios, and dividends are not modeled in this minimal prototype.",
            "- Use broker-confirmed prices and availability before placing real orders.",
        ]
    )
    return "\n".join(lines) + "\n"
