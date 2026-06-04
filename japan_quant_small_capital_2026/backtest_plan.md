# Backtest and Experiment Plan

创建日期：2026-05-29  
工作流：academic-research-suite / experiment-agent plan  
状态：设计计划；尚未执行回测

## Material Passport

- **Material ID**: `japan_quant_small_capital_2026_backtest_plan`
- **Type**: code experiment plan
- **Research question**: Can a low-frequency, low-cost Japan ETF/factor strategy provide better risk-adjusted outcomes than simple buy-and-hold under small-capital constraints?
- **Data status**: not yet ingested
- **Verification status**: PLANNED

## Hypotheses

H1: A monthly ETF trend/relative-momentum strategy reduces maximum drawdown versus buy-and-hold TOPIX/Nikkei exposure after realistic costs.

H2: A value-quality-momentum-low-volatility composite improves paper portfolio risk-adjusted return versus a simple TOPIX universe benchmark, but becomes hard to deploy under small account and 100-share lot constraints.

H3: Japanese text/LLM sentiment adds incremental predictive value only after controlling for momentum, value, quality, volatility, industry and market beta; if not, it should remain excluded from v1.

## Variables

**Independent variables**
- Lookback window: 3, 6, 10, 12 months.
- Rebalance frequency: monthly, quarterly.
- Risk target: 8%, 10%, 12% annual volatility.
- Transaction cost: ETF 0/5/10/20 bps; stock 25/50/100 bps.
- Capital path: initial amount + monthly contribution scenarios.

**Dependent variables**
- CAGR, annualized volatility, Sharpe, Sortino, maximum drawdown.
- Turnover, number of trades, cash drag, cost drag.
- Benchmark excess return and information ratio.
- For stock satellite: affordability-adjusted diversification, realized number of holdings, sector concentration.

**Controls**
- Benchmark: buy-and-hold TOPIX ETF proxy, Nikkei 225 ETF proxy, cash/defensive baseline.
- No look-ahead: all fundamentals and text data lagged by availability date.
- Survivorship control: use historical constituents when available; otherwise flag limitation explicitly.

## Data Plan

1. **ETF prices**: JPX/J-Quants or other licensed historical price source with adjusted close and dividends.
2. **Stock prices and fundamentals**: J-Quants daily quotes, listed information, financial statements, dividends.
3. **Corporate actions**: splits, dividends, trading suspensions.
4. **Text module v2**: Japanese disclosures/news with timestamps; use only if licensing and timestamp integrity are clear.
5. **Policy/account constraints**: NISA rules are treated as account wrapper assumptions, not strategy alpha.

## Experiment Steps

1. Build data loader and normalized calendar for Japanese trading days.
2. Implement ETF core signals:
   - monthly signal date,
   - absolute trend filter,
   - relative momentum rank,
   - volatility sizing,
   - next-day execution.
3. Implement small-capital simulator:
   - integer units,
   - uninvested cash,
   - monthly contributions,
   - cost scenarios.
4. Implement stock factor paper portfolio:
   - universe filters,
   - factor winsorization/z-scoring,
   - sector neutralization optional,
   - 100-share affordability report.
5. Run walk-forward analysis:
   - no training on future data,
   - yearly performance decomposition,
   - crisis-period stress tests.
6. Produce markdown report with tables and charts.

## Acceptance Criteria

- Signals are timestamp-safe and do not use same-day close as executable price.
- All results are shown net of at least one conservative cost scenario.
- ETF core must be compared to buy-and-hold and cash/defensive baseline.
- Stock satellite must report how many stocks are actually affordable under each capital scenario.
- Any LLM/text module must show ablation value after standard factors; otherwise it is rejected from strategy.

## Planned Output Files

- `data_dictionary.md`: source fields, dates, adjustment policy.
- `etf_core_backtest.csv`: monthly portfolio state and trades.
- `factor_satellite_backtest.csv`: paper stock portfolio state and trades.
- `performance_report.md`: metrics, charts, sensitivity analysis.
- `execution_constraints.md`: minimum lot, cash drag, cost and NISA assumptions.

