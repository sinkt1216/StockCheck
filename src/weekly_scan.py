"""Weekly universe scan: MA slope + volume (latest week)."""

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

from weekly_bars import fetch_avg_volume_50d, fetch_weekly_ohlc, latest_volume_spike, week_start_monday
from weekly_trend_state import compute_weekly_trend_series, load_config as load_wt_config

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "sources.yaml"
DEFAULT_UNIVERSE = ROOT / "data" / "universe" / "nyse.json"
DEFAULT_SCAN_DIR = ROOT / "data" / "scans"

LIQUIDITY_DEFAULTS = {"min_avg_volume_50d": 300_000}
SCAN_DEFAULTS = {"volume_ma_weeks": 20, "golden_cross_lookback_weeks": 26}


def load_liquidity_config(config_path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    if yaml is None or not config_path.is_file():
        return dict(LIQUIDITY_DEFAULTS)
    with config_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    merged = dict(LIQUIDITY_DEFAULTS)
    merged.update(data.get("liquidity", {}))
    return merged


def load_scan_config(config_path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    if yaml is None or not config_path.is_file():
        return dict(SCAN_DEFAULTS)
    with config_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    merged = dict(SCAN_DEFAULTS)
    merged.update(data.get("weekly_scan", {}))
    return merged


def load_universe(path: Path = DEFAULT_UNIVERSE) -> list[str]:
    if not path.is_file():
        raise FileNotFoundError(f"Universe file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return [entry["symbol"].upper() for entry in data.get("symbols", [])]


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Map legacy scan rows (ma_stack, multi-top fields) to current schema."""
    out = dict(row)
    if "price_above_ma10_ma20" not in out:
        out["price_above_ma10_ma20"] = bool(out.get("ma_stack"))
    return out


def _slope_accelerating(row: dict[str, Any]) -> bool:
    d4 = row.get("slope_4w_delta")
    if d4 is not None and d4 > 0:
        return True
    d1 = row.get("slope_1w_delta")
    return d1 is not None and d1 > 0


def _passes_volume(row: dict[str, Any], *, min_avg_volume_50d: int) -> bool:
    if min_avg_volume_50d <= 0:
        return True
    vol = row.get("avg_volume_50d")
    return vol is not None and vol > min_avg_volume_50d


def _golden_cross_recent(trend_df: Any, lookback_weeks: int) -> bool:
    if trend_df is None or len(trend_df) == 0 or lookback_weeks <= 0:
        return False
    tail = trend_df.iloc[-lookback_weeks:]
    if "golden_cross" not in tail.columns:
        return False
    return bool(tail["golden_cross"].any())


def _passes_golden_cross(row: dict[str, Any]) -> bool:
    if row.get("golden_cross"):
        return True
    recent = row.get("golden_cross_recent")
    if recent is not None:
        return bool(recent)
    # Legacy rows (no cross history): require MA10 above MA20 on latest week
    ma10, ma20 = row.get("ma10"), row.get("ma20")
    return ma10 is not None and ma20 is not None and ma10 > ma20


def _passes_buy_rule(
    row: dict[str, Any], *, min_avg_volume_50d: int, golden_cross_lookback_weeks: int
) -> bool:
    if not row.get("price_above_ma10_ma20"):
        return False
    if not _passes_golden_cross(row):
        return False
    if not _passes_volume(row, min_avg_volume_50d=min_avg_volume_50d):
        return False
    s1, s4 = row.get("slope_1w_pct"), row.get("slope_4w_pct")
    if s1 is None or s4 is None or s1 <= 0 or s4 <= 0:
        return False
    if not _slope_accelerating(row):
        return False
    return bool(row.get("volume_spike"))


def _assign_buy_signal(
    row: dict[str, Any], *, min_avg_volume_50d: int, golden_cross_lookback_weeks: int
) -> dict[str, Any]:
    row = _normalize_row(row)
    row["combined_signal"] = (
        "buy"
        if _passes_buy_rule(
            row,
            min_avg_volume_50d=min_avg_volume_50d,
            golden_cross_lookback_weeks=golden_cross_lookback_weeks,
        )
        else None
    )
    return row


def _is_hit(
    row: dict[str, Any], *, min_avg_volume_50d: int = 0, golden_cross_lookback_weeks: int = 26
) -> bool:
    return row.get("combined_signal") == "buy"


def _hit_filter_meta(*, min_avg_volume_50d: int, golden_cross_lookback_weeks: int) -> dict[str, Any]:
    return {
        "combined_signal": "buy",
        "price_above_ma10_ma20": True,
        "golden_cross": f"this week OR within last {golden_cross_lookback_weeks} weeks",
        "slope_1w_positive": True,
        "slope_4w_positive": True,
        "slope_acceleration": "slope_4w_delta > 0 OR slope_1w_delta > 0",
        "volume_spike": True,
        "min_avg_volume_50d": min_avg_volume_50d,
        "common_equity_universe": True,
    }


def scan_symbol(symbol: str) -> dict[str, Any] | None:
    wt_cfg = load_wt_config()
    scan_cfg = load_scan_config()
    min_avg_volume_50d = int(load_liquidity_config()["min_avg_volume_50d"])
    vol_ma_weeks = int(scan_cfg["volume_ma_weeks"])
    gc_lookback = int(scan_cfg["golden_cross_lookback_weeks"])

    try:
        weekly = fetch_weekly_ohlc(symbol, period="max")
    except RuntimeError:
        return None

    if len(weekly) < 30:
        return None

    trend_df = compute_weekly_trend_series(weekly, config=wt_cfg)
    trend = trend_df.iloc[-1].to_dict()
    prev_trend = trend_df.iloc[-2].to_dict() if len(trend_df) >= 2 else {}

    slope_4w = trend.get("slope_4w_pct")
    slope_1w = trend.get("slope_1w_pct")
    prev_slope_4w = prev_trend.get("slope_4w_pct")
    prev_slope_1w = prev_trend.get("slope_1w_pct")
    slope_4w_delta = (
        round(slope_4w - prev_slope_4w, 2)
        if slope_4w is not None and prev_slope_4w is not None
        else None
    )
    slope_1w_delta = (
        round(slope_1w - prev_slope_1w, 2)
        if slope_1w is not None and prev_slope_1w is not None
        else None
    )

    vol_metrics = latest_volume_spike(weekly, ma_weeks=vol_ma_weeks)

    row = {
        "symbol": symbol.upper(),
        "week_end": trend.get("week_end"),
        "week_start": week_start_monday(trend.get("week_end")) if trend.get("week_end") else None,
        "close": trend.get("close"),
        "ma10": trend.get("ma10"),
        "ma20": trend.get("ma20"),
        "trend_state": trend.get("state"),
        "slope_1w_pct": slope_1w,
        "slope_4w_pct": slope_4w,
        "slope_1w_delta": slope_1w_delta,
        "slope_4w_delta": slope_4w_delta,
        "early_turn": bool(trend.get("early_turn")),
        "confirmed_turn": bool(trend.get("confirmed_turn")),
        "price_above_ma10_ma20": bool(trend.get("price_above_ma10_ma20")),
        "ma10_above_ma20": bool(trend.get("ma10_above_ma20")),
        "golden_cross": bool(trend.get("golden_cross")),
        "golden_cross_recent": _golden_cross_recent(trend_df, gc_lookback),
        "avg_volume_50d": fetch_avg_volume_50d(symbol),
        "weekly_volume": vol_metrics["weekly_volume"],
        "volume_ma20": vol_metrics["volume_ma20"],
        "volume_spike": vol_metrics["volume_spike"],
        "combined_signal": None,
    }
    return _assign_buy_signal(
        row, min_avg_volume_50d=min_avg_volume_50d, golden_cross_lookback_weeks=gc_lookback
    )


def refilter_scan(
    payload: dict[str, Any],
    symbols: list[str] | None = None,
    *,
    min_avg_volume_50d: int | None = None,
    golden_cross_lookback_weeks: int | None = None,
) -> dict[str, Any]:
    """Re-apply buy rule to an existing scan (no yfinance)."""
    if min_avg_volume_50d is None:
        min_avg_volume_50d = int(load_liquidity_config()["min_avg_volume_50d"])
    if golden_cross_lookback_weeks is None:
        golden_cross_lookback_weeks = int(load_scan_config()["golden_cross_lookback_weeks"])
    allowed = {s.upper() for s in symbols} if symbols is not None else None
    results: list[dict[str, Any]] = []
    for row in payload.get("results", []):
        if allowed is not None and row.get("symbol", "").upper() not in allowed:
            continue
        results.append(
            _assign_buy_signal(
                row,
                min_avg_volume_50d=min_avg_volume_50d,
                golden_cross_lookback_weeks=golden_cross_lookback_weeks,
            )
        )

    hits = [
        r
        for r in results
        if _is_hit(
            r,
            min_avg_volume_50d=min_avg_volume_50d,
            golden_cross_lookback_weeks=golden_cross_lookback_weeks,
        )
    ]
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
    golden_cross_lookback_weeks: int | None = None,
) -> dict[str, Any]:
    """Fetch 50-day average volume for each row and recompute buy hits."""
    if min_avg_volume_50d is None:
        min_avg_volume_50d = int(load_liquidity_config()["min_avg_volume_50d"])
    if golden_cross_lookback_weeks is None:
        golden_cross_lookback_weeks = int(load_scan_config()["golden_cross_lookback_weeks"])
    results: list[dict[str, Any]] = []
    total = len(payload.get("results", []))
    for i, row in enumerate(payload.get("results", []), start=1):
        symbol = row["symbol"]
        if progress and (i == 1 or i % 25 == 0 or i == total):
            print(f"Volume {i}/{total}: {symbol}...", file=sys.stderr)
        updated = _normalize_row(row)
        updated["avg_volume_50d"] = fetch_avg_volume_50d(symbol)
        results.append(
            _assign_buy_signal(
                updated,
                min_avg_volume_50d=min_avg_volume_50d,
                golden_cross_lookback_weeks=golden_cross_lookback_weeks,
            )
        )

    out = dict(payload)
    out["results"] = results
    out["hit_rows"] = [
        r
        for r in results
        if _is_hit(
            r,
            min_avg_volume_50d=min_avg_volume_50d,
            golden_cross_lookback_weeks=golden_cross_lookback_weeks,
        )
    ]
    out["hits"] = len(out["hit_rows"])
    return out


def enrich_scan_weekly_volume(
    payload: dict[str, Any],
    *,
    progress: bool = True,
    min_avg_volume_50d: int | None = None,
    golden_cross_lookback_weeks: int | None = None,
) -> dict[str, Any]:
    """Backfill weekly volume spike fields and recompute buy hits."""
    if min_avg_volume_50d is None:
        min_avg_volume_50d = int(load_liquidity_config()["min_avg_volume_50d"])
    if golden_cross_lookback_weeks is None:
        golden_cross_lookback_weeks = int(load_scan_config()["golden_cross_lookback_weeks"])
    vol_ma_weeks = int(load_scan_config()["volume_ma_weeks"])
    results: list[dict[str, Any]] = []
    total = len(payload.get("results", []))
    for i, row in enumerate(payload.get("results", []), start=1):
        symbol = row["symbol"]
        if progress and (i == 1 or i % 25 == 0 or i == total):
            print(f"Weekly vol {i}/{total}: {symbol}...", file=sys.stderr)
        updated = _normalize_row(row)
        try:
            weekly = fetch_weekly_ohlc(symbol, period="max")
            updated.update(latest_volume_spike(weekly, ma_weeks=vol_ma_weeks))
            trend_df = compute_weekly_trend_series(weekly, config=load_wt_config())
            trend = trend_df.iloc[-1].to_dict()
            updated["golden_cross"] = bool(trend.get("golden_cross"))
            updated["ma10_above_ma20"] = bool(trend.get("ma10_above_ma20"))
            updated["golden_cross_recent"] = _golden_cross_recent(trend_df, golden_cross_lookback_weeks)
        except RuntimeError:
            updated["weekly_volume"] = None
            updated["volume_ma20"] = None
            updated["volume_spike"] = False
        results.append(
            _assign_buy_signal(
                updated,
                min_avg_volume_50d=min_avg_volume_50d,
                golden_cross_lookback_weeks=golden_cross_lookback_weeks,
            )
        )

    out = dict(payload)
    out["results"] = results
    out["hit_rows"] = [
        r
        for r in results
        if _is_hit(
            r,
            min_avg_volume_50d=min_avg_volume_50d,
            golden_cross_lookback_weeks=golden_cross_lookback_weeks,
        )
    ]
    out["hits"] = len(out["hit_rows"])
    return out


def write_scan_outputs(
    payload: dict[str, Any],
    output_dir: Path,
    *,
    stamp: str | None = None,
    min_avg_volume_50d: int | None = None,
    golden_cross_lookback_weeks: int | None = None,
) -> tuple[Path, Path]:
    if min_avg_volume_50d is None:
        min_avg_volume_50d = int(load_liquidity_config()["min_avg_volume_50d"])
    if golden_cross_lookback_weeks is None:
        golden_cross_lookback_weeks = int(load_scan_config()["golden_cross_lookback_weeks"])
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = stamp or datetime.now(UTC).strftime("%Y-%m-%d")
    full_path = output_dir / f"{stamp}.json"
    hits_path = output_dir / f"{stamp}_hits.json"
    full_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    hits_payload = {
        "generated_at": payload["generated_at"],
        "universe_count": payload["universe_count"],
        "hits": payload["hits"],
        "hit_filters": _hit_filter_meta(
            min_avg_volume_50d=min_avg_volume_50d,
            golden_cross_lookback_weeks=golden_cross_lookback_weeks,
        ),
        "rows": payload["hit_rows"],
    }
    hits_path.write_text(json.dumps(hits_payload, indent=2), encoding="utf-8")
    return full_path, hits_path


def run_scan(symbols: list[str], *, progress: bool = True) -> dict[str, Any]:
    min_avg_volume_50d = int(load_liquidity_config()["min_avg_volume_50d"])
    golden_cross_lookback_weeks = int(load_scan_config()["golden_cross_lookback_weeks"])
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

    hits = [
        r
        for r in results
        if _is_hit(
            r,
            min_avg_volume_50d=min_avg_volume_50d,
            golden_cross_lookback_weeks=golden_cross_lookback_weeks,
        )
    ]
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
        f"Buy hits: {payload['hits']}  Errors: {payload['errors']}",
        f"Week (Mon): {week_start_monday(payload['hit_rows'][0]['week_end']) if payload['hit_rows'] else 'n/a'}",
        "",
        f"{'Symbol':<8} {'Close':>8} {'Trend':<12} {'slp1w':>7} {'slp4w':>7} {'d4w':>7} {'Flags'}",
        "-" * 72,
    ]

    for row in sorted(payload["hit_rows"], key=lambda r: r["symbol"]):
        flags: list[str] = ["BUY"]
        if row.get("volume_spike"):
            flags.append("VOL_SPIKE")
        if row.get("golden_cross"):
            flags.append("GC")
        elif row.get("golden_cross_recent"):
            flags.append("GC_recent")
        if row.get("early_turn"):
            flags.append("early_turn")
        slope = row.get("slope_4w_pct")
        slope_str = f"{slope:+.2f}%" if slope is not None else "n/a"
        s1 = row.get("slope_1w_pct")
        s1_str = f"{s1:+.2f}%" if s1 is not None else "n/a"
        d4 = row.get("slope_4w_delta")
        d4_str = f"{d4:+.2f}%" if d4 is not None else "n/a"
        lines.append(
            f"{row['symbol']:<8} ${row.get('close', 0):>7.2f} "
            f"{row.get('trend_state', ''):<12} {s1_str:>7} {slope_str:>7} {d4_str:>7} "
            f"{', '.join(flags)}"
        )
    return "\n".join(lines)


def main() -> int:
    universe_path = DEFAULT_UNIVERSE
    output_dir = DEFAULT_SCAN_DIR
    refilter_path: Path | None = None
    enrich_path: Path | None = None
    enrich_weekly_path: Path | None = None
    universe_explicit = False
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        if argv[i] == "--universe" and i + 1 < len(argv):
            universe_path = Path(argv[i + 1])
            universe_explicit = True
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
        elif argv[i] == "--enrich-weekly-volume" and i + 1 < len(argv):
            enrich_weekly_path = Path(argv[i + 1])
            i += 2
        else:
            i += 1

    min_avg_volume_50d = int(load_liquidity_config()["min_avg_volume_50d"])

    if enrich_weekly_path is not None:
        if not enrich_weekly_path.is_file():
            print(f"ERROR: scan file not found: {enrich_weekly_path}", file=sys.stderr)
            return 1
        payload = json.loads(enrich_weekly_path.read_text(encoding="utf-8"))
        stamp = enrich_weekly_path.stem.replace("_hits", "")
        print(
            f"Enriching weekly volume spike on {enrich_weekly_path.name} "
            f"({len(payload.get('results', []))} rows)...",
            file=sys.stderr,
        )
        payload = enrich_scan_weekly_volume(payload, min_avg_volume_50d=min_avg_volume_50d)
        full_path, hits_path = write_scan_outputs(
            payload, output_dir, stamp=stamp, min_avg_volume_50d=min_avg_volume_50d
        )
        print(summarize_scan(payload))
        print()
        print(f"Full scan:  {full_path}")
        print(f"Hits only:  {hits_path}")
        return 0

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
        if refilter_path is None:
            print(f"ERROR: {exc}", file=sys.stderr)
            print("Run: python src/build_universe.py", file=sys.stderr)
            return 1
        symbols = []

    if refilter_path is not None:
        if not refilter_path.is_file():
            print(f"ERROR: scan file not found: {refilter_path}", file=sys.stderr)
            return 1
        payload = json.loads(refilter_path.read_text(encoding="utf-8"))
        stamp = refilter_path.stem
        filter_symbols = symbols if universe_explicit else None
        if filter_symbols is not None:
            print(
                f"Re-filtering {refilter_path.name} with {len(filter_symbols)} universe symbols...",
                file=sys.stderr,
            )
        else:
            print(
                f"Re-filtering {refilter_path.name} ({len(payload.get('results', []))} rows)...",
                file=sys.stderr,
            )
        payload = refilter_scan(payload, filter_symbols, min_avg_volume_50d=min_avg_volume_50d)
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
