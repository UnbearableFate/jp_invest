from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class AssetConfig:
    symbol: str
    data_symbol: str
    name: str
    asset_class: str
    role: str
    max_weight: float
    jquants_code: str = ""
    min_trade_unit: int = 1
    slippage_bps: float = 0.0
    enabled: bool = True


@dataclass(frozen=True)
class PortfolioConfig:
    capital_jpy: float
    cash_floor_jpy: float
    benchmark_symbol: str
    rebalance: str
    risk_check: str
    max_drawdown_target: float
    risk_reduce_drawdown: float
    full_defense_drawdown: float
    min_trade_jpy: float
    rebalance_threshold: float
    max_positions: int
    transaction_cost_bps: float

    @property
    def cash_floor_weight(self) -> float:
        return min(max(self.cash_floor_jpy / self.capital_jpy, 0.0), 1.0)


@dataclass(frozen=True)
class SignalConfig:
    momentum_fast_days: int
    momentum_slow_days: int
    skip_days: int
    volatility_days: int
    trend_days: int

    @property
    def min_history_days(self) -> int:
        return max(
            self.momentum_slow_days + self.skip_days,
            self.trend_days,
            self.volatility_days + 1,
        )


@dataclass(frozen=True)
class StrategyConfig:
    portfolio: PortfolioConfig
    signals: SignalConfig
    assets: tuple[AssetConfig, ...]

    @property
    def enabled_assets(self) -> tuple[AssetConfig, ...]:
        return tuple(asset for asset in self.assets if asset.enabled)

    @property
    def symbols(self) -> list[str]:
        return [asset.symbol for asset in self.enabled_assets]

    @property
    def cash_symbol(self) -> str:
        cash_assets = [asset.symbol for asset in self.enabled_assets if asset.role == "cash"]
        if not cash_assets:
            raise ValueError("Config must include exactly one cash asset.")
        if len(cash_assets) > 1:
            raise ValueError("Config must include only one cash asset.")
        return cash_assets[0]

    def asset(self, symbol: str) -> AssetConfig:
        for asset in self.enabled_assets:
            if asset.symbol == symbol:
                return asset
        raise KeyError(f"Unknown enabled asset: {symbol}")

    def by_role(self, role: str) -> list[AssetConfig]:
        return [asset for asset in self.enabled_assets if asset.role == role]

    def symbol_for_data_symbol(self, data_symbol: str) -> str:
        for asset in self.enabled_assets:
            if asset.data_symbol == data_symbol:
                return asset.symbol
        return data_symbol


def load_config(path: str | Path) -> StrategyConfig:
    with Path(path).open("rb") as file:
        raw = tomllib.load(file)

    portfolio = PortfolioConfig(**raw["portfolio"])
    signals = SignalConfig(**raw["signals"])
    assets = tuple(AssetConfig(**item) for item in raw["assets"])
    config = StrategyConfig(portfolio=portfolio, signals=signals, assets=assets)
    validate_config(config)
    return config


def validate_config(config: StrategyConfig) -> None:
    if config.portfolio.capital_jpy <= 0:
        raise ValueError("capital_jpy must be positive.")
    if config.portfolio.cash_floor_jpy < 0:
        raise ValueError("cash_floor_jpy cannot be negative.")
    if config.portfolio.max_positions < 1:
        raise ValueError("max_positions must be at least 1.")
    if not 0 <= config.portfolio.rebalance_threshold <= 1:
        raise ValueError("rebalance_threshold must be a weight between 0 and 1.")
    if config.portfolio.risk_reduce_drawdown > config.portfolio.full_defense_drawdown:
        raise ValueError("risk_reduce_drawdown cannot exceed full_defense_drawdown.")

    symbols = [asset.symbol for asset in config.enabled_assets]
    if len(symbols) != len(set(symbols)):
        raise ValueError("Asset symbols must be unique.")
    _ = config.cash_symbol

    for asset in config.enabled_assets:
        if asset.max_weight < 0 or asset.max_weight > 1:
            raise ValueError(f"{asset.symbol} max_weight must be between 0 and 1.")
        if asset.min_trade_unit < 1:
            raise ValueError(f"{asset.symbol} min_trade_unit must be at least 1.")
