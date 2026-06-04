from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import AssetConfig, StrategyConfig
from .signals import rebalance_dates

try:
    import torch
except ImportError:  # pragma: no cover - exercised only in missing dependency environments.
    torch = None  # type: ignore[assignment]


FEATURE_WINDOWS = (1, 5, 21, 63, 126, 252)
VOLATILITY_WINDOWS = (21, 63)
DRAWDOWN_WINDOWS = (63, 252)
MOVING_AVERAGE_WINDOWS = (63, 200)
TARGET_COLUMN = "target"


def build_ml_dataset(
    prices: pd.DataFrame,
    config: StrategyConfig,
    horizon_days: int = 21,
    frequency: str | None = None,
) -> pd.DataFrame:
    """Build a monthly supervised learning panel from daily prices.

    Features are computed from prices lagged by one trading day. Labels use the
    forward return from the rebalance close over ``horizon_days``.
    """

    rows = build_feature_rows(
        prices=prices,
        config=config,
        horizon_days=horizon_days,
        include_future=True,
        dates=None,
        frequency=frequency,
    )
    if rows.empty:
        return rows

    rows["target_raw"] = rows["risk_adjusted_excess_return"]
    rows[TARGET_COLUMN] = rows.groupby("date")["target_raw"].rank(pct=True) * 2.0 - 1.0
    return rows.sort_values(["date", "symbol"]).reset_index(drop=True)


def build_feature_rows(
    prices: pd.DataFrame,
    config: StrategyConfig,
    horizon_days: int = 21,
    include_future: bool = True,
    dates: pd.DatetimeIndex | list[pd.Timestamp] | None = None,
    frequency: str | None = None,
) -> pd.DataFrame:
    prices = prices.copy().sort_index().ffill()
    if prices.empty:
        return pd.DataFrame()

    if dates is None:
        dates = rebalance_dates(prices, frequency or config.portfolio.rebalance)
    else:
        dates = pd.DatetimeIndex(dates)

    feature_prices = prices.shift(1)
    returns = prices.pct_change()
    assets = config.by_role("risk")
    asset_classes = sorted({asset.asset_class for asset in assets})
    benchmark_symbol = config.portfolio.benchmark_symbol
    max_history = max(FEATURE_WINDOWS + VOLATILITY_WINDOWS + DRAWDOWN_WINDOWS + MOVING_AVERAGE_WINDOWS)

    rows: list[dict[str, Any]] = []
    for asof in dates:
        asof = pd.Timestamp(asof)
        if asof not in prices.index:
            continue
        position = int(prices.index.get_loc(asof))
        if position <= max_history:
            continue
        if include_future and position + horizon_days >= len(prices):
            continue

        benchmark_history = get_history(feature_prices, benchmark_symbol, asof)
        benchmark_features = market_features(benchmark_history)

        for asset in assets:
            history = get_history(feature_prices, asset.symbol, asof)
            if len(history) <= max_history:
                continue
            if pd.isna(prices.at[asof, asset.symbol]):
                continue

            row: dict[str, Any] = {
                "date": asof.date().isoformat(),
                "symbol": asset.symbol,
                "asset_class": asset.asset_class,
                "close": float(prices.at[asof, asset.symbol]),
            }
            row.update(price_features(history))
            row.update(benchmark_features)
            row.update(relative_features(row, benchmark_features))
            row.update(asset_features(asset, asset_classes))

            if include_future:
                row.update(
                    future_label_features(
                        prices=prices,
                        returns=returns,
                        symbol=asset.symbol,
                        benchmark_symbol=benchmark_symbol,
                        position=position,
                        horizon_days=horizon_days,
                    )
                )
            rows.append(row)

    return pd.DataFrame(rows)


def get_history(prices: pd.DataFrame, symbol: str, asof: pd.Timestamp) -> pd.Series:
    if symbol not in prices.columns:
        return pd.Series(dtype=float)
    return prices.loc[:asof, symbol].dropna()


def price_features(close: pd.Series) -> dict[str, float]:
    features: dict[str, float] = {}
    for window in FEATURE_WINDOWS:
        features[f"ret_{window}d"] = pct_change_over(close, window)
    for window in VOLATILITY_WINDOWS:
        features[f"vol_{window}d"] = annualized_volatility(close, window)
    for window in DRAWDOWN_WINDOWS:
        features[f"drawdown_{window}d"] = drawdown(close, window)
    for window in MOVING_AVERAGE_WINDOWS:
        features[f"ma_gap_{window}d"] = moving_average_gap(close, window)
    return features


def market_features(benchmark_close: pd.Series) -> dict[str, float]:
    if benchmark_close.empty:
        return {
            "market_ret_63d": 0.0,
            "market_ret_252d": 0.0,
            "market_vol_63d": 0.0,
            "market_drawdown_252d": 0.0,
            "market_above_ma200": 0.0,
        }
    return {
        "market_ret_63d": pct_change_over(benchmark_close, 63),
        "market_ret_252d": pct_change_over(benchmark_close, 252),
        "market_vol_63d": annualized_volatility(benchmark_close, 63),
        "market_drawdown_252d": drawdown(benchmark_close, 252),
        "market_above_ma200": float(moving_average_gap(benchmark_close, 200) > 0.0),
    }


def relative_features(row: dict[str, Any], benchmark_features: dict[str, float]) -> dict[str, float]:
    return {
        "excess_ret_63d": float(row.get("ret_63d", 0.0)) - benchmark_features["market_ret_63d"],
        "excess_ret_252d": float(row.get("ret_252d", 0.0)) - benchmark_features["market_ret_252d"],
    }


def asset_features(asset: AssetConfig, asset_classes: list[str]) -> dict[str, float]:
    name = asset.name.lower()
    features = {f"asset_class_{clean_feature_name(asset_class)}": 0.0 for asset_class in asset_classes}
    features[f"asset_class_{clean_feature_name(asset.asset_class)}"] = 1.0
    features.update(
        {
            "is_leveraged_inverse": float(asset.asset_class == "leveraged_inverse"),
            "is_bull": float("bull" in name or "ブル" in asset.name),
            "is_bear": float("bear" in name or "ベア" in asset.name),
            "is_etn": float("etn" in name),
            "max_weight": float(asset.max_weight),
            "min_trade_unit": float(asset.min_trade_unit),
        }
    )
    return features


def future_label_features(
    prices: pd.DataFrame,
    returns: pd.DataFrame,
    symbol: str,
    benchmark_symbol: str,
    position: int,
    horizon_days: int,
) -> dict[str, float]:
    start_price = float(prices[symbol].iloc[position])
    end_price = float(prices[symbol].iloc[position + horizon_days])
    future_return = end_price / start_price - 1.0

    benchmark_return = 0.0
    if benchmark_symbol in prices.columns:
        benchmark_start = float(prices[benchmark_symbol].iloc[position])
        benchmark_end = float(prices[benchmark_symbol].iloc[position + horizon_days])
        benchmark_return = benchmark_end / benchmark_start - 1.0

    future_daily = returns[symbol].iloc[position + 1 : position + horizon_days + 1].dropna()
    future_volatility = float(future_daily.std() * np.sqrt(252)) if len(future_daily) > 1 else 0.0
    future_excess_return = future_return - benchmark_return
    risk_adjusted = future_excess_return / max(future_volatility, 0.01)
    return {
        "future_return": future_return,
        "future_benchmark_return": benchmark_return,
        "future_excess_return": future_excess_return,
        "future_volatility": future_volatility,
        "risk_adjusted_excess_return": risk_adjusted,
        "target_outperform_benchmark": float(future_excess_return > 0.0),
    }


def pct_change_over(close: pd.Series, window: int) -> float:
    if len(close) <= window:
        return 0.0
    start = float(close.iloc[-window - 1])
    end = float(close.iloc[-1])
    if start <= 0:
        return 0.0
    return end / start - 1.0


def annualized_volatility(close: pd.Series, window: int) -> float:
    if len(close) <= window:
        return 0.0
    daily = close.pct_change().dropna().iloc[-window:]
    if daily.empty:
        return 0.0
    return float(daily.std() * np.sqrt(252))


def drawdown(close: pd.Series, window: int) -> float:
    if len(close) < window:
        return 0.0
    current = float(close.iloc[-1])
    high = float(close.iloc[-window:].max())
    if high <= 0:
        return 0.0
    return 1.0 - current / high


def moving_average_gap(close: pd.Series, window: int) -> float:
    if len(close) < window:
        return 0.0
    current = float(close.iloc[-1])
    average = float(close.iloc[-window:].mean())
    if average <= 0:
        return 0.0
    return current / average - 1.0


def clean_feature_name(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value.lower()).strip("_")


def select_feature_columns(frame: pd.DataFrame) -> list[str]:
    blocked = {
        "date",
        "symbol",
        "asset_class",
        "close",
        "future_return",
        "future_benchmark_return",
        "future_excess_return",
        "future_volatility",
        "risk_adjusted_excess_return",
        "target_raw",
        "target_outperform_benchmark",
        TARGET_COLUMN,
    }
    prefixes = (
        "asset_class_",
        "drawdown_",
        "excess_ret_",
        "is_",
        "ma_gap_",
        "market_",
        "ret_",
        "vol_",
    )
    names = []
    for column in frame.columns:
        if column in blocked:
            continue
        if column.startswith(prefixes) or column in {"max_weight", "min_trade_unit"}:
            names.append(column)
    return sorted(names)


def prepare_feature_frame(frame: pd.DataFrame, feature_columns: list[str]) -> pd.DataFrame:
    prepared = frame.copy()
    for column in feature_columns:
        if column not in prepared.columns:
            prepared[column] = 0.0
    return (
        prepared[feature_columns]
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0.0)
        .astype(float)
    )


def make_sequences(
    frame: pd.DataFrame,
    feature_columns: list[str],
    sequence_length: int,
    require_target: bool,
) -> tuple[np.ndarray, np.ndarray | None, pd.DataFrame]:
    if sequence_length < 1:
        raise ValueError("sequence_length must be at least 1.")

    samples: list[np.ndarray] = []
    targets: list[float] = []
    meta_rows: list[dict[str, str]] = []
    sorted_frame = frame.sort_values(["symbol", "date"]).reset_index(drop=True)
    for symbol, group in sorted_frame.groupby("symbol", sort=False):
        group = group.sort_values("date").reset_index(drop=True)
        values = prepare_feature_frame(group, feature_columns).to_numpy(dtype=np.float32)
        for idx in range(sequence_length - 1, len(group)):
            if require_target and pd.isna(group.loc[idx, TARGET_COLUMN]):
                continue
            samples.append(values[idx - sequence_length + 1 : idx + 1])
            if require_target:
                targets.append(float(group.loc[idx, TARGET_COLUMN]))
            meta_rows.append(
                {
                    "date": str(group.loc[idx, "date"]),
                    "symbol": str(symbol),
                }
            )

    if not samples:
        empty_x = np.empty((0, sequence_length, len(feature_columns)), dtype=np.float32)
        empty_y = np.empty((0,), dtype=np.float32) if require_target else None
        return empty_x, empty_y, pd.DataFrame(meta_rows)

    x = np.stack(samples).astype(np.float32)
    y = np.asarray(targets, dtype=np.float32) if require_target else None
    return x, y, pd.DataFrame(meta_rows)


if torch is not None:

    class PriceTransformer(torch.nn.Module):
        def __init__(
            self,
            input_dim: int,
            sequence_length: int,
            model_dim: int = 64,
            num_heads: int = 4,
            num_layers: int = 2,
            dropout: float = 0.1,
        ) -> None:
            super().__init__()
            self.input_projection = torch.nn.Linear(input_dim, model_dim)
            self.position = torch.nn.Parameter(torch.zeros(1, sequence_length, model_dim))
            layer = torch.nn.TransformerEncoderLayer(
                d_model=model_dim,
                nhead=num_heads,
                dim_feedforward=model_dim * 4,
                dropout=dropout,
                activation="gelu",
                batch_first=True,
            )
            self.encoder = torch.nn.TransformerEncoder(layer, num_layers=num_layers)
            self.head = torch.nn.Sequential(
                torch.nn.LayerNorm(model_dim),
                torch.nn.Linear(model_dim, max(model_dim // 2, 8)),
                torch.nn.GELU(),
                torch.nn.Dropout(dropout),
                torch.nn.Linear(max(model_dim // 2, 8), 1),
            )

        def forward(self, x: Any) -> Any:
            hidden = self.input_projection(x)
            hidden = hidden + self.position[:, : hidden.shape[1], :]
            encoded = self.encoder(hidden)
            return self.head(encoded[:, -1, :]).squeeze(-1)

else:

    class PriceTransformer:  # type: ignore[no-redef]
        pass


def require_torch() -> Any:
    if torch is None:
        raise RuntimeError("PyTorch is required for Transformer ML commands. Install with `uv pip install -r requirements.txt`.")
    return torch


def choose_device(device: str | None = None) -> str:
    torch_module = require_torch()
    if device:
        return device
    if torch_module.cuda.is_available():
        return "cuda"
    if getattr(torch_module.backends, "mps", None) and torch_module.backends.mps.is_available():
        return "mps"
    return "cpu"


def train_transformer(
    dataset: pd.DataFrame | str | Path,
    out_path: str | Path,
    sequence_length: int = 12,
    epochs: int = 80,
    batch_size: int = 64,
    learning_rate: float = 1e-3,
    weight_decay: float = 1e-4,
    model_dim: int = 64,
    num_heads: int = 4,
    num_layers: int = 2,
    dropout: float = 0.1,
    validation_ratio: float = 0.2,
    device: str | None = None,
    seed: int = 7,
) -> dict[str, Any]:
    torch_module = require_torch()
    if isinstance(dataset, (str, Path)):
        frame = pd.read_csv(dataset)
    else:
        frame = dataset.copy()

    if frame.empty:
        raise ValueError("Training dataset is empty.")

    feature_columns = select_feature_columns(frame)
    if not feature_columns:
        raise ValueError("Training dataset has no usable feature columns.")

    x, y, meta = make_sequences(frame, feature_columns, sequence_length, require_target=True)
    if y is None or len(x) < 2:
        raise ValueError("Not enough sequence samples to train the Transformer.")

    torch_module.manual_seed(seed)
    device_name = choose_device(device)
    train_index, valid_index = time_ordered_split(meta, validation_ratio)
    x_train = x[train_index]
    y_train = y[train_index]
    x_valid = x[valid_index]
    y_valid = y[valid_index]

    mean = x_train.reshape(-1, x_train.shape[-1]).mean(axis=0)
    std = x_train.reshape(-1, x_train.shape[-1]).std(axis=0)
    std = np.where(std < 1e-6, 1.0, std)
    x_train = (x_train - mean) / std
    x_valid = (x_valid - mean) / std

    model_config = {
        "input_dim": len(feature_columns),
        "sequence_length": sequence_length,
        "model_dim": model_dim,
        "num_heads": num_heads,
        "num_layers": num_layers,
        "dropout": dropout,
    }
    model = PriceTransformer(**model_config).to(device_name)
    optimizer = torch_module.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
    loss_fn = torch_module.nn.SmoothL1Loss()

    train_loader = torch_module.utils.data.DataLoader(
        torch_module.utils.data.TensorDataset(
            torch_module.tensor(x_train, dtype=torch_module.float32),
            torch_module.tensor(y_train, dtype=torch_module.float32),
        ),
        batch_size=batch_size,
        shuffle=True,
    )

    best_state = None
    best_valid_loss = float("inf")
    final_train_loss = float("nan")
    for _ in range(max(epochs, 1)):
        model.train()
        batch_losses: list[float] = []
        for batch_x, batch_y in train_loader:
            batch_x = batch_x.to(device_name)
            batch_y = batch_y.to(device_name)
            optimizer.zero_grad(set_to_none=True)
            loss = loss_fn(model(batch_x), batch_y)
            loss.backward()
            optimizer.step()
            batch_losses.append(float(loss.detach().cpu()))
        final_train_loss = float(np.mean(batch_losses)) if batch_losses else float("nan")

        valid_loss = evaluate_loss(model, x_valid, y_valid, loss_fn, device_name)
        if valid_loss <= best_valid_loss:
            best_valid_loss = valid_loss
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}

    if best_state is not None:
        model.load_state_dict(best_state)

    checkpoint = {
        "model_type": "price_transformer",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "feature_columns": feature_columns,
        "normalization": {
            "mean": mean.astype(float).tolist(),
            "std": std.astype(float).tolist(),
        },
        "model_config": model_config,
        "state_dict": model.state_dict(),
        "train_summary": {
            "samples": int(len(x)),
            "train_samples": int(len(train_index)),
            "valid_samples": int(len(valid_index)),
            "final_train_loss": final_train_loss,
            "best_valid_loss": best_valid_loss,
            "device": device_name,
            "epochs": int(max(epochs, 1)),
        },
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    torch_module.save(checkpoint, out)
    return checkpoint["train_summary"]


def time_ordered_split(meta: pd.DataFrame, validation_ratio: float) -> tuple[np.ndarray, np.ndarray]:
    dates = pd.Series(pd.to_datetime(meta["date"]).unique()).sort_values().reset_index(drop=True)
    if len(dates) <= 1:
        index = np.arange(len(meta))
        return index, index
    valid_count = max(1, int(round(len(dates) * validation_ratio)))
    valid_count = min(valid_count, len(dates) - 1)
    valid_dates = set(dates.iloc[-valid_count:].dt.strftime("%Y-%m-%d"))
    valid_mask = meta["date"].isin(valid_dates).to_numpy()
    train_index = np.flatnonzero(~valid_mask)
    valid_index = np.flatnonzero(valid_mask)
    if len(train_index) == 0:
        train_index = np.flatnonzero(np.ones(len(meta), dtype=bool))
    if len(valid_index) == 0:
        valid_index = train_index
    return train_index, valid_index


def evaluate_loss(model: Any, x: np.ndarray, y: np.ndarray, loss_fn: Any, device_name: str) -> float:
    torch_module = require_torch()
    if len(x) == 0:
        return float("nan")
    model.eval()
    with torch_module.no_grad():
        predictions = model(torch_module.tensor(x, dtype=torch_module.float32, device=device_name))
        loss = loss_fn(predictions, torch_module.tensor(y, dtype=torch_module.float32, device=device_name))
    return float(loss.detach().cpu())


@dataclass
class TransformerPredictor:
    model: Any
    feature_columns: list[str]
    sequence_length: int
    mean: np.ndarray
    std: np.ndarray
    device: str

    def predict_scores(
        self,
        prices: pd.DataFrame,
        config: StrategyConfig,
        asof: pd.Timestamp | None = None,
    ) -> pd.Series:
        if asof is None:
            asof = pd.Timestamp(prices.index[-1])
        asof = pd.Timestamp(asof)
        feature_frame = build_prediction_frame(prices, config, asof, self.sequence_length)
        if feature_frame.empty:
            return pd.Series(dtype=float)

        x, _, meta = make_sequences(feature_frame, self.feature_columns, self.sequence_length, require_target=False)
        if len(x) == 0:
            return pd.Series(dtype=float)

        x = (x - self.mean) / self.std
        torch_module = require_torch()
        self.model.eval()
        with torch_module.no_grad():
            raw = (
                self.model(torch_module.tensor(x, dtype=torch_module.float32, device=self.device))
                .detach()
                .cpu()
                .numpy()
            )
        prediction_frame = meta.copy()
        prediction_frame["model_prediction"] = raw.astype(float)
        latest_date = asof.date().isoformat()
        latest = prediction_frame[prediction_frame["date"] == latest_date]
        if latest.empty:
            latest = prediction_frame[prediction_frame["date"] == prediction_frame["date"].max()]
        ranked = latest.set_index("symbol")["model_prediction"].rank(pct=True)
        ranked.name = "model_score"
        return ranked.astype(float)


def build_prediction_frame(
    prices: pd.DataFrame,
    config: StrategyConfig,
    asof: pd.Timestamp,
    sequence_length: int,
) -> pd.DataFrame:
    history = prices.loc[:asof].copy()
    dates = list(rebalance_dates(history, config.portfolio.rebalance))
    if not dates or pd.Timestamp(dates[-1]) != asof:
        dates.append(asof)
    dates = pd.DatetimeIndex(sorted(set(pd.Timestamp(date) for date in dates)))
    return build_feature_rows(
        prices=history,
        config=config,
        include_future=False,
        dates=dates,
    )


def load_transformer_predictor(path: str | Path, device: str | None = None) -> TransformerPredictor:
    torch_module = require_torch()
    device_name = choose_device(device)
    try:
        checkpoint = torch_module.load(Path(path), map_location=device_name, weights_only=False)
    except TypeError:
        checkpoint = torch_module.load(Path(path), map_location=device_name)
    model = PriceTransformer(**checkpoint["model_config"]).to(device_name)
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    return TransformerPredictor(
        model=model,
        feature_columns=list(checkpoint["feature_columns"]),
        sequence_length=int(checkpoint["model_config"]["sequence_length"]),
        mean=np.asarray(checkpoint["normalization"]["mean"], dtype=np.float32),
        std=np.asarray(checkpoint["normalization"]["std"], dtype=np.float32),
        device=device_name,
    )


@dataclass
class StaticPredictionProvider:
    predictions: pd.DataFrame

    def predict_scores(
        self,
        prices: pd.DataFrame,
        config: StrategyConfig,
        asof: pd.Timestamp | None = None,
    ) -> pd.Series:
        if self.predictions.empty:
            return pd.Series(dtype=float)
        if asof is None:
            asof = pd.Timestamp(prices.index[-1])
        date = pd.Timestamp(asof).date().isoformat()
        rows = self.predictions[self.predictions["date"].astype(str) == date]
        if rows.empty:
            return pd.Series(dtype=float)
        return rows.set_index("symbol")["model_score"].astype(float)


def walk_forward_transformer(
    prices: pd.DataFrame,
    config: StrategyConfig,
    out_dir: str | Path,
    horizon_days: int = 21,
    sequence_length: int = 12,
    initial_train_months: int = 24,
    epochs: int = 40,
    batch_size: int = 64,
    learning_rate: float = 1e-3,
    model_weight: float = 0.3,
    max_test_months: int | None = None,
    device: str | None = None,
) -> pd.DataFrame:
    from .backtest import run_backtest, write_backtest_outputs

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    dataset = build_ml_dataset(prices, config, horizon_days=horizon_days)
    dataset.to_csv(out / "dataset.csv", index=False)
    if dataset.empty:
        raise ValueError("Walk-forward dataset is empty.")

    dates = sorted(dataset["date"].unique())
    test_dates = dates[initial_train_months:]
    if max_test_months is not None:
        test_dates = test_dates[:max_test_months]
    if not test_dates:
        raise ValueError("Not enough monthly samples for the requested initial_train_months.")

    predictions: list[pd.DataFrame] = []
    model_dir = out / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    for test_date in test_dates:
        train_frame = dataset[dataset["date"] < test_date].copy()
        if train_frame["date"].nunique() < max(sequence_length + 1, 3):
            continue
        model_path = model_dir / f"transformer_{test_date}.pt"
        train_transformer(
            train_frame,
            model_path,
            sequence_length=sequence_length,
            epochs=epochs,
            batch_size=batch_size,
            learning_rate=learning_rate,
            device=device,
        )
        predictor = load_transformer_predictor(model_path, device=device)
        scores = predictor.predict_scores(prices.loc[:test_date], config, pd.Timestamp(test_date))
        if scores.empty:
            continue
        rows = scores.rename("model_score").reset_index()
        rows.insert(0, "date", test_date)
        predictions.append(rows)

    if predictions:
        prediction_frame = pd.concat(predictions, ignore_index=True)
    else:
        prediction_frame = pd.DataFrame(columns=["date", "symbol", "model_score"])
    prediction_frame.to_csv(out / "walk_forward_predictions.csv", index=False)

    rule_result = run_backtest(prices, config)
    provider = StaticPredictionProvider(prediction_frame)
    ml_result = run_backtest(prices, config, model_provider=provider, model_weight=model_weight)
    write_backtest_outputs(rule_result, out / "rule")
    write_backtest_outputs(ml_result, out / "ml_overlay")
    (out / "walk_forward_report.md").write_text(
        render_walk_forward_report(rule_result.summary, ml_result.summary, prediction_frame, model_weight),
        encoding="utf-8",
    )
    return prediction_frame


def render_walk_forward_report(
    rule_summary: dict[str, float | str],
    ml_summary: dict[str, float | str],
    predictions: pd.DataFrame,
    model_weight: float,
) -> str:
    lines = [
        "# Transformer Walk-Forward Report",
        "",
        f"- **model_weight**: {model_weight:.2f}",
        f"- **prediction_rows**: {len(predictions)}",
        f"- **prediction_months**: {predictions['date'].nunique() if not predictions.empty else 0}",
        "",
        "## Rule Baseline",
        "",
    ]
    lines.extend(render_summary_lines(rule_summary))
    lines.extend(["", "## ML Overlay", ""])
    lines.extend(render_summary_lines(ml_summary))
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Transformer predictions are generated in walk-forward order only.",
            "- The model only changes ranking scores; caps, affordability, defensive rules, and order rounding still apply.",
            "- Treat this as research output until the overlay beats the rule strategy out of sample after costs.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_summary_lines(summary: dict[str, float | str]) -> list[str]:
    lines: list[str] = []
    for key, value in summary.items():
        if isinstance(value, float):
            if "return" in key or "cagr" in key or "volatility" in key or "drawdown" in key:
                rendered = f"{value:.2%}"
            else:
                rendered = f"{value:,.2f}"
        else:
            rendered = str(value)
        lines.append(f"- **{key}**: {rendered}")
    return lines
