"""S&P 500 weekly breadth: 52w high/low ratio and % above MA10/MA20 for regime episodes."""

from __future__ import annotations

import argparse
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from spy_indicator_regime import (  # noqa: E402
    EPISODES_2007_2009,
    EPISODES_2018_2020,
    Episode,
)

WEEKLY_MA = (10, 20)
HIGH_LOW_WEEKS = 52
NEAR_PCT = 0.01  # within 1% of 52w extreme (DeanFi style)


def fetch_sp500_tickers() -> list[str]:
    url = (
        "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/"
        "master/data/constituents.csv"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "StockCheck/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        df = pd.read_csv(resp)
    symbols = df["Symbol"].astype(str).str.replace(".", "-", regex=False).tolist()
    return symbols


def download_weekly_closes(
    symbols: list[str],
    *,
    start: str,
    end: str,
    chunk: int = 80,
) -> pd.DataFrame:
    buf_start = (pd.Timestamp(start) - pd.Timedelta(weeks=HIGH_LOW_WEEKS + 10)).strftime("%Y-%m-%d")
    fetch_end = (pd.Timestamp(end) + pd.Timedelta(weeks=4)).strftime("%Y-%m-%d")
    frames: list[pd.DataFrame] = []
    ok: list[str] = []

    for i in range(0, len(symbols), chunk):
        batch = symbols[i : i + chunk]
        raw = yf.download(
            batch,
            start=buf_start,
            end=fetch_end,
            group_by="ticker",
            auto_adjust=True,
            threads=True,
            progress=False,
        )
        if raw.empty:
            continue
        if len(batch) == 1:
            sym = batch[0]
            if "Close" in raw.columns:
                s = raw["Close"].rename(sym)
                frames.append(s.to_frame())
                ok.append(sym)
            continue
        for sym in batch:
            try:
                s = raw[sym]["Close"].rename(sym)
                if s.notna().sum() > HIGH_LOW_WEEKS:
                    frames.append(s.to_frame())
                    ok.append(sym)
            except (KeyError, TypeError):
                continue

    if not frames:
        raise RuntimeError("No symbol data downloaded")

    daily = pd.concat(frames, axis=1).sort_index()
    daily.index = pd.to_datetime(daily.index).tz_localize(None)
    weekly = daily.resample("W-FRI").last()
    return weekly


def compute_breadth(weekly: pd.DataFrame) -> pd.DataFrame:
    close = weekly.astype(float)
    n = close.notna().sum(axis=1)
    rows: list[dict] = []

    roll_high = close.rolling(HIGH_LOW_WEEKS, min_periods=HIGH_LOW_WEEKS).max()
    roll_low = close.rolling(HIGH_LOW_WEEKS, min_periods=HIGH_LOW_WEEKS).min()

    ma = {p: close.rolling(p, min_periods=p).mean() for p in WEEKLY_MA}

    for dt in close.index:
        c = close.loc[dt]
        valid = c.notna()
        if valid.sum() < 50:
            continue
        c = c[valid]
        rh = roll_high.loc[dt, valid]
        rl = roll_low.loc[dt, valid]
        near_high = (c >= rh * (1 - NEAR_PCT)).sum()
        near_low = (c <= rl * (1 + NEAR_PCT)).sum()
        hl_ratio = near_high / near_low if near_low > 0 else float("nan")

        above10 = (c > ma[10].loc[dt, valid]).sum()
        above20 = (c > ma[20].loc[dt, valid]).sum()
        above_both = ((c > ma[10].loc[dt, valid]) & (c > ma[20].loc[dt, valid])).sum()
        total = int(valid.sum())
        rows.append(
            {
                "week": dt.strftime("%Y-%m-%d"),
                "stocks": total,
                "near_52w_high": int(near_high),
                "near_52w_low": int(near_low),
                "hl_ratio": hl_ratio,
                "pct_above_ma10": above10 / total * 100,
                "pct_above_ma20": above20 / total * 100,
                "pct_above_both": above_both / total * 100,
            }
        )
    df = pd.DataFrame(rows)
    df["week"] = pd.to_datetime(df["week"])
    return df.set_index("week")


def breadth_snapshot(row: pd.Series) -> str:
    return (
        f"nh={int(row['near_52w_high'])} nl={int(row['near_52w_low'])} "
        f"ratio={row['hl_ratio']:.2f}  "
        f">MA10={row['pct_above_ma10']:.1f}% >MA20={row['pct_above_ma20']:.1f}% "
        f">both={row['pct_above_both']:.1f}%"
    )


def find_first_breadth_signal(
    breadth: pd.DataFrame,
    *,
    after: str,
    before: str,
    condition: str,
) -> str | None:
    sub = breadth.loc[pd.Timestamp(after) : pd.Timestamp(before)]
    if sub.empty:
        return None
    if condition == "hl_ratio_below_1":
        hits = sub[sub["hl_ratio"] < 1.0]
    elif condition == "hl_ratio_below_0_5":
        hits = sub[sub["hl_ratio"] < 0.5]
    elif condition == "pct_ma20_below_50":
        hits = sub[sub["pct_above_ma20"] < 50]
    elif condition == "pct_ma20_below_30":
        hits = sub[sub["pct_above_ma20"] < 30]
    elif condition == "pct_both_below_40":
        hits = sub[sub["pct_above_both"] < 40]
    elif condition == "pct_both_below_25":
        hits = sub[sub["pct_above_both"] < 25]
    elif condition == "pct_ma20_above_50":
        hits = sub[sub["pct_above_ma20"] > 50]
    elif condition == "hl_ratio_above_2":
        hits = sub[sub["hl_ratio"] > 2.0]
    else:
        return None
    if hits.empty:
        return None
    return hits.index[0].strftime("%Y-%m-%d")


def _nearest_breadth_row(breadth: pd.DataFrame, date_str: str) -> pd.Series:
    ts = pd.Timestamp(date_str)
    idx = breadth.index.get_indexer([ts], method="nearest")[0]
    return breadth.iloc[idx]


def analyze_episode_breadth(breadth: pd.DataFrame, ep: Episode) -> dict:
    peak = _nearest_breadth_row(breadth, ep.peak_week)
    trough = _nearest_breadth_row(breadth, ep.trough_week)
    win_start = (pd.Timestamp(ep.peak_week) - pd.Timedelta(weeks=8)).strftime("%Y-%m-%d")
    recovery_end = (pd.Timestamp(ep.trough_week) + pd.Timedelta(weeks=16)).strftime("%Y-%m-%d")

    return {
        "name": ep.name,
        "peak": peak,
        "trough": trough,
        "first_hl_below_1": find_first_breadth_signal(
            breadth, after=win_start, before=ep.trough_week, condition="hl_ratio_below_1"
        ),
        "first_hl_below_0_5": find_first_breadth_signal(
            breadth, after=win_start, before=ep.trough_week, condition="hl_ratio_below_0_5"
        ),
        "first_ma20_below_50": find_first_breadth_signal(
            breadth, after=win_start, before=ep.trough_week, condition="pct_ma20_below_50"
        ),
        "first_ma20_below_30": find_first_breadth_signal(
            breadth, after=win_start, before=ep.trough_week, condition="pct_ma20_below_30"
        ),
        "first_both_below_40": find_first_breadth_signal(
            breadth, after=win_start, before=ep.trough_week, condition="pct_both_below_40"
        ),
        "first_both_below_25": find_first_breadth_signal(
            breadth, after=win_start, before=ep.trough_week, condition="pct_both_below_25"
        ),
        "recovery_ma20_above_50": find_first_breadth_signal(
            breadth, after=ep.trough_week, before=recovery_end, condition="pct_ma20_above_50"
        ),
        "recovery_hl_above_2": find_first_breadth_signal(
            breadth, after=ep.trough_week, before=recovery_end, condition="hl_ratio_above_2"
        ),
    }


def weeks_after_peak(peak: str, signal: str | None) -> str:
    if not signal:
        return "n/a"
    return f"{(pd.Timestamp(signal) - pd.Timestamp(peak)).days // 7}w"


def weeks_after_trough(trough: str, signal: str | None) -> str:
    if not signal:
        return "n/a"
    return f"{(pd.Timestamp(signal) - pd.Timestamp(trough)).days // 7}w"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    parser.add_argument("--period", choices=("2018-2020", "2007-2009"), default="2018-2020")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    episodes = EPISODES_2007_2009 if args.period == "2007-2009" else EPISODES_2018_2020

    print("Fetching S&P 500 tickers...")
    symbols = fetch_sp500_tickers()
    print(f"Downloading weekly data for {len(symbols)} symbols ({args.start} to {args.end})...")
    weekly = download_weekly_closes(symbols, start=args.start, end=args.end)
    breadth = compute_breadth(weekly)
    breadth = breadth.loc[pd.Timestamp(args.start) : pd.Timestamp(args.end)]

    lines: list[str] = []
    def emit(s: str = "") -> None:
        print(s)
        lines.append(s)

    emit("S&P 500 WEEKLY BREADTH (computed from yfinance, current constituents)")
    emit(f"Period: {args.start} to {args.end}")
    emit(f"52w high/low: within {NEAR_PCT*100:.0f}% of rolling {HIGH_LOW_WEEKS}-week extreme")
    emit(f"MA breadth: weekly close above MA10 / MA20 / both")
    emit("Note: uses today's S&P 500 list — survivorship bias on old periods.")
    emit("=" * 100)

    emit("\nWEEKLY BREADTH TABLE")
    emit("-" * 100)
    emit(
        f"{'Week':<11} {'nh':>5} {'nl':>5} {'H/L':>6} "
        f"{'>MA10':>7} {'>MA20':>7} {'>both':>7}"
    )
    emit("-" * 100)
    for week, row in breadth.iterrows():
        emit(
            f"{week.strftime('%Y-%m-%d'):<11} {int(row['near_52w_high']):>5} {int(row['near_52w_low']):>5} "
            f"{row['hl_ratio']:>6.2f} "
            f"{row['pct_above_ma10']:>6.1f}% {row['pct_above_ma20']:>6.1f}% "
            f"{row['pct_above_both']:>6.1f}%"
        )

    emit("\n" + "=" * 100)
    emit("EPISODE BREADTH ANALYSIS")
    emit("=" * 100)

    start_signals = [
        ("H/L ratio < 1.0", "first_hl_below_1"),
        ("H/L ratio < 0.5", "first_hl_below_0_5"),
        ("% above MA20 < 50", "first_ma20_below_50"),
        ("% above MA20 < 30", "first_ma20_below_30"),
        ("% above both < 40", "first_both_below_40"),
        ("% above both < 25", "first_both_below_25"),
    ]
    recovery_signals = [
        ("% above MA20 > 50", "recovery_ma20_above_50"),
        ("H/L ratio > 2.0", "recovery_hl_above_2"),
    ]

    for ep in episodes:
        a = analyze_episode_breadth(breadth, ep)
        emit(f"\n### {a['name']}")
        emit(f"  Peak ({ep.peak_week}):   {breadth_snapshot(a['peak'])}")
        emit(f"  Trough ({ep.trough_week}): {breadth_snapshot(a['trough'])}")
        emit("  START breadth signals (peak -> trough):")
        for label, key in start_signals:
            dt = a[key]
            emit(f"    {label + ':':<24} {dt or 'None':<12} ({weeks_after_peak(ep.peak_week, dt)})")
        emit("  RECOVERY breadth signals (trough -> +16w):")
        for label, key in recovery_signals:
            dt = a[key]
            emit(f"    {label + ':':<24} {dt or 'None':<12} ({weeks_after_trough(ep.trough_week, dt)})")

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
