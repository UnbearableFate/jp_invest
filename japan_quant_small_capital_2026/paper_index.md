# Paper and Source Index: Japan Quant Small-Capital Strategy

检索日期：2026-05-29  
主题：最新量化投资研究、日本市场约束、小额资金可执行策略  
说明：PDF 能下载的来源已归档到 `papers/`；SSRN/ScienceDirect/官方网页等不能稳定下载的来源以网页核验和元数据记录为主。

## Search Strategy

**Databases / sources**
- arXiv, SSRN, ScienceDirect, J-STAGE, University of Tokyo CIRJE, JPX, J-Quants, FSA.

**Keywords**
- `quantitative trading`, `machine learning asset pricing`, `stock return prediction`, `large language model financial trading`, `LLM trading agent`, `Japan stock market`, `TOPIX`, `Japanese momentum`, `J-Quants`, `NISA`, `trading unit Japan`.

**Date range**
- 重点纳入 2024-2026；保留少量更早但对“国际股票收益机器学习”有基础意义的研究。

**Inclusion criteria**
- 直接涉及量化交易、机器学习/LLM 资产定价、股票收益预测、交易代理、投资因子、日本市场或日本投资制度。
- 可核验来源：论文主页、DOI/出版商页面、arXiv、SSRN、J-STAGE、大学工作论文、政府/交易所官方页面。
- 能对低频、小额、日本市场策略设计提供约束或可转化信号。

**Exclusion criteria**
- 纯加密货币、纯高频做市、不可复现营销材料、没有可核验来源的二手博客。
- 只报告回测收益而没有清晰方法、数据或成本处理的来源。

## Included Research Sources

| ID | Source | Year | Local file | Role in this project | Verification |
|---|---:|---:|---|---|---|
| R1 | [R&D-Agent-Quant: A Multi-Agent Framework for Data-Centric Factors and Model Joint Optimization](https://arxiv.org/abs/2505.15155) | 2025 | `papers/2505.15155_rd_agent_quant.pdf` | 说明 2025 年量化研究自动化从“找模型”转向“数据/因子/模型联合优化”；适合作为研究流程参考，不适合直接给小额账户上线。 | arXiv verified |
| R2 | [Language Model Guided Reinforcement Learning in Quantitative Trading](https://arxiv.org/abs/2508.02366) | 2025 | `papers/2508.02366_llm_guided_rl_quant_trading.pdf` | 展示 LLM 指导 RL 交易的研究方向；实盘风险较高，适合作为后续实验模块。 | arXiv verified |
| R3 | [QuantAgent: Price-Driven Multi-Agent LLMs for High-Frequency Trading](https://arxiv.org/abs/2509.09995) | 2025 | `papers/2509.09995_quantagent_hft.pdf` | 代表 LLM 多智能体交易研究的高复杂度方向；因 HFT/基础设施要求，不纳入小额 v1 实盘。 | arXiv verified |
| R4 | [Machine learning for stock return prediction: Transformers or simple neural networks](https://www.sciencedirect.com/science/article/pii/S1544612325020379) | 2025 | metadata only | 最新 transformer 与简单神经网络股票收益预测比较；支持把机器学习作为因子融合研究，但需防过拟合。 | ScienceDirect verified |
| R5 | [Artificial Intelligence Asset Pricing Models](https://ssrn.com/abstract=5089371) | 2025 | metadata only | 资产定价中 AI/ML 模型的综述性和框架性证据；用于评价复杂模型是否值得引入。 | SSRN verified, PDF 403 |
| R6 | [Alpha Go Everywhere: Machine Learning and International Stock Returns](https://ssrn.com/abstract=3489679) | 2020 | metadata only | 国际股票收益机器学习的基础证据；提醒日本市场策略需要跨市场泛化验证。 | SSRN verified, PDF 403 |
| R7 | [Can Large Language Models Trade? Testing Financial Theories with LLM Agents in Market Simulations](https://arxiv.org/abs/2504.10789) | 2025 | `papers/2504.10789_llm_trade_market_simulations.pdf` | 用模拟市场检验 LLM 交易行为；对“LLM 是否能直接交易”持保守参考价值。 | arXiv verified |
| R8 | [A Survey of Large Language Model Agent in Financial Trading](https://arxiv.org/abs/2408.06361) | 2024 | `papers/2408.06361_llm_agent_financial_trading_survey.pdf` | 梳理 LLM 交易代理研究生态；用于区分研究原型和可执行个人策略。 | arXiv verified |
| R9 | [Integrating Large Language Models and Reinforcement Learning for Sentiment-Driven Quantitative Trading](https://arxiv.org/abs/2510.10526) | 2025 | `papers/2510.10526_fingpt_rl_sentiment_trading.pdf` | 说明金融 LLM 情绪信号与 RL 集成的研究方向；小额策略不应以训练或自动执行大模型为前提。 | arXiv verified |
| R10 | [Revealing Hidden Alpha in Large-Cap Stocks: LLM-Driven Sentiment Analysis of Japanese 10-K Reports](https://www.jstage.jst.go.jp/article/pjsai/JSAI2025/0/JSAI2025_1H3OS8a05/_article/-char/en) | 2025 | `papers/jsai2025_japanese_llm_sentiment_topix.pdf` | 日本大盘股披露文本情绪与 TOPIX 100/500 股票收益预测的直接证据；适合作为日文文本信号候选。 | J-STAGE verified |
| R11 | [Investment with New Sentiment Analysis in Japanese Stock Market: Expert Knowledge Can Still Outperform ChatGPT](https://www.cirje.e.u-tokyo.ac.jp/research/dp/2025/2025cf1248.pdf) | 2025 | `papers/cirje_2025cf1248_expert_knowledge_sentiment.pdf` | 日本新闻标题情绪、专家词典和 ChatGPT 情绪比较的本土证据；支持构建“市场数据校准的日文情绪”模块。 | CIRJE verified |
| R12 | [Credit distortions in Japanese momentum](https://www.sciencedirect.com/science/article/abs/pii/S0927539825000374) | 2025 | metadata only | 日本动量策略的本土约束：僵尸企业和银行信用扭曲会削弱朴素动量。 | ScienceDirect verified |

## Included Market / Data / Policy Sources

| ID | Source | Relevance |
|---|---|---|
| M1 | [JPX: Trading Unit](https://www.jpx.co.jp/english/equities/trading/domestic/03.html) | 日本国内股票交易单位已标准化为 100 股；这直接影响小额个股分散化。 |
| M2 | [JPX: ETF Outline](https://www.jpx.co.jp/english/equities/products/etfs/etf-outline/) | JPX 官方将 ETF 描述为可通过证券公司交易、透明度高、成本较低、可从相对较小金额开始；支持 v1 使用 ETF 核心。 |
| M3 | [JPX: J-Quants API](https://www.jpx.co.jp/english/markets/other-data-services/j-quants-api/index.html) | 官方数据 API，覆盖日本金融数据和 API 访问；适合作为回测数据主源。 |
| M4 | [J-Quants API Reference: Daily Quotes](https://jpx.gitbook.io/j-quants-en/api-reference/daily_quotes) | 提供每日行情字段说明；适合实现可复现回测管线。 |
| M5 | [FSA: NISA basics and 2024 system expansion](https://www.fsa.go.jp/policy/nisa2/about/nisa/start/index.html) | 新 NISA 对小额长期投资极重要；策略文档只作为制度约束，不提供税务建议。 |

## Download Notes

- 成功下载：R1, R2, R3, R7, R8, R9, R10, R11。
- 未下载但网页核验：R4, R5, R6, R12, M1-M5。
- SSRN PDF 直链返回 403，因此保留 metadata-only 记录；不要在后续报告中声称 SSRN PDF 已本地归档。
