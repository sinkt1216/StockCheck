"""Mean-reversion trend analysis for any symbol (DeanFi methodology via yfinance)."""

from __future__ import annotations

import math
import sys
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import yfinance as yf

MA_PERIODS = (20, 50, 200)
ZSCORE_LOOKBACK = 252
FETCH_DAYS = 956
MA_PAIRS = (
    (20, 50, "short_term_vs_intermediate", "20 vs 50 "),
    (20, 200, "short_term_vs_long_term", "20 vs 200"),
    (50, 200, "intermediate_vs_long_term", "50 vs 200"),
)


def _safe_float(value: Any, decimals: int = 2) -> float | None:
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return None
    return round(float(value), decimals)


def determine_signal(zscore: float | None, threshold: float = 2.0) -> str:
    if zscore is None or (isinstance(zscore, float) and math.isnan(zscore)):
        return "insufficient_data"
    if zscore > threshold:
        return "extremely_overbought"
    if zscore > 1:
        return "moderately_overbought"
    if zscore < -threshold:
        return "extremely_oversold"
    if zscore < -1:
        return "moderately_oversold"
    return "normal_range"


def determine_trend_alignment(ma_20: float, ma_50: float, ma_200: float) -> str:
    if any(math.isnan(v) for v in (ma_20, ma_50, ma_200)):
        return "insufficient_data"
    if ma_20 > ma_50 > ma_200:
        return "strong_bullish"
    if ma_20 > ma_50:
        return "moderate_bullish"
    if ma_20 < ma_50 < ma_200:
        return "strong_bearish"
    if ma_20 < ma_50:
        return "moderate_bearish"
    return "mixed"


def _zscore(series: pd.Series, lookback: int = ZSCORE_LOOKBACK) -> pd.Series:
    rolling_mean = series.rolling(window=lookback, min_periods=lookback).mean()
    rolling_std = series.rolling(window=lookback, min_periods=lookback).std()
    return (series - rolling_mean) / rolling_std


def fetch_prices(symbol: str, period: str = "5y") -> pd.Series:
    df = yf.Ticker(symbol).history(period=period)
    if df.empty:
        raise RuntimeError(f"No price history returned for {symbol}")
    return df["Close"].tail(FETCH_DAYS)


def analyze_symbol(symbol: str) -> dict[str, Any]:
    symbol = symbol.upper()
    prices = fetch_prices(symbol)
    if len(prices) < 200:
        raise RuntimeError(f"Insufficient history for {symbol}: {len(prices)} days")

    mas = {p: prices.rolling(window=p, min_periods=p).mean() for p in MA_PERIODS}
    latest_price = float(prices.iloc[-1])
    latest_date = prices.index[-1].strftime("%Y-%m-%d")

    metrics_by_ma: dict[str, dict[str, Any]] = {}
    for period in MA_PERIODS:
        ma = mas[period]
        distance = prices - ma
        distance_pct = (distance / ma) * 100
        zscore = _zscore(distance)
        metrics_by_ma[f"ma_{period}"] = {
            "distance": _safe_float(distance.iloc[-1]),
            "distance_percent": _safe_float(distance_pct.iloc[-1]),
            "zscore": _safe_float(zscore.iloc[-1]),
            "signal": determine_signal(zscore.iloc[-1]),
        }

    ma_pairs: dict[str, dict[str, Any]] = {}
    for short, long, key, _label in MA_PAIRS:
        spread = mas[short] - mas[long]
        spread_pct = (spread / mas[long]) * 100
        zscore = _zscore(spread)
        spread_val = spread.iloc[-1]
        alignment = "bullish" if spread_val > 0 else "bearish"
        ma_pairs[key] = {
            "ma_short": short,
            "ma_long": long,
            "spread": _safe_float(spread_val),
            "spread_percent": _safe_float(spread_pct.iloc[-1]),
            "zscore": _safe_float(zscore.iloc[-1]),
            "signal": determine_signal(zscore.iloc[-1]),
            "alignment": alignment,
            "alignment_note": f"{short}-day MA is {'above' if spread_val > 0 else 'below'} {long}-day MA",
        }

    ma_values = {f"ma_{p}": _safe_float(mas[p].iloc[-1]) for p in MA_PERIODS}
    trend = determine_trend_alignment(
        mas[20].iloc[-1], mas[50].iloc[-1], mas[200].iloc[-1]
    )

    return {
        "symbol": symbol,
        "date": latest_date,
        "current_price": _safe_float(latest_price),
        "trend_alignment": trend,
        "moving_averages": ma_values,
        "metrics_by_ma": metrics_by_ma,
        "ma_pairs": ma_pairs,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "method": "DeanFi mean reversion (20/50/200 SMA, 252-day z-score lookback)",
    }


def summarize(analysis: dict[str, Any]) -> str:
    symbol = analysis["symbol"]
    lines = [
        f"Trend Analysis — {symbol} (DeanFi method)",
        "=" * 40,
        f"Trading date:     {analysis['date']}",
        f"Price:            ${analysis['current_price']}",
        f"Trend alignment:  {analysis['trend_alignment']}",
        "",
        "Price vs MA:",
    ]
    for period, label in ((20, "20-day"), (50, "50-day"), (200, "200-day")):
        m = analysis["metrics_by_ma"][f"ma_{period}"]
        lines.append(
            f"  {label:8} {m['distance_percent']}% "
            f"(z={m['zscore']}, {m['signal']})"
        )

    lines.append("MA spreads:")
    for _short, _long, key, label in MA_PAIRS:
        p = analysis["ma_pairs"][key]
        lines.append(
            f"  {label}: spread {p['spread_percent']}% "
            f"(z={p['zscore']}, {p['signal']}, {p['alignment']})"
        )

    lines.extend(["", _interpret(analysis)])
    return "\n".join(lines)


def _interpret(analysis: dict[str, Any]) -> str:
    trend = analysis["trend_alignment"]
    z200 = analysis["metrics_by_ma"]["ma_200"]["zscore"]
    price = analysis["current_price"]
    ma200 = analysis["moving_averages"]["ma_200"]

    parts = [f"Summary: {trend.replace('_', ' ')} MA stack"]
    if price is not None and ma200 is not None:
        parts.append(
            "price above 200-day MA (long-term uptrend)"
            if price > ma200
            else "price below 200-day MA (long-term downtrend)"
        )
    if z200 is not None:
        if z200 > 2:
            parts.append("statistically stretched above 200-day MA — mean reversion risk elevated")
        elif z200 > 1:
            parts.append("moderately extended above 200-day MA")
        elif z200 < -2:
            parts.append("statistically stretched below 200-day MA — potential bounce zone")
        elif z200 < -1:
            parts.append("moderately depressed vs 200-day MA")
        else:
            parts.append("distance from 200-day MA within normal range")
    return "Interpretation: " + "; ".join(parts) + "."


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python src/trend_analysis.py SYMBOL", file=sys.stderr)
        return 1
    symbol = sys.argv[1].upper()
    try:
        analysis = analyze_symbol(symbol)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(summarize(analysis))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
