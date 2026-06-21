"""Shared weekly OHLC helpers for StockCheck trend modules."""

from __future__ import annotations

import pandas as pd
import yfinance as yf


def fetch_weekly_ohlc(symbol: str, period: str = "10y") -> pd.DataFrame:
    symbol = symbol.upper()
    df = yf.Ticker(symbol).history(period=period, auto_adjust=True)
    if df.empty:
        raise RuntimeError(f"No price history returned for {symbol}")

    weekly = df.resample("W-FRI").agg(
        {
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }
    )
    weekly = weekly.dropna(subset=["Close"])
    weekly.index = pd.to_datetime(weekly.index).tz_localize(None)
    return weekly
