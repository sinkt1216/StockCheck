"""Shared weekly OHLC helpers for StockCheck trend modules."""

from __future__ import annotations

from typing import Any

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


def week_start_monday(week_end: str | pd.Timestamp) -> str:
    """Monday that opens the W-FRI week ending on the given Friday."""
    return (pd.Timestamp(week_end) - pd.Timedelta(days=4)).strftime("%Y-%m-%d")


def compute_weekly_volume_series(weekly: pd.DataFrame, *, ma_weeks: int = 20) -> pd.DataFrame:
    """Weekly share volume, its MA, and spike flag (volume > MA)."""
    vol = weekly["Volume"].astype(float)
    vma = vol.rolling(ma_weeks, min_periods=ma_weeks).mean()
    return pd.DataFrame(
        {
            "week_end": weekly.index.strftime("%Y-%m-%d"),
            "weekly_volume": vol.round(0).astype("int64"),
            "volume_ma20": vma.round(0),
            "volume_spike": (vol > vma).fillna(False),
        }
    )


def latest_volume_spike(weekly: pd.DataFrame, *, ma_weeks: int = 20) -> dict[str, Any]:
    series = compute_weekly_volume_series(weekly, ma_weeks=ma_weeks)
    if series.empty:
        return {"weekly_volume": None, "volume_ma20": None, "volume_spike": False}
    row = series.iloc[-1]
    vma = row["volume_ma20"]
    return {
        "weekly_volume": int(row["weekly_volume"]),
        "volume_ma20": int(vma) if pd.notna(vma) else None,
        "volume_spike": bool(row["volume_spike"]),
    }


def fetch_avg_volume_50d(symbol: str) -> int | None:
    """Mean daily share volume over the last 50 trading sessions."""
    symbol = symbol.upper()
    df = yf.Ticker(symbol).history(period="4mo", auto_adjust=True)
    if df.empty or "Volume" not in df.columns:
        return None
    vols = df["Volume"].dropna().tail(50)
    if len(vols) < 20:
        return None
    return int(round(vols.mean()))
