from __future__ import annotations

from pathlib import Path
from datetime import date
import importlib.util
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from rakuten_quant.basic_strategies import compare_basic_strategies
from rakuten_quant.backtest import run_backtest
from rakuten_quant.config import load_config
from rakuten_quant.data import clamp_jquants_start, fetch_jquants_v2_daily_quotes, load_price_csv
from rakuten_quant.hf_peft import CsvScoreProvider, write_peft_training_script
from rakuten_quant.ml import build_ml_dataset, load_transformer_predictor, train_transformer
from rakuten_quant.orders import build_orders
from rakuten_quant.portfolio import target_weights


ROOT = Path(__file__).resolve().parents[1]


class StrategyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_config(ROOT / "configs" / "strategy.toml")
        dates = pd.bdate_range("2022-01-03", periods=360)
        rows = []
        for idx, date in enumerate(dates):
            rows.extend(
                [
                    {"date": date, "symbol": "1475", "close": 100 + idx * 0.08},
                    {"date": date, "symbol": "1329", "close": 100 + idx * 0.12},
                    {"date": date, "symbol": "1655", "close": 100 + idx * 0.18},
                    {"date": date, "symbol": "2559", "close": 100 + idx * 0.10},
                    {"date": date, "symbol": "1540", "close": 100 + idx * 0.05},
                    {"date": date, "symbol": "2510", "close": 100 + idx * 0.01},
                ]
            )
        cls.raw = pd.DataFrame(rows)

    def test_load_prices_adds_cash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prices.csv"
            self.raw.to_csv(path, index=False)
            prices = load_price_csv(path, self.config)
        self.assertIn("CASH", prices.columns)
        self.assertEqual(list(prices.columns), self.config.symbols)

    def test_jquants_start_is_clamped_to_five_year_window(self) -> None:
        start = clamp_jquants_start("2020-01-01", today=date(2026, 6, 5))
        self.assertEqual(start.date().isoformat(), "2021-06-05")

    def test_jquants_download_uses_local_cache_and_clipped_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cached_prices.csv"
            cached_rows = []
            for symbol in ["1329", "1655", "1540", "2510", "9999"]:
                cached_rows.append({"date": "2026-06-05", "symbol": symbol, "close": 100.0})
            pd.DataFrame(cached_rows).to_csv(path, index=False)

            calls = []

            def fake_download(asset_symbol, jquants_code, start, end, api_key, pause_seconds):
                calls.append((asset_symbol, start.date().isoformat(), end.date().isoformat()))
                return [{"date": "2026-06-05", "symbol": asset_symbol, "close": 200.0}]

            with patch("rakuten_quant.data.download_jquants_symbol_rows", side_effect=fake_download):
                fetch_jquants_v2_daily_quotes(
                    self.config,
                    "2020-01-01",
                    "2026-06-05",
                    path,
                    api_key="test",
                    today=date(2026, 6, 5),
                )

            self.assertEqual(calls, [("2559", "2021-06-05", "2026-06-05")])
            saved = pd.read_csv(path)
            self.assertEqual(set(saved["symbol"].astype(str)), {"1329", "1655", "1540", "2510", "2559", "9999"})

    def test_target_weights_sum_to_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prices.csv"
            self.raw.to_csv(path, index=False)
            prices = load_price_csv(path, self.config)
        weights = target_weights(prices, self.config)
        self.assertAlmostEqual(float(weights.sum()), 1.0)
        self.assertGreaterEqual(float(weights["CASH"]) + 1e-12, self.config.portfolio.cash_floor_weight)

    def test_backtest_and_orders_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prices.csv"
            self.raw.to_csv(path, index=False)
            prices = load_price_csv(path, self.config)
        result = run_backtest(prices, self.config)
        self.assertFalse(result.equity_curve.empty)
        self.assertIn("max_drawdown", result.summary)
        orders = build_orders(prices, self.config)
        self.assertIn("action", orders.columns)
        self.assertFalse(orders.empty)

    def test_basic_strategy_comparison_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prices.csv"
            self.raw.to_csv(path, index=False)
            prices = load_price_csv(path, self.config)
            summary = compare_basic_strategies(prices, self.config, Path(tmp) / "basic")
        self.assertIn("rule_current", set(summary["strategy"]))
        self.assertIn("dual_momentum", set(summary["strategy"]))

    def test_csv_score_provider_and_peft_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scores.csv"
            pd.DataFrame(
                [
                    {"date": "2023-05-31", "symbol": "1329", "model_score": 0.2},
                    {"date": "2023-05-31", "symbol": "1655", "model_score": 0.8},
                ]
            ).to_csv(path, index=False)
            provider = CsvScoreProvider.from_csv(path)
            prices_path = Path(tmp) / "prices.csv"
            self.raw.to_csv(prices_path, index=False)
            prices = load_price_csv(prices_path, self.config)
            scores = provider.predict_scores(prices, self.config, pd.Timestamp("2023-05-31"))
            self.assertGreater(float(scores["1655"]), float(scores["1329"]))

            script_path = write_peft_training_script(
                Path(tmp) / "train_peft.py",
                base_model="ProsusAI/finbert",
                train_csv="data/labels.csv",
                hub_model_id="user/test-finance-lora",
            )
            self.assertIn("LoraConfig", script_path.read_text(encoding="utf-8"))

    @unittest.skipIf(importlib.util.find_spec("torch") is None, "PyTorch is not installed")
    def test_transformer_dataset_training_and_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prices.csv"
            self.raw.to_csv(path, index=False)
            prices = load_price_csv(path, self.config)
            dataset = build_ml_dataset(prices, self.config, horizon_days=5)
            self.assertFalse(dataset.empty)

            model_path = Path(tmp) / "transformer.pt"
            train_transformer(
                dataset,
                model_path,
                sequence_length=2,
                epochs=1,
                batch_size=8,
                model_dim=16,
                num_heads=2,
                num_layers=1,
                device="cpu",
            )
            predictor = load_transformer_predictor(model_path, device="cpu")
            scores = predictor.predict_scores(prices, self.config, prices.index[-1])
            self.assertFalse(scores.empty)
            weights = target_weights(prices, self.config, model_scores=scores, model_weight=0.3)
            self.assertAlmostEqual(float(weights.sum()), 1.0)


if __name__ == "__main__":
    unittest.main()
