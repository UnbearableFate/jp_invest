from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/sample_prices.csv")
    parser.add_argument("--start", default="2021-01-04")
    parser.add_argument("--end", default="2026-05-29")
    args = parser.parse_args()

    rng = np.random.default_rng(42)
    dates = pd.bdate_range(args.start, args.end)
    assets = {
        "1329": {"start": 3000.0, "drift": 0.00022, "vol": 0.010},
        "1655": {"start": 280.0, "drift": 0.00032, "vol": 0.012},
        "2559": {"start": 13500.0, "drift": 0.00026, "vol": 0.011},
        "1540": {"start": 6200.0, "drift": 0.00018, "vol": 0.009},
        "2510": {"start": 960.0, "drift": 0.00003, "vol": 0.002},
    }

    rows: list[dict[str, object]] = []
    market_shock = np.zeros(len(dates))
    shock_start = int(len(dates) * 0.58)
    market_shock[shock_start : shock_start + 30] = -0.006
    market_shock[shock_start + 30 : shock_start + 75] = 0.003

    for symbol, params in assets.items():
        prices = [params["start"]]
        for idx in range(1, len(dates)):
            common = market_shock[idx]
            defensive = symbol == "2510"
            shock = common * (0.15 if defensive else 1.0)
            daily_return = params["drift"] + shock + rng.normal(0.0, params["vol"])
            prices.append(max(prices[-1] * (1.0 + daily_return), 1.0))
        for date, close in zip(dates, prices, strict=True):
            rows.append({"date": date.date().isoformat(), "symbol": symbol, "close": round(close, 4)})

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out, index=False)
    print(out.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
