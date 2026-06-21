"""Weekly universe scan: MA slope + multi-top breakout (latest week)."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

from multi_top_breakout import _eval_at_index, load_config as load_mt_config
from weekly_bars import fetch_avg_volume_50d, fetch_weekly_ohlc
from weekly_trend_state import compute_weekly_trend_series, load_config as load_wt_config

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "sources.yaml"
DEFAULT_UNIVERSE = ROOT / "data" / "universe" / "nyse.json"
DEFAULT_SCAN_DIR = ROOT / "data" / "scans"

SLOPE_TURN = 0.15
LIQUIDITY_DEFAULTS = {"min_avg_volume_50d": 300_000}


def load_liquidity_config(config_path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    if yaml is None or not config_path.is_file():
        return dict(LIQUIDITY_DEFAULTS)
    with config_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    merged = dict(LIQUIDITY_DEFAULTS)
    merged.update(data.get("liquidity", {}))
    return merged


def load_universe(path: Path = DEFAULT_UNIVERSE) -> list[str]:
    if not path.is_file():
        raise FileNotFoundError(f"Universe file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return [entry["symbol"].upper() for entry in data.get("symbols", [])]


def _combined_signal(
    trend: dict[str, Any],
    mt: dict[str, Any],
    *,
    slope_4w_delta: float | None = None,
) -> str | None:
    """Assign combined_signal — priority: watch → break → confirmed → extended."""
    stage = mt.get("stage")
    slope = trend.get("slope_4w_pct")
    breakout = mt.get("breakout")
    close = trend.get("close")
    ma10 = trend.get("ma10")

    slopes_rising = (
        slope is not None
        and slope > 0
        and slope_4w_delta is not None
        and slope_4w_delta > 0
    )

    if stage == "WATCH" and slopes_rising:
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

    slope_4w = trend.get("slope_4w_pct")
    prev_slope_4w = prev_trend.get("slope_4w_pct")
    slope_delta = None
    if slope_4w is not None and prev_slope_4w is not None:
        slope_delta = round(slope_4w - prev_slope_4w, 2)

    combined = _combined_signal(trend, mt, slope_4w_delta=slope_delta)

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
        "avg_volume_50d": fetch_avg_volume_50d(symbol),
    }


def _ma_aligned(row: dict[str, Any]) -> bool:
    close = row.get("close")
    ma10 = row.get("ma10")
    ma20 = row.get("ma20")
    if close is None or ma10 is None or ma20 is None:
        return False
    return close > ma10 and ma10 > ma20


def _passes_volume(row: dict[str, Any], *, min_avg_volume_50d: int) -> bool:
    if min_avg_volume_50d <= 0:
        return True
    vol = row.get("avg_volume_50d")
    return vol is not None and vol > min_avg_volume_50d


def _is_hit(row: dict[str, Any], *, min_avg_volume_50d: int = 0) -> bool:
    if not _ma_aligned(row):
        return False
    if not _passes_volume(row, min_avg_volume_50d=min_avg_volume_50d):
        return False
    return bool(
        row.get("combined_signal")
        or row.get("early_turn")
        or row.get("first_break")
    )


def _hit_filter_meta(*, min_avg_volume_50d: int) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "close_above_ma10": True,
        "ma10_above_ma20": True,
        "common_equity_universe": True,
    }
    if min_avg_volume_50d > 0:
        meta["min_avg_volume_50d"] = min_avg_volume_50d
    return meta


def refilter_scan(
    payload: dict[str, Any],
    symbols: list[str] | None = None,
    *,
    min_avg_volume_50d: int | None = None,
) -> dict[str, Any]:
    """Re-apply combined_signal / hit rules to an existing scan (no yfinance)."""
    if min_avg_volume_50d is None:
        min_avg_volume_50d = int(load_liquidity_config()["min_avg_volume_50d"])
    allowed = {s.upper() for s in symbols} if symbols is not None else None
    results: list[dict[str, Any]] = []
    for row in payload.get("results", []):
        if allowed is not None and row.get("symbol", "").upper() not in allowed:
            continue
        trend = {
            "slope_4w_pct": row.get("slope_4w_pct"),
            "early_turn": row.get("early_turn"),
            "state": row.get("trend_state"),
            "close": row.get("close"),
            "ma10": row.get("ma10"),
        }
        mt = {"stage": row.get("mt_stage"), "breakout": row.get("breakout")}
        row = dict(row)
        row["combined_signal"] = _combined_signal(
            trend, mt, slope_4w_delta=row.get("slope_4w_delta")
        )
        results.append(row)

    hits = [r for r in results if _is_hit(r, min_avg_volume_50d=min_avg_volume_50d)]
    out = dict(payload)
    out["results"] = results
    out["hit_rows"] = hits
    out["hits"] = len(hits)
    if allowed is not None:
        out["universe_count"] = len(allowed)
        out["scanned"] = len(results)
    return out


def enrich_scan_volume(
    payload: dict[str, Any],
    *,
    progress: bool = True,
    min_avg_volume_50d: int | None = None,
) -> dict[str, Any]:
    """Fetch 50-day average volume for each scanned row and recompute hits."""
    if min_avg_volume_50d is None:
        min_avg_volume_50d = int(load_liquidity_config()["min_avg_volume_50d"])
    results: list[dict[str, Any]] = []
    total = len(payload.get("results", []))
    for i, row in enumerate(payload.get("results", []), start=1):
        symbol = row["symbol"]
        if progress and (i == 1 or i % 25 == 0 or i == total):
            print(f"Volume {i}/{total}: {symbol}...", file=sys.stderr)
        updated = dict(row)
        updated["avg_volume_50d"] = fetch_avg_volume_50d(symbol)
        results.append(updated)

    out = dict(payload)
    out["results"] = results
    out["hit_rows"] = [r for r in results if _is_hit(r, min_avg_volume_50d=min_avg_volume_50d)]
    out["hits"] = len(out["hit_rows"])
    return out


def write_scan_outputs(
    payload: dict[str, Any],
    output_dir: Path,
    *,
    stamp: str | None = None,
    min_avg_volume_50d: int | None = None,
) -> tuple[Path, Path]:
    if min_avg_volume_50d is None:
        min_avg_volume_50d = int(load_liquidity_config()["min_avg_volume_50d"])
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = stamp or datetime.now(UTC).strftime("%Y-%m-%d")
    full_path = output_dir / f"{stamp}.json"
    hits_path = output_dir / f"{stamp}_hits.json"
    full_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    hits_payload = {
        "generated_at": payload["generated_at"],
        "universe_count": payload["universe_count"],
        "hits": payload["hits"],
        "hit_filters": _hit_filter_meta(min_avg_volume_50d=min_avg_volume_50d),
        "rows": payload["hit_rows"],
    }
    hits_path.write_text(json.dumps(hits_payload, indent=2), encoding="utf-8")
    return full_path, hits_path


def run_scan(symbols: list[str], *, progress: bool = True) -> dict[str, Any]:
    min_avg_volume_50d = int(load_liquidity_config()["min_avg_volume_50d"])
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

    hits = [r for r in results if _is_hit(r, min_avg_volume_50d=min_avg_volume_50d)]
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
    refilter_path: Path | None = None
    enrich_path: Path | None = None
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        if argv[i] == "--universe" and i + 1 < len(argv):
            universe_path = Path(argv[i + 1])
            i += 2
        elif argv[i] == "--output-dir" and i + 1 < len(argv):
            output_dir = Path(argv[i + 1])
            i += 2
        elif argv[i] == "--refilter" and i + 1 < len(argv):
            refilter_path = Path(argv[i + 1])
            i += 2
        elif argv[i] == "--enrich-volume" and i + 1 < len(argv):
            enrich_path = Path(argv[i + 1])
            i += 2
        else:
            i += 1

    min_avg_volume_50d = int(load_liquidity_config()["min_avg_volume_50d"])

    if enrich_path is not None:
        if not enrich_path.is_file():
            print(f"ERROR: scan file not found: {enrich_path}", file=sys.stderr)
            return 1
        payload = json.loads(enrich_path.read_text(encoding="utf-8"))
        stamp = enrich_path.stem.replace("_hits", "")
        print(f"Enriching volume on {enrich_path.name} ({len(payload.get('results', []))} rows)...", file=sys.stderr)
        payload = enrich_scan_volume(payload, min_avg_volume_50d=min_avg_volume_50d)
        full_path, hits_path = write_scan_outputs(
            payload, output_dir, stamp=stamp, min_avg_volume_50d=min_avg_volume_50d
        )
        print(summarize_scan(payload))
        print()
        print(f"Full scan:  {full_path}")
        print(f"Hits only:  {hits_path}")
        return 0

    try:
        symbols = load_universe(universe_path)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("Run: python src/build_universe.py", file=sys.stderr)
        return 1

    if refilter_path is not None:
        if not refilter_path.is_file():
            print(f"ERROR: scan file not found: {refilter_path}", file=sys.stderr)
            return 1
        payload = json.loads(refilter_path.read_text(encoding="utf-8"))
        stamp = refilter_path.stem
        print(
            f"Re-filtering {refilter_path.name} with {len(symbols)} universe symbols...",
            file=sys.stderr,
        )
        payload = refilter_scan(payload, symbols, min_avg_volume_50d=min_avg_volume_50d)
        full_path, hits_path = write_scan_outputs(
            payload, output_dir, stamp=stamp, min_avg_volume_50d=min_avg_volume_50d
        )
    else:
        print(f"Loaded {len(symbols)} symbols from {universe_path}", file=sys.stderr)
        payload = run_scan(symbols)
        date_stamp = datetime.now(UTC).strftime("%Y-%m-%d")
        univ_tag = universe_path.stem
        stamp = f"{date_stamp}_{univ_tag}" if univ_tag != "nyse" else date_stamp
        full_path, hits_path = write_scan_outputs(
            payload, output_dir, stamp=stamp, min_avg_volume_50d=min_avg_volume_50d
        )

    print(summarize_scan(payload))
    print()
    print(f"Full scan:  {full_path}")
    print(f"Hits only:  {hits_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
