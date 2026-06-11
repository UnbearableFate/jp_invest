from __future__ import annotations

from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from .config import StrategyConfig


JQUANTS_LOOKBACK_YEARS = 5


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
    today: date | None = None,
) -> Path:
    """Download adjusted daily closes from J-Quants API V2.

    The API key is intentionally not read from config files. Use the
    JQUANTS_API_KEY environment variable or pass api_key from a secure caller.
    Existing local rows are treated as a cache and merged with new API rows.
    API requests are clipped to J-Quants' rolling five-year access window.
    """

    api_key = api_key or os.environ.get("JQUANTS_API_KEY")
    if not api_key:
        raise ValueError("Set JQUANTS_API_KEY before downloading J-Quants data.")

    requested_start = pd.Timestamp(start).normalize()
    requested_end = pd.Timestamp(end).normalize()
    if requested_end < requested_start:
        raise ValueError("J-Quants end date must be on or after start date.")

    api_start = clamp_jquants_start(requested_start, today=today)
    out = Path(out_path)
    cached = load_cached_price_rows(out, config)
    rows: list[dict[str, object]] = []

    for asset in config.enabled_assets:
        if asset.role == "cash":
            continue
        fetch_start = next_fetch_start(cached, asset.symbol, api_start, requested_end)
        if fetch_start is None:
            continue
        rows.extend(
            download_jquants_symbol_rows(
                asset_symbol=asset.symbol,
                jquants_code=asset.jquants_code or asset.symbol,
                start=fetch_start,
                end=requested_end,
                api_key=api_key,
                pause_seconds=pause_seconds,
            )
        )

    combined = merge_price_rows(cached, pd.DataFrame(rows))
    if combined.empty:
        raise RuntimeError("J-Quants returned no rows and no cached rows are available.")

    out.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out, index=False)
    return out


def normalize_jquants_date(value: str) -> str:
    return pd.Timestamp(value).strftime("%Y%m%d")


def default_jquants_start(today: date | None = None) -> str:
    return jquants_min_download_start(today=today).date().isoformat()


def jquants_min_download_start(today: date | None = None) -> pd.Timestamp:
    base = pd.Timestamp(today or date.today()).normalize()
    return base - pd.DateOffset(years=JQUANTS_LOOKBACK_YEARS)


def clamp_jquants_start(start: str | pd.Timestamp, today: date | None = None) -> pd.Timestamp:
    requested = pd.Timestamp(start).normalize()
    minimum = jquants_min_download_start(today=today)
    return max(requested, minimum)


def load_cached_price_rows(path: str | Path, config: StrategyConfig) -> pd.DataFrame:
    file_path = Path(path)
    if not file_path.exists() or file_path.stat().st_size == 0:
        return empty_price_rows()

    raw = pd.read_csv(file_path)
    if raw.empty:
        return empty_price_rows()
    if not {"date", "symbol", "close"}.issubset(raw.columns):
        return empty_price_rows()

    frame = raw[["date", "symbol", "close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date.astype(str)
    frame["symbol"] = frame["symbol"].astype(str)
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["date", "symbol", "close"])
    return normalize_price_rows(frame)


def empty_price_rows() -> pd.DataFrame:
    return pd.DataFrame(columns=["date", "symbol", "close"])


def next_fetch_start(
    cached: pd.DataFrame,
    symbol: str,
    api_start: pd.Timestamp,
    requested_end: pd.Timestamp,
) -> pd.Timestamp | None:
    if api_start > requested_end:
        return None

    if cached.empty:
        return api_start

    symbol_rows = cached[cached["symbol"] == symbol]
    if symbol_rows.empty:
        return api_start

    latest_cached = pd.to_datetime(symbol_rows["date"]).max().normalize()
    if latest_cached >= requested_end:
        return None
    return max(api_start, latest_cached + pd.Timedelta(days=1))


def download_jquants_symbol_rows(
    asset_symbol: str,
    jquants_code: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    api_key: str,
    pause_seconds: float,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    start_yyyymmdd = normalize_jquants_date(start.isoformat())
    end_yyyymmdd = normalize_jquants_date(end.isoformat())
    page_key: str | None = None

    while True:
        params = {
            "code": jquants_code,
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
            raise RuntimeError(f"J-Quants HTTP {exc.code} for {asset_symbol}: {body}") from exc
        except URLError as exc:
            raise RuntimeError(f"J-Quants request failed for {asset_symbol}: {exc}") from exc

        for item in payload.get("data", []):
            close = item.get("AdjC", item.get("C"))
            if close is None:
                continue
            rows.append(
                {
                    "date": item["Date"],
                    "symbol": asset_symbol,
                    "close": float(close),
                }
            )

        page_key = payload.get("pagination_key")
        if not page_key:
            break
        time.sleep(pause_seconds)
    time.sleep(pause_seconds)
    return rows


def merge_price_rows(cached: pd.DataFrame, downloaded: pd.DataFrame) -> pd.DataFrame:
    frames = []
    if cached is not None and not cached.empty:
        frames.append(cached)
    if downloaded is not None and not downloaded.empty:
        frames.append(downloaded)
    if not frames:
        return empty_price_rows()
    return normalize_price_rows(pd.concat(frames, ignore_index=True))


def normalize_price_rows(frame: pd.DataFrame) -> pd.DataFrame:
    rows = frame[["date", "symbol", "close"]].copy()
    rows["date"] = pd.to_datetime(rows["date"]).dt.date.astype(str)
    rows["symbol"] = rows["symbol"].astype(str)
    rows["close"] = pd.to_numeric(rows["close"], errors="coerce")
    rows = rows.dropna(subset=["date", "symbol", "close"])
    rows = rows.drop_duplicates(["date", "symbol"], keep="last")
    return rows.sort_values(["date", "symbol"]).reset_index(drop=True)
