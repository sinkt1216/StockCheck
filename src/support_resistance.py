"""Fetch and summarize support/resistance levels from DeanFi."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "sources.yaml"
DEFAULT_PRIMARY = "https://r2.deanfi.com/supportresistence/support_resistence.json"
DEFAULT_FALLBACK = (
    "https://raw.githubusercontent.com/GibsonNeo/deanfi-data/main/"
    "supportresistence/support_resistence.json"
)
DEFAULT_CACHE = ROOT / "data" / "supportresistence" / "support_resistence.json"

INDEX_LABELS = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq-100",
    "IWM": "Russell 2000",
    "DIA": "Dow Jones",
}


def load_config(config_path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    if yaml is None or not config_path.is_file():
        return {
            "support_resistance": {
                "primary_url": DEFAULT_PRIMARY,
                "fallback_url": DEFAULT_FALLBACK,
                "cache_path": str(DEFAULT_CACHE.relative_to(ROOT)),
            }
        }
    with config_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def fetch_json(url: str, timeout: int = 30) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "StockCheck/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_support_resistance(
    *,
    dry_run: bool = False,
    config_path: Path = DEFAULT_CONFIG,
) -> tuple[dict[str, Any], str]:
    cfg = load_config(config_path).get("support_resistance", {})
    primary = cfg.get("primary_url", DEFAULT_PRIMARY)
    fallback = cfg.get("fallback_url", DEFAULT_FALLBACK)
    errors: list[str] = []

    for url in (primary, fallback):
        try:
            payload = fetch_json(url)
            if not dry_run:
                cache = ROOT / cfg.get("cache_path", DEFAULT_CACHE.relative_to(ROOT))
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return payload, url
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
            errors.append(f"{url}: {exc}")

    raise RuntimeError("All support/resistance sources failed:\n" + "\n".join(errors))


def _fmt_levels(levels: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    return [f"    {key:4} {levels.get(key, 'n/a')}" for key in keys]


def summarize(payload: dict[str, Any]) -> str:
    meta = payload.get("metadata", {})
    data = payload.get("data", {})

    lines = [
        "Support / Resistance (DeanFi)",
        "=" * 40,
        f"Generated at:   {meta.get('generated_at', 'n/a')}",
        f"Data source:    {meta.get('data_source', 'n/a')}",
        f"Reference bar:  prior session H/L/C (pivot inputs)",
        f"Tickers:        {', '.join(data.keys())}",
        "",
    ]

    for symbol in ("SPY", "QQQ", "IWM", "DIA"):
        block = data.get(symbol)
        if not block:
            continue

        ref = block.get("reference_bar", {})
        trad = block.get("traditional_pivots", {})
        fib = block.get("fibonacci_pivots", {})
        sma = block.get("sma", {})
        close = ref.get("c")

        lines.extend(
            [
                f"{symbol} - {INDEX_LABELS.get(symbol, symbol)}",
                f"  Ref date:       {ref.get('date', 'n/a')}  close ${close}",
                f"  Ref range:      H ${ref.get('h')} / L ${ref.get('l')}",
                "  Traditional pivots:",
                *_fmt_levels(trad, ("P", "R1", "R2", "S1", "S2")),
                "  Fibonacci pivots:",
                *_fmt_levels(fib, ("FP", "FR1", "FR2", "FS1", "FS2")),
                "  Moving averages:",
                *_fmt_levels(sma, ("SMA20", "SMA50", "SMA200")),
            ]
        )

        if close is not None and trad.get("P") is not None:
            p = trad["P"]
            if close > trad.get("R1", float("inf")):
                zone = "above R1 (extended above pivot resistance)"
            elif close > p:
                zone = "above pivot (bullish side of P)"
            elif close > trad.get("S1", 0):
                zone = "below pivot (bearish side of P)"
            else:
                zone = "below S1 (extended below pivot support)"
            lines.append(f"  vs pivot P:     close {'>' if close > p else '<='} P -> {zone}")

        lines.append("")

    return "\n".join(lines).rstrip()


def main() -> int:
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv
    try:
        payload, source = fetch_support_resistance(dry_run=dry_run)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(summarize(payload))
    print()
    if dry_run:
        print(f"[dry-run] Fetched from: {source}")
        print("[dry-run] Cache not written (pass no flag to save)")
    else:
        cfg = load_config().get("support_resistance", {})
        cache = ROOT / cfg.get("cache_path", DEFAULT_CACHE.relative_to(ROOT))
        print(f"Cached to: {cache}")
        print(f"Source:    {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
