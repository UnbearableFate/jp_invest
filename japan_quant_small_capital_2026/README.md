# Japan Quant Small-Capital Strategy 2026

创建日期：2026-05-29  
工作流：academic-research-suite / deep-research + experiment-agent plan  
状态：研究综述、策略规格与回测计划；不是个性化投资建议。

## Core Conclusion

最新量化研究显示，transformer、LLM、多智能体和情绪信号正在快速进入量化研发流程，但日本小额账户的第一约束是执行可行性：100 股个股交易单位、分散化不足、交易成本、现金拖累、NISA 账户限制和数据可得性。因此，本项目建议采用分层策略：

1. **v1 实盘候选**：日本 ETF trend / relative momentum / volatility sizing，月度再平衡，低换手。
2. **研究型卫星**：日本个股 value-quality-momentum-low-volatility 复合因子，先纸面回测并加入 100 股 affordability 约束。
3. **v2/v3 增强**：日文披露/新闻文本情绪和 LLM 模块，仅在严格 walk-forward 和成本扣除后引入。

## Files

| File | Purpose |
|---|---|
| `research_question_brief.md` | ARS 风格研究问题、FINER 评分、范围边界。 |
| `paper_index.md` | 检索策略、论文/官方来源索引、下载状态。 |
| `paper_index.bib` | 可复用 BibTeX 条目。 |
| `source_verification.md` | 来源质量矩阵、风险标记、核验限制。 |
| `japan_quant_lit_review.md` | 综合综述、主题、矛盾处理、知识缺口、devil's advocate 检查。 |
| `small_capital_strategy_spec.md` | 日本小额账户 v1 策略规格。 |
| `backtest_plan.md` | experiment-agent 风格回测和实验计划。 |
| `papers/` | 已下载 PDF；SSRN/ScienceDirect/官方网页以 metadata-only 记录。 |

## First Implementation Target

先实现 ETF core backtest：

- 日本 broad-market ETF / J-REIT / defensive sleeve。
- 10-month moving average + 6-month positive return trend filter。
- 6-month risk-adjusted relative momentum。
- 8-12% target volatility sizing。
- 月度再平衡，下一交易日执行，扣 5/10/20 bps 成本。
- 与 buy-and-hold TOPIX/Nikkei proxy、现金/防御基准比较。

