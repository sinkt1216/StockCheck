"""Standalone SPY regime analysis: MA slopes/spreads, MACD, RSI (no project trend state)."""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

DEFAULT_START = "2018-01-22"
DEFAULT_END = "2020-04-20"
MA_PERIODS = (10, 20, 50)
SLOPE_WEEKS = 4
RSI_PERIOD = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9


def fetch_daily(symbol: str, *, start: str, end: str) -> pd.DataFrame:
    buf = (pd.Timestamp(start) - pd.Timedelta(weeks=60)).strftime("%Y-%m-%d")
    fetch_end = (pd.Timestamp(end) + pd.Timedelta(weeks=20)).strftime("%Y-%m-%d")
    t = yf.Ticker(symbol)
    df = t.history(start=buf, end=fetch_end, auto_adjust=True)
    if df.empty:
        raise RuntimeError(f"No data for {symbol}")
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    w = daily.resample("W-FRI").agg({"Close": "last", "Volume": "sum"}).dropna()
    return w


def _slope_pct(series: pd.Series, window: int, idx: int) -> float:
    if idx < window - 1:
        return float("nan")
    y = series.iloc[idx - window + 1 : idx + 1].astype(float).values
    if len(y) < window or np.any(np.isnan(y)) or y[-1] == 0:
        return float("nan")
    x = np.arange(window, dtype=float)
    slope = float(np.polyfit(x, y, 1)[0])
    return slope / y[-1] * 100.0


def rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = close.ewm(span=MACD_FAST, adjust=False).mean()
    ema_slow = close.ewm(span=MACD_SLOW, adjust=False).mean()
    line = ema_fast - ema_slow
    signal = line.ewm(span=MACD_SIGNAL, adjust=False).mean()
    hist = line - signal
    return line, signal, hist


def enrich_weekly(weekly: pd.DataFrame) -> pd.DataFrame:
    close = weekly["Close"].astype(float)
    out = weekly.copy()
    for p in MA_PERIODS:
        out[f"ma{p}"] = close.rolling(p, min_periods=p).mean()

    for p in MA_PERIODS:
        slopes = []
        ma = out[f"ma{p}"]
        for i in range(len(out)):
            slopes.append(_slope_pct(ma, SLOPE_WEEKS, i))
        out[f"slope{p}w"] = slopes
        out[f"slope{p}_d1w"] = ma.pct_change() * 100

    out["spread_10_20_pct"] = (out["ma10"] - out["ma20"]) / out["ma20"] * 100
    out["spread_20_50_pct"] = (out["ma20"] - out["ma50"]) / out["ma50"] * 100
    out["spread_10_50_pct"] = (out["ma10"] - out["ma50"]) / out["ma50"] * 100

    out["rsi"] = rsi(close)
    macd_line, macd_sig, macd_hist = macd(close)
    out["macd"] = macd_line
    out["macd_signal"] = macd_sig
    out["macd_hist"] = macd_hist
    out["macd_hist_d1w"] = macd_hist.diff()

    out["close_dd_26w_pct"] = (close / close.rolling(26, min_periods=26).max() - 1) * 100
    out["week"] = out.index.strftime("%Y-%m-%d")
    return out


@dataclass
class Episode:
    name: str
    peak_week: str
    trough_week: str
    peak_close: float
    trough_close: float


EPISODES_2018_2020 = [
    Episode("Feb 2018 correction", "2018-01-26", "2018-02-09", 281.0, 258.0),
    Episode("Q4 2018 bear", "2018-09-21", "2018-12-24", 293.0, 235.0),
    Episode("May 2019 pullback", "2019-04-26", "2019-06-03", 294.0, 275.0),
    Episode("COVID crash", "2020-02-14", "2020-03-20", 338.0, 230.0),
]

EPISODES_2007_2009 = [
    Episode("Aug 2007 flare-up", "2007-07-20", "2007-08-17", 147.0, 138.0),
    Episode("Oct07-Mar08 first leg", "2007-10-05", "2008-03-14", 157.0, 127.0),
    Episode("2008 GFC crash leg", "2008-08-29", "2008-11-21", 130.0, 78.0),
    Episode("Full bear Oct07-Mar09", "2007-10-05", "2009-03-06", 157.0, 68.0),
]


def nearest_row(df: pd.DataFrame, date_str: str) -> pd.Series:
    ts = pd.Timestamp(date_str)
    idx = df.index.get_indexer([ts], method="nearest")[0]
    return df.iloc[idx]


def fmt(v: Any, w: int = 7) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return f"{'':>{w}}"
    return f"{float(v):+{w - 1}.2f}%" if w > 1 else str(v)


def snapshot_row(row: pd.Series) -> str:
    return (
        f"{row['week']}  close=${row['Close']:.2f}  "
        f"slp10={fmt(row['slope10w'], 6).strip()} slp20={fmt(row['slope20w'], 6).strip()} slp50={fmt(row['slope50w'], 6).strip()}  "
        f"10-20={fmt(row['spread_10_20_pct'], 6).strip()} 20-50={fmt(row['spread_20_50_pct'], 6).strip()}  "
        f"RSI={row['rsi']:.1f}  MACD_hist={row['macd_hist']:.2f}  dd26w={row['close_dd_26w_pct']:.1f}%"
    )


def find_first_cross(df: pd.DataFrame, col: str, direction: str, after: str, before: str) -> str | None:
    sub = df.loc[after:before]
    if sub.empty:
        return None
    if direction == "below_zero":
        hits = sub[sub[col] < 0]
    elif direction == "above_zero":
        hits = sub[sub[col] > 0]
    elif direction == "rsi_below_50":
        hits = sub[sub["rsi"] < 50]
    elif direction == "rsi_above_50":
        hits = sub[sub["rsi"] > 50]
    elif direction == "macd_cross_down":
        hits = sub[sub["macd"] < sub["macd_signal"]]
    elif direction == "macd_cross_up":
        hits = sub[sub["macd"] > sub["macd_signal"]]
    else:
        return None
    if hits.empty:
        return None
    return hits.index[0].strftime("%Y-%m-%d")


def analyze_episode(df: pd.DataFrame, ep: Episode) -> dict[str, Any]:
    peak = nearest_row(df, ep.peak_week)
    trough = nearest_row(df, ep.trough_week)
    dd = (trough["Close"] / peak["Close"] - 1) * 100

    win_start = (pd.Timestamp(ep.peak_week) - pd.Timedelta(weeks=8)).strftime("%Y-%m-%d")
    win_end = (pd.Timestamp(ep.trough_week) + pd.Timedelta(weeks=8)).strftime("%Y-%m-%d")
    window = df.loc[win_start:win_end]

    recovery = df.loc[ep.trough_week : (pd.Timestamp(ep.trough_week) + pd.Timedelta(weeks=16)).strftime("%Y-%m-%d")]

    return {
        "name": ep.name,
        "drawdown": dd,
        "peak": snapshot_row(peak),
        "trough": snapshot_row(trough),
        "first_spread_10_20_neg": find_first_cross(df, "spread_10_20_pct", "below_zero", win_start, ep.trough_week),
        "first_spread_20_50_neg": find_first_cross(df, "spread_20_50_pct", "below_zero", win_start, ep.trough_week),
        "first_slope10_neg": find_first_cross(df, "slope10w", "below_zero", win_start, ep.trough_week),
        "first_slope20_neg": find_first_cross(df, "slope20w", "below_zero", win_start, ep.trough_week),
        "first_slope50_neg": find_first_cross(df, "slope50w", "below_zero", win_start, ep.trough_week),
        "first_rsi_below_50": find_first_cross(df, "rsi", "rsi_below_50", win_start, ep.trough_week),
        "first_rsi_below_40": find_first_cross(
            df, "rsi", "rsi_below_50", win_start, ep.trough_week
        ),
        "first_macd_cross_down": find_first_cross(df, "macd", "macd_cross_down", win_start, ep.trough_week),
        "trough_rsi": float(trough["rsi"]) if not math.isnan(trough["rsi"]) else None,
        "recovery_rsi_above_50": find_first_cross(recovery, "rsi", "rsi_above_50", ep.trough_week, recovery.index[-1].strftime("%Y-%m-%d")),
        "recovery_macd_cross_up": find_first_cross(recovery, "macd", "macd_cross_up", ep.trough_week, recovery.index[-1].strftime("%Y-%m-%d")),
        "recovery_slope10_pos": find_first_cross(recovery, "slope10w", "above_zero", ep.trough_week, recovery.index[-1].strftime("%Y-%m-%d")),
        "recovery_spread_10_20_pos": find_first_cross(recovery, "spread_10_20_pct", "above_zero", ep.trough_week, recovery.index[-1].strftime("%Y-%m-%d")),
        "window": window,
    }


def _weeks_from_peak_trough(
    full_df: pd.DataFrame, peak_week: str, trough_week: str, signal_date: str | None
) -> str:
    if not signal_date:
        return "n/a"
    peak_ts = pd.Timestamp(peak_week)
    sig_ts = pd.Timestamp(signal_date)
    return f"{(sig_ts - peak_ts).days // 7}w after peak"


def _weeks_from_trough_recovery(trough_week: str, signal_date: str | None) -> str:
    if not signal_date:
        return "n/a"
    trough_ts = pd.Timestamp(trough_week)
    sig_ts = pd.Timestamp(signal_date)
    return f"{(sig_ts - trough_ts).days // 7}w after trough"


def main() -> None:
    parser = argparse.ArgumentParser(description="SPY weekly MA/MACD/RSI regime analysis")
    parser.add_argument("--from", dest="start", default=DEFAULT_START)
    parser.add_argument("--to", dest="end", default=DEFAULT_END)
    parser.add_argument(
        "--period",
        choices=("2018-2020", "2007-2009"),
        default="2018-2020",
        help="Episode set for signal timing analysis",
    )
    args = parser.parse_args()
    episodes = EPISODES_2007_2009 if args.period == "2007-2009" else EPISODES_2018_2020

    daily = fetch_daily("SPY", start=args.start, end=args.end)
    weekly = to_weekly(daily)
    full_df = enrich_weekly(weekly)
    df = full_df.loc[args.start : args.end]

    print("SPY indicator regime analysis (weekly bars, W-FRI close)")
    print(f"Period: {args.start} to {args.end}")
    print(f"MA slopes: {SLOPE_WEEKS}-week linear regression, normalized as %/week")
    print(f"MA spreads: (short-long)/long * 100")
    print(f"RSI({RSI_PERIOD}), MACD({MACD_FAST}/{MACD_SLOW}/{MACD_SIGNAL}) on weekly close")
    print("=" * 100)

    print("\nFULL WEEKLY TABLE")
    print("-" * 100)
    hdr = (
        f"{'Week':<11} {'Close':>8} "
        f"{'slp10':>7} {'slp20':>7} {'slp50':>7} "
        f"{'10-20':>7} {'20-50':>7} {'10-50':>7} "
        f"{'RSI':>5} {'MACD':>7} {'Sig':>7} {'Hist':>7} {'dd26w':>7}"
    )
    print(hdr)
    print("-" * 100)
    for _, row in df.iterrows():
        print(
            f"{row['week']:<11} "
            f"${row['Close']:>7.2f} "
            f"{fmt(row['slope10w'], 7)} {fmt(row['slope20w'], 7)} {fmt(row['slope50w'], 7)} "
            f"{fmt(row['spread_10_20_pct'], 7)} {fmt(row['spread_20_50_pct'], 7)} {fmt(row['spread_10_50_pct'], 7)} "
            f"{row['rsi']:>5.1f} "
            f"{row['macd']:>7.2f} {row['macd_signal']:>7.2f} {row['macd_hist']:>7.2f} "
            f"{row['close_dd_26w_pct']:>6.1f}%"
        )

    print("\n" + "=" * 100)
    print("EPISODE ANALYSIS")
    print("=" * 100)

    start_signals = [
        ("slope10 < 0", "first_slope10_neg"),
        ("slope20 < 0", "first_slope20_neg"),
        ("slope50 < 0", "first_slope50_neg"),
        ("spread 10-20 < 0", "first_spread_10_20_neg"),
        ("spread 20-50 < 0", "first_spread_20_50_neg"),
        ("RSI < 50", "first_rsi_below_50"),
        ("MACD < signal", "first_macd_cross_down"),
    ]

    for ep in episodes:
        a = analyze_episode(full_df, ep)
        print(f"\n### {a['name']} (drawdown ~{a['drawdown']:.1f}%)")
        print(f"  Peak:   {a['peak']}")
        print(f"  Trough: {a['trough']}")
        print("  START signals (first occurrence peak -> trough):")
        for label, key in start_signals:
            dt = a[key]
            timing = _weeks_from_peak_trough(full_df, ep.peak_week, ep.trough_week, dt)
            print(f"    {label + ':':<22} {dt or 'None':<12} ({timing})")
        if a["trough_rsi"]:
            print(f"    RSI at trough:        {a['trough_rsi']:.1f}")
        print("  END / recovery signals (trough -> +16 weeks):")
        recovery_signals = [
            ("RSI > 50", "recovery_rsi_above_50"),
            ("MACD > signal", "recovery_macd_cross_up"),
            ("slope10 > 0", "recovery_slope10_pos"),
            ("spread 10-20 > 0", "recovery_spread_10_20_pos"),
        ]
        for label, key in recovery_signals:
            dt = a[key]
            timing = _weeks_from_trough_recovery(ep.trough_week, dt)
            print(f"    {label + ':':<22} {dt or 'None':<12} ({timing})")

    print("\n" + "=" * 100)
    print("SENSITIVITY RANKING (earliest START signal per episode)")
    print("=" * 100)
    for ep in episodes:
        a = analyze_episode(full_df, ep)
        ranked = []
        for label, key in start_signals:
            dt = a[key]
            if dt:
                ranked.append((pd.Timestamp(dt), label, _weeks_from_peak_trough(full_df, ep.peak_week, ep.trough_week, dt)))
        ranked.sort()
        order = " -> ".join(f"{lbl} ({wk})" for _, lbl, wk in ranked) if ranked else "(no signals)"
        print(f"  {ep.name}: {order}")


if __name__ == "__main__":
    main()
