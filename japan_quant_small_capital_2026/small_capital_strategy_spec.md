# 策略规格：日本市场小额量化投资 v1

创建日期：2026-05-29  
状态：研究规格，不是实盘建议  
目标：用低频、低换手、低复杂度策略，把最新量化研究转化为日本市场小额账户可回测方案。

## Design Principles

1. **先可执行，再复杂**：小额资金优先 ETF 和少仓位；复杂 ML/LLM 只作为研究增强。
2. **低换手**：月度再平衡；优先用新增资金调整权重，减少卖出。
3. **规则透明**：所有信号可用行情、财务、分红和公开文本复现。
4. **无杠杆、无卖空、无高频**：不依赖个人投资者难以获得的基础设施。
5. **成本先行**：回测必须先扣交易成本、滑点、分红/除权处理和现金拖累。

## Strategy Layers

### Layer A: ETF Core Trend and Relative Momentum

**Purpose**: 作为可实际部署的第一层策略，适合小额资金和 NISA/定投场景。

**Universe**
- 日本宽基股票 ETF：TOPIX 或 Nikkei 225 暴露。
- 日本 REIT ETF：可选，用作日本风险资产分散。
- 防御资产：现金、货币基金或短久期债券类工具；具体产品在部署时按券商可得性确认。

**Signals**
- Absolute trend: risk asset is eligible if latest monthly close is above 10-month moving average and 6-month total return is positive.
- Relative momentum: among eligible risk assets, rank by 6-month return divided by 6-month realized volatility.
- Volatility sizing: target annualized volatility 8-12%; exposure = min(100%, target_vol / realized_vol_60d).
- Defensive switch: if no risk asset passes absolute trend, hold defensive asset/cash.

**Portfolio construction**
- Hold 1-2 risk ETFs plus defensive sleeve.
- Rebalance monthly after close, next trading day execution.
- Minimum trade rule: if contribution or rebalance amount is smaller than one trade unit plus cost buffer, hold cash until next month.
- Max single risk ETF weight: 80%; max total equity/J-REIT risk exposure: 90%.

**Why this fits small capital**
- ETF can usually be bought in small units and is more diversified than a 100-share individual stock lot.
- Low turnover reduces fees and behavioral mistakes.
- Signal does not require paid alternative data or LLM infrastructure.

### Layer B: Individual Stock Factor Satellite

**Purpose**: 研究层或小比例卫星层，用来吸收资产定价和日本本土因子研究。

**Universe filter**
- TSE Prime / TOPIX 500-style liquid universe.
- Exclude stocks with insufficient price history, very low liquidity, severe trading suspension, missing fundamentals, or extreme one-off accounting anomalies.
- Apply 100-share minimum-lot affordability constraint before live deployment; if account cannot hold at least 20-30 names, keep this layer paper-only or use fractional-share services with explicit cost modeling.

**Composite score**
- Momentum: 12-1 month return or 6-1 month return, winsorized by industry.
- Value: earnings yield, book-to-market, dividend yield where available.
- Quality: ROE, operating margin, equity ratio, accruals/earnings stability.
- Low volatility: trailing 6-12 month realized volatility and downside volatility.
- Liquidity: turnover and bid-ask proxy; low-liquidity names penalized.

**Construction**
- Long-only top decile/quintile after filters.
- Rebalance monthly or quarterly; quarterly preferred for taxable/cost-sensitive deployment.
- Industry cap: max 25% per sector.
- Name cap: max 5% per stock in paper portfolio; live account can only deploy if minimum lot constraint permits.

### Layer C: Japanese Text / LLM Sentiment Research Module

**Purpose**: 后续增强，不进入 v1 实盘核心。

**Candidate inputs**
- Japanese company disclosures, earnings summaries, TDnet-style announcements, curated news sentiment.
- LLM or smaller Japanese financial sentiment model output converted to numeric surprise/sentiment features.

**Strict gates before use**
- Publication-time lag enforced: signal can only use text available before the trade timestamp.
- Walk-forward validation by year and industry.
- Cost and turnover adjusted performance must beat Layer B without sentiment.
- Feature ablation must show sentiment adds value beyond momentum, value, quality and industry exposure.

## Risk Controls

- No margin, no leverage, no options, no short selling in v1.
- Keep emergency cash outside the strategy; do not force full investment.
- Max monthly turnover target: ETF core < 50%; stock satellite < 100% quarterly.
- Drawdown monitor: if strategy drawdown exceeds 20%, freeze new risk increases and continue only rule-based reductions; do not discretionary average down.
- Concentration rule: if only one ETF is held, exposure is capped below 90% unless long-term investor explicitly accepts full equity beta.

## Execution Rules

- Compute signals using adjusted close/total return data where available.
- Execute only at next session open/close after signal date; never use same-day close as executable price.
- Include conservative transaction cost scenarios:
  - ETF core: 5, 10, 20 bps one-way.
  - Stock satellite: 25, 50, 100 bps one-way.
- Include cash drag and uninvested cash from minimum trade size.
- Use NISA only as an account wrapper in analysis; never assume tax-free status unless the instrument/account is eligible.

## Recommended v1 Output

The first implementation should produce:

1. Monthly ETF core backtest against TOPIX/Nikkei buy-and-hold.
2. Same strategy under 0, 10, 20 bps ETF cost scenarios.
3. Contribution-aware simulation for small monthly investment amounts.
4. Paper-only individual stock factor model with 100-share affordability constraint.
5. Sensitivity report: signal lookback 3/6/10/12 months, rebalance monthly vs quarterly, target volatility 8/10/12%.

