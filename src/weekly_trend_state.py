"""Weekly trend state machine via 10-week MA slope (yfinance)."""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

from weekly_bars import fetch_weekly_ohlc, week_start_monday

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "sources.yaml"

DEFAULTS = {
    "slope_turn": 0.15,
    "slope_mature": 1.0,
    "regression_weeks": 4,
    "ma_short": 10,
    "ma_long": 20,
    "ma_medium": 50,
}


def load_config(config_path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    if yaml is None or not config_path.is_file():
        return {"weekly_trend": dict(DEFAULTS)}
    with config_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    merged = dict(DEFAULTS)
    merged.update(data.get("weekly_trend", {}))
    return {"weekly_trend": merged}


def _slope_pct_per_week(series: pd.Series, window: int, idx: int) -> float:
    if idx < window - 1:
        return float("nan")
    y = series.iloc[idx - window + 1 : idx + 1].astype(float).values
    if len(y) < window or np.any(np.isnan(y)) or y[-1] == 0:
        return float("nan")
    x = np.arange(window, dtype=float)
    slope = float(np.polyfit(x, y, 1)[0])
    return slope / y[-1] * 100.0


def _assign_state(
    slope_4w: float,
    ma_stack: bool,
    breakout_12w: bool,
    *,
    slope_turn: float,
    slope_mature: float,
) -> str:
    if math.isnan(slope_4w):
        return "INSUFFICIENT"
    if slope_4w > slope_mature and ma_stack:
        return "MATURE_UP"
    if slope_4w > slope_turn and ma_stack and breakout_12w:
        return "CONFIRMED_UP"
    if slope_4w > slope_turn:
        return "EARLY_UP"
    if slope_4w < -slope_turn:
        return "DOWNTREND"
    return "BASE"


def compute_weekly_trend_series(
    weekly: pd.DataFrame,
    *,
    config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    cfg = (config or load_config())["weekly_trend"]
    slope_turn = float(cfg["slope_turn"])
    slope_mature = float(cfg["slope_mature"])
    reg_weeks = int(cfg["regression_weeks"])
    ma_short = int(cfg["ma_short"])
    ma_long = int(cfg["ma_long"])
    ma_medium = int(cfg["ma_medium"])

    close = weekly["Close"].astype(float)
    ma10 = close.rolling(window=ma_short, min_periods=ma_short).mean()
    ma20 = close.rolling(window=ma_long, min_periods=ma_long).mean()
    ma50 = close.rolling(window=ma_medium, min_periods=ma_medium).mean()

    prior_low_8 = close.rolling(window=8, min_periods=8).min().shift(1)
    prior_high_12 = close.rolling(window=12, min_periods=12).max().shift(1)

    rows: list[dict[str, Any]] = []
    prev_slope_4w = float("nan")

    for i in range(len(weekly)):
        week_end = weekly.index[i]
        c = float(close.iloc[i])
        m10 = float(ma10.iloc[i]) if not math.isnan(ma10.iloc[i]) else float("nan")
        m20 = float(ma20.iloc[i]) if not math.isnan(ma20.iloc[i]) else float("nan")
        m50 = float(ma50.iloc[i]) if not math.isnan(ma50.iloc[i]) else float("nan")

        slope_4w = _slope_pct_per_week(ma10, reg_weeks, i)
        if i > 0 and not math.isnan(ma10.iloc[i]) and not math.isnan(ma10.iloc[i - 1]) and ma10.iloc[i - 1] != 0:
            slope_1w = (ma10.iloc[i] - ma10.iloc[i - 1]) / ma10.iloc[i - 1] * 100.0
        else:
            slope_1w = float("nan")

        pl8 = prior_low_8.iloc[i]
        ph12 = prior_high_12.iloc[i]
        higher_low = not math.isnan(pl8) and c > float(pl8)
        breakout_12w = not math.isnan(ph12) and c > float(ph12)
        ma_stack = not any(math.isnan(v) for v in (c, m10, m20)) and c > m10 > m20
        ma10_above_ma20 = not any(math.isnan(v) for v in (m10, m20)) and m10 > m20
        ma10_above_ma50 = not any(math.isnan(v) for v in (m10, m50)) and m10 > m50

        state = _assign_state(
            slope_4w,
            ma_stack,
            breakout_12w,
            slope_turn=slope_turn,
            slope_mature=slope_mature,
        )

        early_turn = (
            not math.isnan(slope_4w)
            and not math.isnan(prev_slope_4w)
            and prev_slope_4w <= slope_turn
            and slope_4w > slope_turn
        )
        confirmed_turn = early_turn and ma_stack and higher_low

        rows.append(
            {
                "week_end": week_end.strftime("%Y-%m-%d"),
                "close": round(c, 2),
                "ma10": round(m10, 2) if not math.isnan(m10) else None,
                "ma20": round(m20, 2) if not math.isnan(m20) else None,
                "ma50": round(m50, 2) if not math.isnan(m50) else None,
                "slope_1w_pct": round(slope_1w, 2) if not math.isnan(slope_1w) else None,
                "slope_4w_pct": round(slope_4w, 2) if not math.isnan(slope_4w) else None,
                "higher_low": higher_low,
                "price_above_ma10_ma20": ma_stack,
                "ma10_above_ma20": ma10_above_ma20,
                "ma10_above_ma50": ma10_above_ma50,
                "breakout_12w": breakout_12w,
                "early_turn": early_turn,
                "confirmed_turn": confirmed_turn,
                "state": state,
            }
        )
        prev_slope_4w = slope_4w

    return pd.DataFrame(rows)


def analyze_symbol(symbol: str, *, config_path: Path = DEFAULT_CONFIG) -> pd.DataFrame:
    config = load_config(config_path)
    weekly = fetch_weekly_ohlc(symbol)
    return compute_weekly_trend_series(weekly, config=config)


def summarize_row(row: pd.Series) -> str:
    return (
        f"{row['week_end']}  close={row['close']}  "
        f"slope_4w={row['slope_4w_pct']}%  state={row['state']}"
        f"{'  early_turn' if row['early_turn'] else ''}"
        f"{'  confirmed_turn' if row['confirmed_turn'] else ''}"
    )


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python src/weekly_trend_state.py SYMBOL [--from YYYY-MM-DD] [--to YYYY-MM-DD]", file=sys.stderr)
        return 1

    symbol = sys.argv[1].upper()
    start = end = None
    argv = sys.argv[2:]
    i = 0
    while i < len(argv):
        if argv[i] == "--from" and i + 1 < len(argv):
            start = argv[i + 1]
            i += 2
        elif argv[i] == "--to" and i + 1 < len(argv):
            end = argv[i + 1]
            i += 2
        else:
            i += 1

    try:
        df = analyze_symbol(symbol)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if start:
        df = df[df["week_end"] >= start]
    if end:
        df = df[df["week_end"] <= end]

    print(f"Weekly trend state — {symbol}")
    print("=" * 60)
    for _, row in df.iterrows():
        flags = []
        if row["early_turn"]:
            flags.append("early_turn")
        if row["confirmed_turn"]:
            flags.append("confirmed_turn")
        flag_str = f"  [{', '.join(flags)}]" if flags else ""
        print(
            f"{week_start_monday(row['week_end'])}  ${row['close']:>8}  "
            f"slope_4w={str(row['slope_4w_pct']):>6}%  "
            f"ma={'Y' if row['price_above_ma10_ma20'] else 'N'}  "
            f"10>20={'Y' if row['ma10_above_ma20'] else 'N'}  "
            f"10>50={'Y' if row['ma10_above_ma50'] else 'N'}  "
            f"{row['state']}{flag_str}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
