# Source Verification Report

检索日期：2026-05-29  
工作流：academic-research-suite / deep-research / source_verification_agent

## Overall Assessment

**Sources reviewed**: 17  
**Verified**: 17 | **Flagged**: 3 | **Rejected**: 0

核验结论：本项目证据足够支持“研究综述 + 策略规格 + 回测计划”。证据不足以支持任何保证收益、个性化投资建议、或“LLM 直接自动交易优于简单策略”的结论。

## Source Quality Matrix

| Source | Level | Venue | Method | Currency | COI / risk | Overall |
|---|---|---|---|---|---|---|
| R&D-Agent-Quant (arXiv 2025) | VI | pass | empirical/system prototype | pass | author/tooling incentives possible | Include with caveat |
| LLM + RL + sentiment trading (arXiv 2025) | VI | pass | empirical trading prototype | pass | overfitting and benchmark risk | Include as research module only |
| QuantAgent HFT (arXiv 2025) | VI | pass | HFT/multi-agent prototype | pass | not retail-executable | Exclude from v1 live strategy |
| Transformer vs simple neural networks (Finance Research Letters 2025) | III/VI | pass | empirical ML forecasting | pass | paywalled full text | Include as ML evidence |
| AI Asset Pricing Models (SSRN 2025) | V/VI | pass | asset-pricing framework/review | pass | working-paper status | Include with caveat |
| Alpha Go Everywhere (SSRN 2020) | III/VI | pass | international empirical ML | warn: older but foundational | working-paper status | Include as foundation |
| Do LLMs Trade? (arXiv 2025) | VI | pass | market simulation | pass | simulation-real gap | Include with caveat |
| LLM Agent in Financial Trading Survey (arXiv 2024) | V | pass | literature survey | pass | survey not primary performance evidence | Include |
| LLM + RL sentiment-driven quant trading (arXiv 2025) | VI | pass | sentiment/RL trading prototype | pass | resource and overfitting risk | Include as boundary evidence |
| JSAI Japanese 10-K LLM sentiment (J-STAGE 2025) | VI | pass | Japanese disclosure sentiment prediction | pass | conference paper | Include |
| CIRJE expert-knowledge sentiment (2025) | VI | pass | Japan empirical working paper | pass | working paper | Include |
| Japanese momentum credit distortions (JBF 2025) | III/VI | pass | empirical finance | pass | paywalled full text | Include |
| JPX trading unit | official | pass | exchange rule | pass | none | Include as hard constraint |
| JPX ETF outline | official | pass | market product info | pass | none | Include |
| JPX J-Quants API | official | pass | data service | pass | data coverage/subscription limits | Include |
| J-Quants daily quotes docs | official | pass | API schema | pass | API availability limits | Include |
| FSA NISA basics | official | pass | policy/tax wrapper | pass | not personalized tax advice | Include as constraint |

## Flagged Sources

### QuantAgent HFT

- **Issue**: 核心场景是高频交易和多智能体系统，依赖小额个人投资者无法获得的执行基础设施。
- **Severity**: Medium
- **Recommendation**: 保留为“研究前沿”证据，但不进入 v1 实盘策略。

### LLM/RL trading prototypes

- **Issue**: 研究常见风险是回测过拟合、成本建模不足、市场冲击缺失、样本外退化。
- **Severity**: Medium
- **Recommendation**: 只作为后续实验模块；v1 先使用规则透明的动量/趋势/波动率模型。

### SSRN and paywalled publisher sources

- **Issue**: 部分 PDF 无法本地归档，且工作论文或付费全文限制会降低逐句复核能力。
- **Severity**: Low
- **Recommendation**: 使用摘要页/出版商页进行存在性核验；关键结论不得超过可核验摘要和公开信息。

## Predatory Journal Alerts

未发现明显掠夺性出版风险。arXiv/SSRN 工作论文需按未同行评审或预印本处理。

## Conflict of Interest Disclosures

工具型/框架型论文可能存在作者对自建系统的正向展示偏差。策略设计中已将这些论文降级为“研究方向”和“后续实验”，而不是实盘核心依据。

## Verification Limitations

- 未进行 Semantic Scholar API 全覆盖去重；本轮用来源主页、官方网页、arXiv/SSRN/出版商页面和 PDF 下载结果进行存在性核验。
- 没有访问付费全文，因此对 R4/R12 的细节只使用公开摘要和出版商元数据。
- 未使用券商实时费率表；策略规格采用成本压力测试而不是特定券商假设。
