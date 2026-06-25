"""Weekly backtest: MA slope + volume buy rule."""

from __future__ import annotations

import math
import sys
from typing import Any

import pandas as pd

from weekly_bars import compute_weekly_volume_series, fetch_weekly_ohlc, week_start_monday
from weekly_scan import _assign_buy_signal, load_liquidity_config, load_scan_config
from weekly_trend_state import compute_weekly_trend_series, load_config as load_wt_config


def _currency_prefix(symbol: str) -> str:
    return "HK$" if symbol.upper().endswith(".HK") else "$"


def _fmt_pct(value: Any, width: int = 6, signed: bool = True) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return f"{'':>{width}}"
    if signed:
        return f"{float(value):+{width - 1}.2f}%"
    return f"{float(value):{width - 1}.2f}%"


def _slope_change_label(delta: float | None, early_turn: bool, prev_state: str | None, state: str) -> str:
    if early_turn:
        return "TURN_UP"
    if delta is None or (isinstance(delta, float) and math.isnan(delta)):
        return ""
    if prev_state and prev_state != state:
        return f"{prev_state}->{state}"
    if delta >= 0.20:
        return "accel_up"
    if delta <= -0.20:
        return "accel_down"
    if abs(delta) < 0.05:
        return "flat"
    return "drift_up" if delta > 0 else "drift_down"


def _slope_event(row: pd.Series) -> str:
    parts: list[str] = []
    if row.get("wt_early_turn"):
        parts.append("early_turn")
    if row.get("wt_confirmed_turn"):
        parts.append("confirmed_turn")
    label = row.get("slope_change")
    if label and label not in ("flat", "") and not row.get("wt_early_turn"):
        parts.append(label)
    if row.get("volume_spike"):
        parts.append("VOL_SPIKE")
    if row.get("wt_golden_cross"):
        parts.append("GC")
    return "+".join(parts) if parts else ""


def _add_golden_cross_recent(df: pd.DataFrame, lookback_weeks: int) -> pd.Series:
    flags: list[bool] = []
    cross_col = df["wt_golden_cross"].fillna(False).astype(bool).tolist()
    for i in range(len(cross_col)):
        start = max(0, i - lookback_weeks + 1)
        flags.append(any(cross_col[start : i + 1]))
    return pd.Series(flags, index=df.index)


def _row_to_buy_dict(row: pd.Series) -> dict[str, Any]:
    return {
        "price_above_ma10_ma20": bool(row.get("wt_price_above_ma10_ma20")),
        "slope_1w_pct": row.get("wt_slope_1w_pct"),
        "slope_4w_pct": row.get("wt_slope_4w_pct"),
        "slope_1w_delta": row.get("wt_slope_1w_delta"),
        "slope_4w_delta": row.get("wt_slope_4w_delta"),
        "volume_spike": bool(row.get("volume_spike")),
        "avg_volume_50d": row.get("avg_volume_50d"),
    }


def enrich_backtest(df: pd.DataFrame, *, min_avg_volume_50d: int, golden_cross_lookback_weeks: int) -> pd.DataFrame:
    out = df.copy().reset_index(drop=True)
    out["wt_slope_4w_delta"] = out["wt_slope_4w_pct"].diff().round(2)
    out["wt_slope_1w_delta"] = out["wt_slope_1w_pct"].diff().round(2)
    out["prev_wt_state"] = out["wt_state"].shift(1)
    out["week_start"] = out["week_end"].map(week_start_monday)

    out["slope_change"] = [
        _slope_change_label(
            row["wt_slope_4w_delta"],
            bool(row["wt_early_turn"]),
            row["prev_wt_state"],
            row["wt_state"],
        )
        for _, row in out.iterrows()
    ]
    out["slope_event"] = out.apply(_slope_event, axis=1)
    out["golden_cross_recent"] = _add_golden_cross_recent(out, golden_cross_lookback_weeks)
    out["combined_signal"] = [
        _assign_buy_signal(_row_to_buy_dict(row), min_avg_volume_50d=min_avg_volume_50d)[
            "combined_signal"
        ]
        for _, row in out.iterrows()
    ]
    return out


def run_backtest(
    symbol: str,
    *,
    start: str,
    end: str | None = None,
) -> pd.DataFrame:
    wt_cfg = load_wt_config()
    gc_lookback = int(load_scan_config()["golden_cross_lookback_weeks"])
    min_avg_volume_50d = int(load_liquidity_config()["min_avg_volume_50d"])
    weekly = fetch_weekly_ohlc(symbol, period="max")

    trend = compute_weekly_trend_series(weekly, config=wt_cfg)
    trend = trend.add_prefix("wt_")
    trend = trend.rename(columns={"wt_week_end": "week_end"})

    volume = compute_weekly_volume_series(weekly)

    merged = pd.merge(trend, volume, on="week_end", how="left")
    merged["avg_volume_50d"] = None  # backtest skips daily liquidity fetch
    merged = merged[merged["week_end"] >= start]
    if end:
        merged = merged[merged["week_end"] <= end]

    return enrich_backtest(merged, min_avg_volume_50d=0, golden_cross_lookback_weeks=gc_lookback)


def _build_buy_weeks_summary(df: pd.DataFrame, *, ccy: str) -> list[str]:
    buys = df[df["combined_signal"] == "buy"]
    if buys.empty:
        return ["  (no buy signals in range — volume_spike required; avg_volume_50d not checked in backtest)"]
    lines: list[str] = []
    for _, row in buys.iterrows():
        lines.append(
            f"  {row['week_start']}  close {ccy}{row['wt_close']:.2f}  "
            f"slp1w={_fmt_pct(row.get('wt_slope_1w_pct'), 6).strip()}  "
            f"slp4w={_fmt_pct(row.get('wt_slope_4w_pct'), 6).strip()}  "
            f"d4w={_fmt_pct(row.get('wt_slope_4w_delta'), 6).strip()}  "
            f"{'GC' if row.get('wt_golden_cross') else ''}  "
            f"{'VOL_SPIKE' if row.get('volume_spike') else ''}"
        )
    return lines


def summarize_backtest(symbol: str, df: pd.DataFrame) -> str:
    ccy = _currency_prefix(symbol)
    lines = [
        f"Weekly backtest — {symbol}",
        "=" * 100,
        "",
        "Columns: slp1w/slp4w = weekly MA10 slope | d1w/d4w = week-over-week change",
        "         MA = price_above_ma10_ma20 | GC = golden cross reference (not required for buy)",
        "         VolSpk = weekly volume > 20w MA",
        "         Signal = buy when MA + slopes + acceleration + volume_spike (liquidity skipped here)",
        "Week column = Monday (week open). Bars use W-FRI close; --from/--to filter on Friday week-end.",
        "",
    ]

    header = (
        f"{'Week Mon':<11} {'Close':>8} {'Trend':<12} "
        f"{'slp1w':>7} {'slp4w':>7} {'d1w':>7} {'d4w':>7} {'MA':>3} {'GC':>3} {'VolSpk':>6} "
        f"{'Slope_ev':<20} {'Signal':<6}"
    )
    lines.extend([header, "-" * 100])

    for _, row in df.iterrows():
        signal = str(row["combined_signal"]) if pd.notna(row["combined_signal"]) else ""
        ma = "Y" if row.get("wt_price_above_ma10_ma20") else "N"
        gc = "Y" if row.get("wt_golden_cross") else "N"
        vol = "Y" if row.get("volume_spike") else "N"
        lines.append(
            f"{row['week_start']:<11} "
            f"{ccy}{row['wt_close']:>7.2f} "
            f"{row['wt_state']:<12} "
            f"{_fmt_pct(row.get('wt_slope_1w_pct'), 7)} "
            f"{_fmt_pct(row.get('wt_slope_4w_pct'), 7)} "
            f"{_fmt_pct(row.get('wt_slope_1w_delta'), 7)} "
            f"{_fmt_pct(row.get('wt_slope_4w_delta'), 7)} "
            f"{ma:>3} "
            f"{gc:>3} "
            f"{vol:>6} "
            f"{row['slope_event']:<20} "
            f"{signal:<6}"
        )

    lines.extend(["", "Buy signal weeks:", ""])
    lines.extend(_build_buy_weeks_summary(df, ccy=ccy))

    event_rows = df[(df["slope_event"] != "") | df["combined_signal"].notna()]
    if not event_rows.empty:
        lines.extend(["", "Event-only view:", "-" * 80])
        for _, row in event_rows.iterrows():
            signal = str(row["combined_signal"]) if pd.notna(row["combined_signal"]) else ""
            lines.append(
                f"  {row['week_start']}  slp4w={_fmt_pct(row.get('wt_slope_4w_pct'), 6).strip()} "
                f"d4w={_fmt_pct(row.get('wt_slope_4w_delta'), 6).strip()}  "
                f"{row['slope_event'] or '-':<20}  {signal}"
            )

    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "Usage: python src/weekly_backtest.py SYMBOL --from YYYY-MM-DD [--to YYYY-MM-DD]",
            file=sys.stderr,
        )
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

    if not start:
        print("ERROR: --from is required", file=sys.stderr)
        return 1

    try:
        df = run_backtest(symbol, start=start, end=end)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(summarize_backtest(symbol, df))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
