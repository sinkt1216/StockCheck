"""Long-term multiple-top resistance and weekly breakout detection."""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

from weekly_bars import fetch_weekly_ohlc

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "sources.yaml"

DEFAULTS = {
    "lookback_years": 5,
    "swing_lookback_weeks": 3,
    "touch_tolerance_pct": 18.0,
    "min_touches": 3,
    "min_span_weeks": 26,
    "breakout_buffer_pct": 1.0,
    "breakout_freshness_weeks": 8,
    "hold_weeks": 1,
    "min_weeks_since_last_touch": 8,
    "base_below_resistance_pct": 60,
    "watch_below_pct": 5.0,
    "extended_above_pct": 25.0,
}


def load_config(config_path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    if yaml is None or not config_path.is_file():
        return {"multi_top_breakout": dict(DEFAULTS)}
    with config_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    merged = dict(DEFAULTS)
    merged.update(data.get("multi_top_breakout", {}))
    return {"multi_top_breakout": merged}


@dataclass
class ResistanceCluster:
    level: float
    touch_count: int
    touch_dates: list[str]
    span_weeks: int
    base_below_pct: float


def _find_confirmed_swing_highs(
    highs: pd.Series,
    *,
    swing_n: int,
    max_idx: int,
) -> list[tuple[int, float]]:
    """Swing highs confirmed by `swing_n` weeks on each side, only up to max_idx."""
    confirmed_limit = max_idx - swing_n
    swings: list[tuple[int, float]] = []
    if confirmed_limit < swing_n:
        return swings

    for i in range(swing_n, confirmed_limit + 1):
        window = highs.iloc[i - swing_n : i + swing_n + 1]
        h = float(highs.iloc[i])
        if h >= float(window.max()) and h > float(highs.iloc[i - 1]) and h > float(highs.iloc[i + 1]):
            swings.append((i, h))
    return swings


def _cluster_swings(
    swings: list[tuple[int, float]],
    dates: pd.DatetimeIndex,
    *,
    tolerance_pct: float,
    min_touches: int,
    min_span_weeks: int,
) -> ResistanceCluster | None:
    if len(swings) < min_touches:
        return None

    candidates: list[ResistanceCluster] = []
    sorted_swings = sorted(swings, key=lambda x: x[1], reverse=True)

    for seed_idx, seed_price in sorted_swings:
        cluster = [(seed_idx, seed_price)]
        for other_idx, other_price in sorted_swings:
            if other_idx == seed_idx:
                continue
            if abs(other_price - seed_price) / seed_price * 100.0 <= tolerance_pct:
                cluster.append((other_idx, other_price))

        if len(cluster) < min_touches:
            continue

        cluster.sort(key=lambda x: x[0])
        first_idx, last_idx = cluster[0][0], cluster[-1][0]
        span_weeks = int((dates[last_idx] - dates[first_idx]).days / 7)
        if span_weeks < min_span_weeks:
            continue

        level = max(price for _, price in cluster)
        touch_dates = [dates[i].strftime("%Y-%m-%d") for i, _ in cluster]
        candidates.append(
            ResistanceCluster(
                level=round(level, 2),
                touch_count=len(cluster),
                touch_dates=touch_dates,
                span_weeks=span_weeks,
                base_below_pct=0.0,
            )
        )

    if not candidates:
        return None

    # Prefer the highest ceiling (green line), tie-break by more touches.
    candidates.sort(key=lambda c: (c.level, c.touch_count), reverse=True)
    return candidates[0]


def _eval_at_index(
    weekly: pd.DataFrame,
    eval_idx: int,
    *,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    lookback_weeks = int(cfg["lookback_years"] * 52)
    swing_n = int(cfg["swing_lookback_weeks"])
    start_idx = max(0, eval_idx - lookback_weeks + 1)
    window = weekly.iloc[start_idx : eval_idx + 1]
    highs = window["High"].astype(float)
    closes = window["Close"].astype(float)
    dates = window.index

    rel_eval = eval_idx - start_idx
    swings = _find_confirmed_swing_highs(highs, swing_n=swing_n, max_idx=rel_eval)
    cluster = _cluster_swings(
        swings,
        dates,
        tolerance_pct=float(cfg["touch_tolerance_pct"]),
        min_touches=int(cfg["min_touches"]),
        min_span_weeks=int(cfg["min_span_weeks"]),
    )

    week_end = weekly.index[eval_idx].strftime("%Y-%m-%d")
    close = float(weekly["Close"].iloc[eval_idx])
    high = float(weekly["High"].iloc[eval_idx])

    if cluster is None:
        return {
            "week_end": week_end,
            "close": round(close, 2),
            "high": round(high, 2),
            "resistance_level": None,
            "touch_count": 0,
            "touch_dates": [],
            "span_weeks": 0,
            "base_below_pct": None,
            "weeks_since_last_touch": None,
            "breakout": False,
            "breakout_week": None,
            "weeks_since_break": None,
            "pct_above_resistance": None,
            "hold_ok": False,
            "stage": "NONE",
        }

    resistance = cluster.level
    threshold = resistance * (1.0 + float(cfg["breakout_buffer_pct"]) / 100.0)
    base_below_pct = float((closes < resistance).sum() / len(closes) * 100.0)
    cluster.base_below_pct = round(base_below_pct, 1)

    last_touch_date = pd.Timestamp(cluster.touch_dates[-1])
    weeks_since_last_touch = int((weekly.index[eval_idx] - last_touch_date).days / 7)

    first_break_week: str | None = None
    weeks_since_break: int | None = None
    hold_weeks = int(cfg["hold_weeks"])
    consecutive = 0
    for j in range(rel_eval + 1):
        if float(closes.iloc[j]) > threshold:
            consecutive += 1
            if consecutive >= hold_weeks and first_break_week is None:
                first_break_week = dates[j].strftime("%Y-%m-%d")
        else:
            consecutive = 0

    if first_break_week:
        break_date = pd.Timestamp(first_break_week)
        weeks_since_break = int((weekly.index[eval_idx] - break_date).days / 7)

    breakout = close > threshold
    pct_above = (close / resistance - 1.0) * 100.0 if resistance else None

    hold_ok = breakout
    if hold_weeks > 1 and eval_idx >= hold_weeks - 1:
        recent = weekly["Close"].iloc[eval_idx - hold_weeks + 1 : eval_idx + 1].astype(float)
        hold_ok = bool((recent > threshold).all())

    freshness = int(cfg["breakout_freshness_weeks"])
    watch_below = float(cfg["watch_below_pct"])
    extended_above = float(cfg["extended_above_pct"])

    stage = "NONE"
    if cluster is not None:
        pct_below = (resistance - close) / resistance * 100.0 if resistance else 0.0
        if not breakout and 0 <= pct_below <= watch_below:
            if weeks_since_last_touch is not None and weeks_since_last_touch >= int(cfg["min_weeks_since_last_touch"]):
                stage = "WATCH"
        elif breakout and weeks_since_break is not None and weeks_since_break <= freshness:
            stage = "BREAK"
        elif breakout and weeks_since_break is not None and 4 <= weeks_since_break <= 12:
            stage = "CONFIRMED"
        elif breakout and (
            (weeks_since_break is not None and weeks_since_break > 12)
            or (pct_above is not None and pct_above > extended_above)
        ):
            stage = "EXTENDED"
        elif breakout:
            stage = "BREAK"

    return {
        "week_end": week_end,
        "close": round(close, 2),
        "high": round(high, 2),
        "resistance_level": resistance,
        "touch_count": cluster.touch_count,
        "touch_dates": cluster.touch_dates,
        "span_weeks": cluster.span_weeks,
        "base_below_pct": cluster.base_below_pct,
        "weeks_since_last_touch": weeks_since_last_touch,
        "breakout": breakout,
        "breakout_week": first_break_week,
        "weeks_since_break": weeks_since_break,
        "pct_above_resistance": round(pct_above, 2) if pct_above is not None else None,
        "hold_ok": hold_ok,
        "stage": stage,
    }


def compute_multi_top_series(
    weekly: pd.DataFrame,
    *,
    config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    cfg = (config or load_config())["multi_top_breakout"]
    rows = []
    start_at = max(int(cfg["swing_lookback_weeks"]) + 1, int(cfg["min_span_weeks"]))
    for i in range(start_at, len(weekly)):
        rows.append(_eval_at_index(weekly, i, cfg=cfg))
    return pd.DataFrame(rows)


def analyze_symbol(symbol: str, *, config_path: Path = DEFAULT_CONFIG) -> pd.DataFrame:
    config = load_config(config_path)
    weekly = fetch_weekly_ohlc(symbol, period="max")
    return compute_multi_top_series(weekly, config=config)


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python src/multi_top_breakout.py SYMBOL [--from YYYY-MM-DD] [--to YYYY-MM-DD]", file=sys.stderr)
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

    print(f"Multi-top breakout — {symbol}")
    print("=" * 70)
    resistance = df["resistance_level"].dropna().iloc[-1] if df["resistance_level"].notna().any() else None
    if resistance:
        sample = df[df["resistance_level"].notna()].iloc[-1]
        print(
            f"Resistance ~${sample['resistance_level']}  "
            f"({sample['touch_count']} touches, span {sample['span_weeks']}w)"
        )
        print(f"Touch weeks: {', '.join(sample['touch_dates'][:6])}{'...' if len(sample['touch_dates']) > 6 else ''}")
        print()

    for _, row in df.iterrows():
        res = f"${row['resistance_level']}" if row["resistance_level"] else "n/a"
        brk = "BREAK" if row["breakout"] else "below"
        print(
            f"{row['week_end']}  ${row['close']:>8}  res={res:>8}  "
            f"{brk:>5}  stage={row['stage']:<10}  "
            f"wk_since_brk={str(row['weeks_since_break']):>3}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
