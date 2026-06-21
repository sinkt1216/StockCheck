"""Combined backtest: weekly MA slope + multi-top breakout."""

from __future__ import annotations

import math
import sys
from typing import Any

import pandas as pd

from multi_top_breakout import compute_multi_top_series, load_config as load_mt_config
from weekly_bars import fetch_weekly_ohlc
from weekly_trend_state import compute_weekly_trend_series, load_config as load_wt_config

SLOPE_TURN = 0.15


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


def _structure_event(row: pd.Series) -> str:
    parts: list[str] = []
    if row.get("mt_stage") == "WATCH":
        parts.append("WATCH")
    if row.get("is_first_break"):
        parts.append("FIRST_BREAK")
    elif row.get("breakout") and row.get("mt_stage") in ("BREAK", "CONFIRMED", "EXTENDED"):
        parts.append("above_res")
    elif pd.notna(row.get("mt_resistance_level")) and not row.get("breakout"):
        parts.append("below_res")
    return "+".join(parts) if parts else ""


def _slope_event(row: pd.Series) -> str:
    parts: list[str] = []
    if row.get("wt_early_turn"):
        parts.append("early_turn")
    if row.get("wt_confirmed_turn"):
        parts.append("confirmed_turn")
    label = row.get("slope_change")
    if label and label not in ("flat", "") and not row.get("wt_early_turn"):
        parts.append(label)
    return "+".join(parts) if parts else ""


def _combined_signal(row: pd.Series) -> str | None:
    """Assign combined_signal — priority: watch → break → confirmed → extended."""
    stage = row.get("mt_stage")
    slope = row.get("wt_slope_4w_pct")
    delta = row.get("wt_slope_4w_delta")
    if stage == "WATCH" and slope is not None and slope > 0 and delta is not None and delta > 0:
        return "watch"
    if row.get("breakout") and (
        row.get("wt_early_turn") or (slope is not None and slope > SLOPE_TURN)
    ):
        if row.get("wt_close") and row.get("wt_ma10") and row["wt_close"] > row["wt_ma10"]:
            return "break"
    if stage == "CONFIRMED" and row.get("wt_state") == "CONFIRMED_UP":
        return "confirmed"
    if stage in ("EXTENDED", "CONFIRMED") and row.get("wt_state") in ("MATURE_UP", "CONFIRMED_UP"):
        return "extended"
    return None


def enrich_backtest(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy().reset_index(drop=True)
    out["wt_slope_4w_delta"] = out["wt_slope_4w_pct"].diff()
    out["prev_wt_state"] = out["wt_state"].shift(1)

    out["slope_change"] = [
        _slope_change_label(
            row["wt_slope_4w_delta"],
            bool(row["wt_early_turn"]),
            row["prev_wt_state"],
            row["wt_state"],
        )
        for _, row in out.iterrows()
    ]

    out["vs_res_pct"] = out.apply(
        lambda r: (
            (r["wt_close"] / r["mt_resistance_level"] - 1.0) * 100.0
            if pd.notna(r.get("mt_resistance_level")) and r["mt_resistance_level"]
            else None
        ),
        axis=1,
    )

    out["is_first_break"] = out["week_end"] == out["mt_breakout_week"]
    out["structure_event"] = out.apply(_structure_event, axis=1)
    out["slope_event"] = out.apply(_slope_event, axis=1)
    out["combined_signal"] = out.apply(_combined_signal, axis=1)
    return out


def run_backtest(
    symbol: str,
    *,
    start: str,
    end: str | None = None,
) -> pd.DataFrame:
    mt_cfg = load_mt_config()
    wt_cfg = load_wt_config()
    weekly = fetch_weekly_ohlc(symbol, period="max")

    trend = compute_weekly_trend_series(weekly, config=wt_cfg)
    trend = trend.add_prefix("wt_")
    trend = trend.rename(columns={"wt_week_end": "week_end"})

    multi = compute_multi_top_series(weekly, config=mt_cfg)
    multi = multi.add_prefix("mt_")
    multi = multi.rename(columns={"mt_week_end": "week_end", "mt_breakout": "breakout"})

    merged = pd.merge(trend, multi, on="week_end", how="inner")
    merged = merged[merged["week_end"] >= start]
    if end:
        merged = merged[merged["week_end"] <= end]

    return enrich_backtest(merged)


def _build_lead_lag_summary(df: pd.DataFrame, *, ccy: str) -> list[str]:
    lines: list[str] = []
    breaks = df[df["is_first_break"] == True]  # noqa: E712
    if breaks.empty:
        return ["  (no structural breaks in range)"]

    for _, br in breaks.iterrows():
        break_week = br["week_end"]
        break_idx = df.index[df["week_end"] == break_week][0]
        prior = df.iloc[:break_idx]
        early = prior[prior["wt_early_turn"] == True]  # noqa: E712
        slope_up = prior[
            (prior["wt_slope_4w_pct"] > SLOPE_TURN)
            & (prior["wt_close"] < prior["mt_resistance_level"])
        ]
        res = br["mt_resistance_level"]
        lines.append(
            f"  Break {break_week} @ {ccy}{br['wt_close']:.2f} "
            f"(res {ccy}{res:.2f}, vs res {_fmt_pct(br['vs_res_pct'], signed=True).strip()})"
        )
        if not early.empty:
            e = early.iloc[-1]
            e_idx = df.index[df["week_end"] == e["week_end"]][0]
            lead_weeks = break_idx - e_idx
            lines.append(
                f"    Slope led: early_turn {e['week_end']} ({lead_weeks}w before break), "
                f"slp4w {e['wt_slope_4w_pct']:+.2f}% -> {br['wt_slope_4w_pct']:+.2f}% at break"
            )
        elif not slope_up.empty:
            s = slope_up.iloc[0]
            s_idx = df.index[df["week_end"] == s["week_end"]][0]
            lead_weeks = break_idx - s_idx
            lines.append(
                f"    Slope already up: slp4w>{SLOPE_TURN}% since {s['week_end']} "
                f"({lead_weeks}w before break), no fresh early_turn"
            )
        else:
            lines.append("    Slope: no early_turn before this break")
            if pd.notna(br["wt_slope_4w_pct"]):
                lines.append(
                    f"    At break: slp4w={br['wt_slope_4w_pct']:+.2f}%, state={br['wt_state']}"
                )
        if pd.notna(br.get("combined_signal")):
            lines.append(f"    Combined signal: {br['combined_signal']} (same week as break)")
        lines.append("")
    return lines


def summarize_backtest(symbol: str, df: pd.DataFrame) -> str:
    ccy = _currency_prefix(symbol)
    lines = [
        f"Combined backtest — {symbol}",
        "=" * 118,
        "",
        "Columns: vsRes = % above/below resistance | slp1w/slp4w = weekly MA10 slope | d4w = week-over-week",
        "         change in slp4w | Slope_ev / Struct_ev = regime or level events | Combined = both layers",
        "",
    ]

    res_rows = df[df["mt_resistance_level"].notna()]
    if not res_rows.empty:
        last = res_rows.iloc[-1]
        touches = last["mt_touch_dates"]
        if isinstance(touches, str):
            touches = eval(touches)
        lines.extend(
            [
                f"Current resistance: {ccy}{last['mt_resistance_level']:.2f}  "
                f"({int(last['mt_touch_count'])} touches, {int(last['mt_span_weeks'])}w span)",
                f"Touch weeks: {', '.join(touches)}",
                "",
            ]
        )

    header = (
        f"{'Week':<11} {'Close':>8} {'vsRes':>7} {'Res':>8} {'MT':<9} {'Trend':<12} "
        f"{'slp1w':>7} {'slp4w':>7} {'d4w':>7} {'Stack':>5} "
        f"{'Slope_ev':<16} {'Struct_ev':<14} {'Combined':<10}"
    )
    lines.extend([header, "-" * 118])

    for _, row in df.iterrows():
        res = f"{ccy}{row['mt_resistance_level']:.2f}" if pd.notna(row.get("mt_resistance_level")) else "n/a"
        combined = str(row["combined_signal"]) if pd.notna(row["combined_signal"]) else ""
        stack = "Y" if row.get("wt_ma_stack") else "N"
        lines.append(
            f"{row['week_end']:<11} "
            f"{ccy}{row['wt_close']:>7.2f} "
            f"{_fmt_pct(row.get('vs_res_pct'), 7)} "
            f"{res:>8} "
            f"{row['mt_stage']:<9} "
            f"{row['wt_state']:<12} "
            f"{_fmt_pct(row.get('wt_slope_1w_pct'), 7)} "
            f"{_fmt_pct(row.get('wt_slope_4w_pct'), 7)} "
            f"{_fmt_pct(row.get('wt_slope_4w_delta'), 7)} "
            f"{stack:>5} "
            f"{row['slope_event']:<16} "
            f"{row['structure_event']:<14} "
            f"{combined:<10}"
        )

    lines.extend(["", "Lead / lag (slope early_turn vs structural FIRST_BREAK):", ""])
    lines.extend(_build_lead_lag_summary(df, ccy=ccy))

    lines.extend(["", "Notes:", ""])
    lines.append(
        "  - Slope often LEADS structural break when early_turn fires while price is still below "
        "resistance (watchlist phase)."
    )
    lines.append(
        "  - Sometimes they coincide (break week is also the first week slope crosses +0.15%/wk)."
    )
    lines.append(
        "  - Slope can lead by several weeks (typical 1-8w) or be already positive well before "
        "the ceiling breaks."
    )

    event_rows = df[(df["slope_event"] != "") | (df["structure_event"] != "") | df["combined_signal"].notna()]
    if not event_rows.empty:
        lines.extend(["", "Event-only view:", "-" * 80])
        for _, row in event_rows.iterrows():
            combined = str(row["combined_signal"]) if pd.notna(row["combined_signal"]) else ""
            lines.append(
                f"  {row['week_end']}  slp4w={_fmt_pct(row.get('wt_slope_4w_pct'), 6).strip()} "
                f"d4w={_fmt_pct(row.get('wt_slope_4w_delta'), 6).strip()}  "
                f"{row['slope_event'] or '-':<16}  {row['structure_event'] or '-':<14}  "
                f"{combined}"
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
