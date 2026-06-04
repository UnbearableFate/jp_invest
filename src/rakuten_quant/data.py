from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from .config import StrategyConfig


def load_price_csv(path: str | Path, config: StrategyConfig | None = None) -> pd.DataFrame:
    raw = pd.read_csv(path)
    if "date" not in raw.columns:
        raise ValueError("Price CSV must contain a 'date' column.")

    raw["date"] = pd.to_datetime(raw["date"])

    if "symbol" in raw.columns:
        raw["symbol"] = raw["symbol"].astype(str)

    if {"symbol", "close"}.issubset(raw.columns):
        prices = raw.pivot_table(index="date", columns="symbol", values="close", aggfunc="last")
    else:
        prices = raw.set_index("date")

    prices = prices.sort_index()
    prices.columns = prices.columns.astype(str)
    prices = prices.apply(pd.to_numeric, errors="coerce")
    prices = prices.dropna(how="all")
    prices = prices.ffill()

    if config is not None:
        prices = prepare_prices(prices, config)
    return prices


def prepare_prices(prices: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    prices = prices.copy()
    for asset in config.enabled_assets:
        if asset.data_symbol in prices.columns and asset.symbol not in prices.columns:
            prices[asset.symbol] = prices[asset.data_symbol]

    cash_symbol = config.cash_symbol
    if cash_symbol not in prices.columns:
        prices[cash_symbol] = 1.0

    missing = [symbol for symbol in config.symbols if symbol not in prices.columns]
    if missing:
        raise ValueError(f"Price data is missing configured symbols: {', '.join(missing)}")

    prices = prices[config.symbols]
    prices[cash_symbol] = prices[cash_symbol].fillna(1.0)
    return prices.ffill().dropna(how="all")


def fetch_yahoo_chart(
    config: StrategyConfig,
    start: str,
    end: str | None,
    out_path: str | Path,
    pause_seconds: float = 0.5,
) -> Path:
    """Download daily closes from Yahoo's chart endpoint.

    This is a convenience research downloader. For production research, prefer
    an auditable J-Quants/JPX/Rakuten export because Yahoo may throttle requests.
    """

    start_dt = pd.Timestamp(start).to_pydatetime().replace(tzinfo=timezone.utc)
    end_dt = (
        pd.Timestamp(end).to_pydatetime().replace(tzinfo=timezone.utc)
        if end
        else datetime.now(timezone.utc)
    )
    period1 = int(start_dt.timestamp())
    period2 = int(end_dt.timestamp())

    rows: list[dict[str, object]] = []
    for asset in config.enabled_assets:
        if asset.role == "cash":
            continue
        params = urlencode({"period1": period1, "period2": period2, "interval": "1d"})
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{asset.data_symbol}?{params}"
        request = Request(url, headers={"User-Agent": "rakuten-quant/0.1"})
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError) as exc:
            raise RuntimeError(f"Failed to download {asset.data_symbol}: {exc}") from exc

        result = payload.get("chart", {}).get("result")
        if not result:
            raise RuntimeError(f"Yahoo returned no chart data for {asset.data_symbol}.")

        chart = result[0]
        timestamps = chart.get("timestamp", [])
        closes = chart.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        for ts, close in zip(timestamps, closes, strict=False):
            if close is None:
                continue
            rows.append(
                {
                    "date": datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat(),
                    "symbol": asset.symbol,
                    "close": float(close),
                }
            )
        time.sleep(pause_seconds)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).sort_values(["date", "symbol"]).to_csv(out, index=False)
    return out


def fetch_jquants_v2_daily_quotes(
    config: StrategyConfig,
    start: str,
    end: str,
    out_path: str | Path,
    api_key: str | None = None,
    pause_seconds: float = 0.2,
) -> Path:
    """Download adjusted daily closes from J-Quants API V2.

    The API key is intentionally not read from config files. Use the
    JQUANTS_API_KEY environment variable or pass api_key from a secure caller.
    """

    api_key = api_key or os.environ.get("JQUANTS_API_KEY")
    if not api_key:
        raise ValueError("Set JQUANTS_API_KEY before downloading J-Quants data.")

    start_yyyymmdd = normalize_jquants_date(start)
    end_yyyymmdd = normalize_jquants_date(end)
    rows: list[dict[str, object]] = []

    for asset in config.enabled_assets:
        if asset.role == "cash":
            continue
        code = asset.jquants_code or asset.symbol
        page_key: str | None = None
        while True:
            params = {
                "code": code,
                "from": start_yyyymmdd,
                "to": end_yyyymmdd,
            }
            if page_key:
                params["pagination_key"] = page_key
            query = urlencode(params)
            url = f"https://api.jquants.com/v2/equities/bars/daily?{query}"
            request = Request(
                url,
                headers={
                    "x-api-key": api_key,
                    "User-Agent": "rakuten-quant/0.1",
                },
            )
            try:
                with urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                body = exc.read(500).decode("utf-8", errors="replace")
                raise RuntimeError(f"J-Quants HTTP {exc.code} for {asset.symbol}: {body}") from exc
            except URLError as exc:
                raise RuntimeError(f"J-Quants request failed for {asset.symbol}: {exc}") from exc

            for item in payload.get("data", []):
                close = item.get("AdjC", item.get("C"))
                if close is None:
                    continue
                rows.append(
                    {
                        "date": item["Date"],
                        "symbol": asset.symbol,
                        "close": float(close),
                    }
                )

            page_key = payload.get("pagination_key")
            if not page_key:
                break
            time.sleep(pause_seconds)
        time.sleep(pause_seconds)

    if not rows:
        raise RuntimeError("J-Quants returned no rows for the configured assets and date range.")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).sort_values(["date", "symbol"]).to_csv(out, index=False)
    return out


def normalize_jquants_date(value: str) -> str:
    return pd.Timestamp(value).strftime("%Y%m%d")
