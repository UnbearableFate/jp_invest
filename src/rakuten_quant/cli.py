from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pandas as pd

from .basic_strategies import compare_basic_strategies
from .backtest import run_backtest, write_backtest_outputs
from .config import load_config
from .data import fetch_jquants_v2_daily_quotes, fetch_yahoo_chart, load_price_csv
from .hf_peft import CompositeScoreProvider, CsvScoreProvider, DEFAULT_FINANCE_MODEL, score_texts_with_hf_model, write_peft_training_script
from .ml import build_ml_dataset, load_transformer_predictor, train_transformer, walk_forward_transformer
from .orders import build_orders, load_positions
from .portfolio import target_weights
from .signals import latest_signal_table


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rakuten-quant")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backtest = subparsers.add_parser("backtest", help="Run a monthly strategy backtest.")
    backtest.add_argument("--config", required=True)
    backtest.add_argument("--prices", required=True)
    backtest.add_argument("--out-dir", required=True)
    add_model_args(backtest)

    signals = subparsers.add_parser("signals", help="Write the latest signal table and target weights.")
    signals.add_argument("--config", required=True)
    signals.add_argument("--prices", required=True)
    signals.add_argument("--out", required=True)
    add_model_args(signals)

    orders = subparsers.add_parser("orders", help="Build a manual broker order list.")
    orders.add_argument("--config", required=True)
    orders.add_argument("--prices", required=True)
    orders.add_argument("--positions")
    orders.add_argument("--out", required=True)
    orders.add_argument("--current-drawdown", type=float, default=0.0)
    add_model_args(orders)

    download = subparsers.add_parser("download-yahoo", help="Download research prices from Yahoo chart API.")
    download.add_argument("--config", required=True)
    download.add_argument("--start", required=True)
    download.add_argument("--end")
    download.add_argument("--out", required=True)

    download_jq = subparsers.add_parser(
        "download-jquants",
        help="Download adjusted daily closes from J-Quants API V2 using JQUANTS_API_KEY.",
    )
    download_jq.add_argument("--config", required=True)
    download_jq.add_argument("--start", required=True)
    download_jq.add_argument("--end", required=True)
    download_jq.add_argument("--out", required=True)

    strategy_compare = subparsers.add_parser("strategy-compare", help="Compare simple quant baseline strategies.")
    strategy_compare.add_argument("--config", required=True)
    strategy_compare.add_argument("--prices", required=True)
    strategy_compare.add_argument("--out-dir", required=True)

    recommend = subparsers.add_parser(
        "recommend",
        help="Download J-Quants data and write the latest recommended order list.",
    )
    recommend.add_argument("--config", default="configs/strategy.toml")
    recommend.add_argument("--start", default="2021-05-29")
    recommend.add_argument("--end", default=date.today().isoformat())
    recommend.add_argument("--prices", default="data/jquants_prices.csv")
    recommend.add_argument("--out-dir", default="reports/jquants")
    recommend.add_argument("--positions")
    recommend.add_argument("--current-drawdown", type=float, default=0.0)
    recommend.add_argument(
        "--use-existing-prices",
        action="store_true",
        help="Skip J-Quants download and reuse the CSV at --prices.",
    )
    add_model_args(recommend)

    ml_dataset = subparsers.add_parser("ml-build-dataset", help="Build a monthly Transformer training dataset.")
    ml_dataset.add_argument("--config", required=True)
    ml_dataset.add_argument("--prices", required=True)
    ml_dataset.add_argument("--out", required=True)
    ml_dataset.add_argument("--horizon-days", type=int, default=21)

    ml_train = subparsers.add_parser("ml-train", help="Train a PyTorch Transformer scoring model.")
    ml_train.add_argument("--dataset", required=True)
    ml_train.add_argument("--out", required=True)
    ml_train.add_argument("--sequence-length", type=int, default=12)
    ml_train.add_argument("--epochs", type=int, default=80)
    ml_train.add_argument("--batch-size", type=int, default=64)
    ml_train.add_argument("--learning-rate", type=float, default=1e-3)
    ml_train.add_argument("--weight-decay", type=float, default=1e-4)
    ml_train.add_argument("--model-dim", type=int, default=64)
    ml_train.add_argument("--num-heads", type=int, default=4)
    ml_train.add_argument("--num-layers", type=int, default=2)
    ml_train.add_argument("--dropout", type=float, default=0.1)
    ml_train.add_argument("--validation-ratio", type=float, default=0.2)
    ml_train.add_argument("--seed", type=int, default=7)
    ml_train.add_argument("--max-steps", type=int)
    ml_train.add_argument("--device")

    ml_predict = subparsers.add_parser("ml-predict", help="Write Transformer score predictions for one rebalance date.")
    ml_predict.add_argument("--config", required=True)
    ml_predict.add_argument("--prices", required=True)
    ml_predict.add_argument("--model", required=True)
    ml_predict.add_argument("--out", required=True)
    ml_predict.add_argument("--asof", help="Prediction date. Defaults to the latest available price date.")
    ml_predict.add_argument("--device")

    ml_walk = subparsers.add_parser("ml-walk-forward", help="Run Transformer walk-forward validation.")
    ml_walk.add_argument("--config", required=True)
    ml_walk.add_argument("--prices", required=True)
    ml_walk.add_argument("--out-dir", required=True)
    ml_walk.add_argument("--horizon-days", type=int, default=21)
    ml_walk.add_argument("--sequence-length", type=int, default=12)
    ml_walk.add_argument("--initial-train-months", type=int, default=24)
    ml_walk.add_argument("--epochs", type=int, default=40)
    ml_walk.add_argument("--batch-size", type=int, default=64)
    ml_walk.add_argument("--learning-rate", type=float, default=1e-3)
    ml_walk.add_argument("--model-weight", type=float, default=0.3)
    ml_walk.add_argument("--max-test-months", type=int)
    ml_walk.add_argument("--device")

    hf_score = subparsers.add_parser("hf-score-texts", help="Score finance text with a Hugging Face model or PEFT adapter.")
    hf_score.add_argument("--input", required=True)
    hf_score.add_argument("--out", required=True)
    hf_score.add_argument("--model-id", default=DEFAULT_FINANCE_MODEL)
    hf_score.add_argument("--adapter")
    hf_score.add_argument("--date-column", default="date")
    hf_score.add_argument("--symbol-column", default="symbol")
    hf_score.add_argument("--text-column", default="text")
    hf_score.add_argument("--batch-size", type=int, default=8)
    hf_score.add_argument("--device")

    hf_script = subparsers.add_parser("hf-peft-script", help="Write a PEFT LoRA sequence-classification training script.")
    hf_script.add_argument("--out", required=True)
    hf_script.add_argument("--base-model", default=DEFAULT_FINANCE_MODEL)
    hf_script.add_argument("--train-csv", required=True)
    hf_script.add_argument("--hub-model-id", required=True)
    hf_script.add_argument("--text-column", default="text")
    hf_script.add_argument("--label-column", default="label")
    hf_script.add_argument("--num-labels", type=int, default=3)
    hf_script.add_argument("--epochs", type=int, default=3)
    hf_script.add_argument("--learning-rate", type=float, default=2e-4)
    hf_script.add_argument("--lora-r", type=int, default=16)
    hf_script.add_argument("--lora-alpha", type=int, default=32)
    hf_script.add_argument("--lora-dropout", type=float, default=0.05)
    hf_script.add_argument("--max-length", type=int, default=256)

    args = parser.parse_args(argv)

    config = load_config(args.config) if hasattr(args, "config") else None

    if args.command == "backtest":
        assert config is not None
        prices = load_price_csv(args.prices, config)
        model_provider = load_model_provider(args.model, args.score_csv, args.score_max_age_days, args.device)
        result = run_backtest(prices, config, model_provider=model_provider, model_weight=args.model_weight)
        write_backtest_outputs(result, args.out_dir)
        print(f"Wrote backtest outputs to {Path(args.out_dir).resolve()}")
        print(f"End value: {result.summary['end_value_jpy']:.0f} JPY")
        print(f"Max drawdown: {result.summary['max_drawdown']:.2%}")
        return 0

    if args.command == "signals":
        assert config is not None
        prices = load_price_csv(args.prices, config)
        out = Path(args.out)
        model_provider = load_model_provider(args.model, args.score_csv, args.score_max_age_days, args.device)
        model_scores = latest_model_scores(model_provider, prices, config)
        write_latest_signals(prices, config, out, model_scores=model_scores, model_weight=args.model_weight)
        print(f"Wrote signals to {out.resolve()}")
        return 0

    if args.command == "orders":
        assert config is not None
        prices = load_price_csv(args.prices, config)
        positions = load_positions(args.positions, config)
        model_provider = load_model_provider(args.model, args.score_csv, args.score_max_age_days, args.device)
        model_scores = latest_model_scores(model_provider, prices, config)
        orders_df = build_orders(
            prices,
            config,
            positions,
            args.current_drawdown,
            model_scores=model_scores,
            model_weight=args.model_weight,
        )
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        orders_df.to_csv(out, index=False)
        print(f"Wrote orders to {out.resolve()}")
        return 0

    if args.command == "download-yahoo":
        assert config is not None
        out = fetch_yahoo_chart(config, args.start, args.end, args.out)
        print(f"Wrote Yahoo research prices to {out.resolve()}")
        return 0

    if args.command == "download-jquants":
        assert config is not None
        out = fetch_jquants_v2_daily_quotes(config, args.start, args.end, args.out)
        print(f"Wrote J-Quants prices to {out.resolve()}")
        return 0

    if args.command == "strategy-compare":
        assert config is not None
        prices = load_price_csv(args.prices, config)
        summary = compare_basic_strategies(prices, config, args.out_dir)
        print(f"Wrote strategy comparison to {Path(args.out_dir).resolve()}")
        print(summary[["strategy", "end_value_jpy", "max_drawdown"]].to_string(index=False))
        return 0

    if args.command == "recommend":
        assert config is not None
        prices_path = Path(args.prices)
        out_dir = Path(args.out_dir)
        if not args.use_existing_prices:
            fetch_jquants_v2_daily_quotes(config, args.start, args.end, prices_path)

        prices = load_price_csv(prices_path, config)
        model_provider = load_model_provider(args.model, args.score_csv, args.score_max_age_days, args.device)
        result = run_backtest(prices, config, model_provider=model_provider, model_weight=args.model_weight)
        write_backtest_outputs(result, out_dir)
        signals_path = out_dir / "latest_signals.csv"
        model_scores = latest_model_scores(model_provider, prices, config)
        write_latest_signals(prices, config, signals_path, model_scores=model_scores, model_weight=args.model_weight)

        positions_path = args.positions
        if positions_path is None and Path("positions.csv").exists():
            positions_path = "positions.csv"
        positions = load_positions(positions_path, config)
        orders_df = build_orders(
            prices,
            config,
            positions,
            args.current_drawdown,
            model_scores=model_scores,
            model_weight=args.model_weight,
        )
        orders_path = out_dir / "orders.csv"
        orders_df.to_csv(orders_path, index=False)

        print(f"Price data: {prices_path.resolve()}")
        print(f"Backtest report: {(out_dir / 'backtest_report.md').resolve()}")
        print(f"Signals: {signals_path.resolve()}")
        print(f"Orders: {orders_path.resolve()}")
        print(f"End value: {result.summary['end_value_jpy']:.0f} JPY")
        print(f"Max drawdown: {result.summary['max_drawdown']:.2%}")
        actionable = orders_df[orders_df["action"].isin(["BUY", "SELL"])]
        if actionable.empty:
            print("No actionable orders.")
        else:
            print("Recommended orders:")
            print(actionable[["symbol", "action", "trade_units", "trade_value_jpy"]].to_string(index=False))
        return 0

    if args.command == "ml-build-dataset":
        assert config is not None
        prices = load_price_csv(args.prices, config)
        dataset = build_ml_dataset(prices, config, horizon_days=args.horizon_days)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        dataset.to_csv(out, index=False)
        print(f"Wrote ML dataset to {out.resolve()}")
        print(f"Rows: {len(dataset)}")
        return 0

    if args.command == "ml-train":
        summary = train_transformer(
            args.dataset,
            args.out,
            sequence_length=args.sequence_length,
            epochs=args.epochs,
            batch_size=args.batch_size,
            learning_rate=args.learning_rate,
            weight_decay=args.weight_decay,
            model_dim=args.model_dim,
            num_heads=args.num_heads,
            num_layers=args.num_layers,
            dropout=args.dropout,
            validation_ratio=args.validation_ratio,
            device=args.device,
            seed=args.seed,
            max_steps=args.max_steps,
        )
        if summary.get("is_main_process", True):
            print(f"Wrote Transformer model to {Path(args.out).resolve()}")
            print(f"Samples: {summary['samples']}")
            print(f"Optimizer steps: {summary['optimizer_steps']}")
            print(f"Best validation loss: {summary['best_valid_loss']:.6f}")
        return 0

    if args.command == "ml-predict":
        assert config is not None
        prices = load_price_csv(args.prices, config)
        asof = resolve_prediction_asof(prices, args.asof)
        predictor = load_transformer_predictor(args.model, device=args.device)
        scores = predictor.predict_scores(prices.loc[:asof], config, asof)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        rows = scores.rename("model_score").reset_index()
        rows.insert(0, "date", asof.date().isoformat())
        rows.to_csv(out, index=False)
        print(f"Wrote Transformer predictions to {out.resolve()}")
        print(f"As-of date: {asof.date().isoformat()}")
        print(f"Rows: {len(rows)}")
        return 0

    if args.command == "ml-walk-forward":
        assert config is not None
        prices = load_price_csv(args.prices, config)
        predictions = walk_forward_transformer(
            prices,
            config,
            args.out_dir,
            horizon_days=args.horizon_days,
            sequence_length=args.sequence_length,
            initial_train_months=args.initial_train_months,
            epochs=args.epochs,
            batch_size=args.batch_size,
            learning_rate=args.learning_rate,
            model_weight=args.model_weight,
            max_test_months=args.max_test_months,
            device=args.device,
        )
        print(f"Wrote walk-forward outputs to {Path(args.out_dir).resolve()}")
        print(f"Prediction rows: {len(predictions)}")
        return 0

    if args.command == "hf-score-texts":
        scores = score_texts_with_hf_model(
            args.input,
            args.out,
            model_id=args.model_id,
            adapter_path=args.adapter,
            date_column=args.date_column,
            symbol_column=args.symbol_column,
            text_column=args.text_column,
            batch_size=args.batch_size,
            device=args.device,
        )
        print(f"Wrote Hugging Face text scores to {Path(args.out).resolve()}")
        print(f"Rows: {len(scores)}")
        return 0

    if args.command == "hf-peft-script":
        out = write_peft_training_script(
            args.out,
            base_model=args.base_model,
            train_csv=args.train_csv,
            hub_model_id=args.hub_model_id,
            text_column=args.text_column,
            label_column=args.label_column,
            num_labels=args.num_labels,
            epochs=args.epochs,
            learning_rate=args.learning_rate,
            lora_r=args.lora_r,
            lora_alpha=args.lora_alpha,
            lora_dropout=args.lora_dropout,
            max_length=args.max_length,
        )
        print(f"Wrote PEFT training script to {out.resolve()}")
        return 0

    parser.error(f"Unhandled command: {args.command}")
    return 2


def add_model_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", help="Path to a trained PyTorch Transformer checkpoint.")
    parser.add_argument("--score-csv", help="CSV with date,symbol,model_score from HF/PEFT or another signal model.")
    parser.add_argument("--score-max-age-days", type=int, default=30, help="Maximum age for score-csv rows at each rebalance.")
    parser.add_argument("--model-weight", type=float, default=0.3, help="Weight of model_score in the final rank score.")
    parser.add_argument("--device", help="PyTorch device override, such as cpu, mps, or cuda.")


def load_model_provider(model_path: str | None, score_csv: str | None, score_max_age_days: int, device: str | None):
    providers = []
    if model_path:
        providers.append(load_transformer_predictor(model_path, device=device))
    if score_csv:
        providers.append(CsvScoreProvider.from_csv(score_csv, max_age_days=score_max_age_days))
    if not providers:
        return None
    if len(providers) == 1:
        return providers[0]
    return CompositeScoreProvider(tuple(providers))


def latest_model_scores(model_provider, prices, config):
    if model_provider is None:
        return None
    return model_provider.predict_scores(prices, config, prices.index[-1])


def resolve_prediction_asof(prices, asof: str | None) -> pd.Timestamp:
    if prices.empty:
        raise ValueError("Price data is empty.")
    if asof is None:
        return pd.Timestamp(prices.index[-1])
    requested = pd.Timestamp(asof)
    eligible = prices.index[prices.index <= requested]
    if len(eligible) == 0:
        raise ValueError(f"No price rows are available on or before {requested.date().isoformat()}.")
    return pd.Timestamp(eligible[-1])


def write_latest_signals(
    prices,
    config,
    out: Path,
    model_scores=None,
    model_weight: float = 0.0,
) -> None:
    table = latest_signal_table(prices, config, model_scores=model_scores, model_weight=model_weight)
    weights = target_weights(prices, config, model_scores=model_scores, model_weight=model_weight)
    table = table.merge(
        weights.rename("target_weight"),
        left_on="symbol",
        right_index=True,
        how="left",
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(out, index=False)


if __name__ == "__main__":
    raise SystemExit(main())
