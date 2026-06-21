"""Weekly universe scan: MA slope + multi-top breakout (latest week)."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from multi_top_breakout import _eval_at_index, load_config as load_mt_config
from weekly_bars import fetch_weekly_ohlc
from weekly_trend_state import compute_weekly_trend_series, load_config as load_wt_config

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_UNIVERSE = ROOT / "data" / "universe" / "nyse.json"
DEFAULT_SCAN_DIR = ROOT / "data" / "scans"

SLOPE_TURN = 0.15


def load_universe(path: Path = DEFAULT_UNIVERSE) -> list[str]:
    if not path.is_file():
        raise FileNotFoundError(f"Universe file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return [entry["symbol"].upper() for entry in data.get("symbols", [])]


def _combined_signal(trend: dict[str, Any], mt: dict[str, Any]) -> str | None:
    stage = mt.get("stage")
    slope = trend.get("slope_4w_pct")
    breakout = mt.get("breakout")
    close = trend.get("close")
    ma10 = trend.get("ma10")

    if stage == "WATCH":
        return "watch"
    if breakout and (trend.get("early_turn") or (slope is not None and slope > SLOPE_TURN)):
        if close is not None and ma10 is not None and close > ma10:
            return "break"
    if stage == "CONFIRMED" and trend.get("state") == "CONFIRMED_UP":
        return "confirmed"
    if stage in ("EXTENDED", "CONFIRMED") and trend.get("state") in ("MATURE_UP", "CONFIRMED_UP"):
        return "extended"
    return None


def scan_symbol(symbol: str) -> dict[str, Any] | None:
    wt_cfg = load_wt_config()
    mt_cfg = load_mt_config()["multi_top_breakout"]

    try:
        weekly = fetch_weekly_ohlc(symbol, period="max")
    except RuntimeError:
        return None

    if len(weekly) < 30:
        return None

    trend_df = compute_weekly_trend_series(weekly, config=wt_cfg)
    trend = trend_df.iloc[-1].to_dict()
    prev_trend = trend_df.iloc[-2].to_dict() if len(trend_df) >= 2 else {}

    mt = _eval_at_index(weekly, len(weekly) - 1, cfg=mt_cfg)
    combined = _combined_signal(trend, mt)

    slope_4w = trend.get("slope_4w_pct")
    prev_slope_4w = prev_trend.get("slope_4w_pct")
    slope_delta = None
    if slope_4w is not None and prev_slope_4w is not None:
        slope_delta = round(slope_4w - prev_slope_4w, 2)

    is_first_break = mt.get("breakout_week") == mt.get("week_end")

    return {
        "symbol": symbol.upper(),
        "week_end": trend.get("week_end"),
        "close": trend.get("close"),
        "ma10": trend.get("ma10"),
        "ma20": trend.get("ma20"),
        "trend_state": trend.get("state"),
        "slope_1w_pct": trend.get("slope_1w_pct"),
        "slope_4w_pct": slope_4w,
        "slope_4w_delta": slope_delta,
        "early_turn": bool(trend.get("early_turn")),
        "confirmed_turn": bool(trend.get("confirmed_turn")),
        "ma_stack": bool(trend.get("ma_stack")),
        "resistance_level": mt.get("resistance_level"),
        "touch_count": mt.get("touch_count"),
        "mt_stage": mt.get("stage"),
        "breakout": bool(mt.get("breakout")),
        "first_break": is_first_break,
        "combined_signal": combined,
    }


def _ma_aligned(row: dict[str, Any]) -> bool:
    close = row.get("close")
    ma10 = row.get("ma10")
    ma20 = row.get("ma20")
    if close is None or ma10 is None or ma20 is None:
        return False
    return close > ma10 and ma10 > ma20


def _is_hit(row: dict[str, Any]) -> bool:
    if not _ma_aligned(row):
        return False
    return bool(
        row.get("combined_signal")
        or row.get("early_turn")
        or row.get("first_break")
        or row.get("mt_stage") == "WATCH"
    )


def run_scan(symbols: list[str], *, progress: bool = True) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    total = len(symbols)
    for i, symbol in enumerate(symbols, start=1):
        if progress and (i == 1 or i % 25 == 0 or i == total):
            print(f"Scanning {i}/{total}: {symbol}...", file=sys.stderr)

        try:
            row = scan_symbol(symbol)
        except Exception as exc:  # noqa: BLE001 — collect per-symbol failures
            errors.append({"symbol": symbol, "error": str(exc)})
            continue

        if row is None:
            errors.append({"symbol": symbol, "error": "insufficient_data"})
            continue
        results.append(row)

    hits = [r for r in results if _is_hit(r)]
    return {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "universe_count": total,
        "scanned": len(results),
        "errors": len(errors),
        "hits": len(hits),
        "results": results,
        "hit_rows": hits,
        "error_rows": errors,
    }


def summarize_scan(payload: dict[str, Any]) -> str:
    lines = [
        f"Weekly scan — {payload['scanned']}/{payload['universe_count']} symbols",
        f"Hits: {payload['hits']}  Errors: {payload['errors']}",
        f"Week ending: {payload['hit_rows'][0]['week_end'] if payload['hit_rows'] else 'n/a'}",
        "",
        f"{'Symbol':<8} {'Close':>8} {'Trend':<12} {'slp4w':>7} {'MT':<9} {'Flags'}",
        "-" * 72,
    ]

    for row in sorted(payload["hit_rows"], key=lambda r: (r.get("combined_signal") or "", r["symbol"])):
        flags: list[str] = []
        if row.get("early_turn"):
            flags.append("early_turn")
        if row.get("first_break"):
            flags.append("FIRST_BREAK")
        if row.get("mt_stage") == "WATCH":
            flags.append("WATCH")
        if row.get("combined_signal"):
            flags.append(str(row["combined_signal"]).upper())
        slope = row.get("slope_4w_pct")
        slope_str = f"{slope:+.2f}%" if slope is not None else "n/a"
        lines.append(
            f"{row['symbol']:<8} ${row.get('close', 0):>7.2f} "
            f"{row.get('trend_state', ''):<12} {slope_str:>7} "
            f"{row.get('mt_stage', 'NONE'):<9} {', '.join(flags)}"
        )
    return "\n".join(lines)


def main() -> int:
    universe_path = DEFAULT_UNIVERSE
    output_dir = DEFAULT_SCAN_DIR
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        if argv[i] == "--universe" and i + 1 < len(argv):
            universe_path = Path(argv[i + 1])
            i += 2
        elif argv[i] == "--output-dir" and i + 1 < len(argv):
            output_dir = Path(argv[i + 1])
            i += 2
        else:
            i += 1

    try:
        symbols = load_universe(universe_path)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("Run: python src/build_universe.py", file=sys.stderr)
        return 1

    print(f"Loaded {len(symbols)} symbols from {universe_path}", file=sys.stderr)
    payload = run_scan(symbols)

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    full_path = output_dir / f"{stamp}.json"
    hits_path = output_dir / f"{stamp}_hits.json"

    full_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    hits_payload = {
        "generated_at": payload["generated_at"],
        "universe_count": payload["universe_count"],
        "hits": payload["hits"],
        "hit_filters": {
            "close_above_ma10": True,
            "ma10_above_ma20": True,
        },
        "rows": payload["hit_rows"],
    }
    hits_path.write_text(json.dumps(hits_payload, indent=2), encoding="utf-8")

    print(summarize_scan(payload))
    print()
    print(f"Full scan:  {full_path}")
    print(f"Hits only:  {hits_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
