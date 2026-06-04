# Rakuten Quant

乐天证券用的低频量化交易原型：用J-Quants真实日线数据，生成“今天应该买/卖什么”的手工下单清单。策略是长仓、无杠杆、无金融衍生品，默认本金约20万日元。

这不是投资建议，也不保证收益。下单前必须自己在乐天证券确认价格、可买数量、NISA/特定口座设置和交易成本。

## 一次设置

只需要设置一次J-Quants API key。不要把key写进文件。

```bash
cd "/Users/unbearablefate/Documents/New project"
export JQUANTS_API_KEY="你的J-Quants API key"
```

当前项目使用 PyTorch Transformer，先在项目里的`.venv`安装依赖：

```bash
uv pip install -r requirements.txt
```

## 一步生成推荐下单清单

```bash
./scripts/recommend.sh
```

这个命令会自动完成：

1. 从J-Quants下载最新可用日线到`data/jquants_prices.csv`
2. 运行回测并写入`reports/jquants/backtest_report.md`
3. 生成最新信号到`reports/jquants/latest_signals.csv`
4. 生成推荐下单清单到`reports/jquants/orders.csv`
5. 在终端打印需要执行的`BUY`/`SELL`

## 如果你已有持仓

在项目根目录创建`positions.csv`：

```csv
symbol,units
1475,137
1540,2
2559,2
```

然后还是执行同一个命令：

```bash
./scripts/recommend.sh
```

脚本会自动读取`positions.csv`，只输出需要调仓的差额订单。

## 常用命令

复用已有行情，不重新请求J-Quants：

```bash
./scripts/recommend.sh --use-existing-prices
```

指定数据区间：

```bash
./scripts/recommend.sh --start 2021-05-29 --end 2026-05-29
```

指定持仓文件：

```bash
./scripts/recommend.sh --positions my_positions.csv
```

使用更激进的benchmark-chase配置：

```bash
./scripts/recommend.sh --config configs/strategy_aggressive.toml
```

使用扩展资产池配置，纳入ブル/ベア、贵金属、东证上市美股ETF：

```bash
./scripts/recommend.sh --config configs/strategy_extended.toml --out-dir reports/jquants_extended
```

比较几种基础量化策略：

```bash
PYTHONPATH=src .venv/bin/python -m rakuten_quant.cli strategy-compare \
  --config configs/strategy_extended.toml \
  --prices data/jquants_prices.csv \
  --out-dir reports/basic_strategies
```

## Transformer 模型流程

先复用已经下载好的J-Quants行情，构建月度训练集：

```bash
PYTHONPATH=src .venv/bin/python -m rakuten_quant.cli ml-build-dataset \
  --config configs/strategy_extended.toml \
  --prices data/jquants_prices.csv \
  --out data/ml_dataset.csv
```

训练一个小型Transformer模型：

```bash
PYTHONPATH=src .venv/bin/python -m rakuten_quant.cli ml-train \
  --dataset data/ml_dataset.csv \
  --out artifacts/ml/transformer.pt \
  --sequence-length 12 \
  --epochs 80
```

用walk-forward方式检查模型是否真的提升样本外表现：

```bash
PYTHONPATH=src .venv/bin/python -m rakuten_quant.cli ml-walk-forward \
  --config configs/strategy_extended.toml \
  --prices data/jquants_prices.csv \
  --out-dir reports/ml \
  --sequence-length 12 \
  --initial-train-months 24 \
  --epochs 40
```

只有当`reports/ml/walk_forward_report.md`显示模型叠加策略优于规则策略时，再把模型加入一键推荐：

```bash
./scripts/recommend.sh \
  --config configs/strategy_extended.toml \
  --out-dir reports/jquants_ml \
  --model artifacts/ml/transformer.pt \
  --model-weight 0.3
```

模型只改变风险资产的排序分数。趋势过滤、仓位上限、可买金额过滤、回撤防守和订单取整仍由规则系统控制。

## Hugging Face + PEFT 文本信号流程

这条线用于日文/英文新闻、财报摘要、公司公告等文本信号。它不替代价格策略，只输出`date,symbol,model_score`，再叠加到现有排序分数。

安装可选Hugging Face依赖：

```bash
uv pip install -r requirements-hf.txt
```

准备一个训练CSV：

```csv
date,symbol,text,label
2025-05-15,1329,"Company guidance improved and demand remained strong",positive
2025-05-16,1540,"Gold demand softened as real yields rose",negative
```

生成PEFT LoRA训练脚本：

```bash
PYTHONPATH=src .venv/bin/python -m rakuten_quant.cli hf-peft-script \
  --train-csv data/hf_text_labels.csv \
  --out scripts/train_finance_peft.py \
  --base-model ProsusAI/finbert \
  --hub-model-id your-hf-name/jp-finance-sentiment-lora
```

训练脚本可以用本地GPU或Hugging Face Jobs执行。正式用H200时，把同一脚本提交到HF Jobs，并确保`HF_TOKEN`有Hub写权限，训练结果会推送到`--hub-model-id`。

用金融基础模型或PEFT adapter给最新文本打分：

```bash
PYTHONPATH=src .venv/bin/python -m rakuten_quant.cli hf-score-texts \
  --input data/latest_texts.csv \
  --out data/hf_text_scores.csv \
  --model-id ProsusAI/finbert
```

如果已经有PEFT adapter：

```bash
PYTHONPATH=src .venv/bin/python -m rakuten_quant.cli hf-score-texts \
  --input data/latest_texts.csv \
  --out data/hf_text_scores.csv \
  --model-id ProsusAI/finbert \
  --adapter your-hf-name/jp-finance-sentiment-lora
```

把文本信号叠加到推荐订单：

```bash
./scripts/recommend.sh \
  --use-existing-prices \
  --config configs/strategy_extended.toml \
  --out-dir reports/jquants_hf \
  --score-csv data/hf_text_scores.csv \
  --model-weight 0.2
```

可以同时叠加价格Transformer和HF文本信号：

```bash
./scripts/recommend.sh \
  --use-existing-prices \
  --config configs/strategy_extended.toml \
  --out-dir reports/jquants_hybrid \
  --model artifacts/ml/transformer.pt \
  --score-csv data/hf_text_scores.csv \
  --model-weight 0.3
```

## 输出怎么看

最重要的文件是：

- `reports/jquants/orders.csv`：手工下单清单
- `reports/jquants/latest_signals.csv`：各资产动量、波动率、是否入选、目标权重
- `reports/jquants/backtest_report.md`：历史回测表现和最大回撤
- `reports/ml/walk_forward_report.md`：Transformer样本外验证结果
- `reports/basic_strategies/basic_strategy_report.md`：基础量化策略横向比较

`orders.csv`里的关键列：

- `action`: `BUY`买入，`SELL`卖出，`HOLD`不动
- `trade_units`: 推荐交易数量
- `trade_value_jpy`: 估算交易金额
- `target_weight`: 策略目标权重

`latest_signals.csv`里新增的模型列：

- `rule_score`: 原规则分数
- `model_score`: Transformer横截面排序分数
- `score`: 规则和模型融合后的最终分数

## 当前默认策略

- 标的：`1329`、`1655`、`2559`、`1540`、`2510`、现金
- 月度调仓，双周风险检查
- 风险资产需高于200日均线，且12-1个月动量为正
- 选2-3个评分最高资产，按反波动率分配
- 回撤超过6%时风险资产减半，超过10%时进入防守仓
- 默认不预留固定现金，小额差额低于5000日元不交易

`configs/strategy_aggressive.toml`会更接近日经225买入持有表现，但历史回撤会高于默认策略。

`configs/strategy_extended.toml`会纳入更多高波动产品，例如`1579`、`1580`、`2036`、`2037`、`2038`、`2039`、`2040`、`2041`，以及白金、白银、钯金、贵金属篮子和NASDAQ/S&P 500相关ETF。这个配置用于高风险研究，默认关闭10-15%回撤防守，杠杆/反向/ETN只给5%权重上限。

## 项目结构

- `configs/strategy.toml`：策略参数和标的配置
- `src/rakuten_quant/`：数据下载、信号、回测、订单生成代码
- `scripts/recommend.sh`：一键生成推荐订单
- `data/`：本地行情数据，已加入`.gitignore`
- `reports/`：本地报告和订单输出，已加入`.gitignore`
