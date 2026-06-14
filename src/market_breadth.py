"""Fetch and summarize S&P 500 market breadth from DeanFi daily_breadth.json."""

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
DEFAULT_PRIMARY = "https://r2.deanfi.com/advance-decline/daily_breadth.json"
DEFAULT_FALLBACK = (
    "https://raw.githubusercontent.com/GibsonNeo/deanfi-data/main/"
    "advance-decline/daily_breadth.json"
)
DEFAULT_CACHE = ROOT / "data" / "breadth" / "daily_breadth.json"


def load_config(config_path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    if yaml is None or not config_path.is_file():
        return {
            "market_breadth": {
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


def fetch_breadth(
    *,
    dry_run: bool = False,
    config_path: Path = DEFAULT_CONFIG,
) -> tuple[dict[str, Any], str]:
    """Return (payload, source_url). Raises on failure."""
    cfg = load_config(config_path).get("market_breadth", {})
    primary = cfg.get("primary_url", DEFAULT_PRIMARY)
    fallback = cfg.get("fallback_url", DEFAULT_FALLBACK)

    errors: list[str] = []
    for url in (primary, fallback):
        try:
            payload = fetch_json(url)
            if dry_run:
                return payload, url
            cache = ROOT / cfg.get("cache_path", DEFAULT_CACHE.relative_to(ROOT))
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return payload, url
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
            errors.append(f"{url}: {exc}")

    raise RuntimeError("All breadth sources failed:\n" + "\n".join(errors))


def summarize(payload: dict[str, Any]) -> str:
    meta = payload.get("metadata", {})
    data = payload.get("data", {})
    ad = data.get("advances_declines", {})
    vol = data.get("volume_metrics", {})
    hl = data.get("new_highs_lows", {})
    ma = data.get("moving_averages", {})

    lines = [
        "S&P 500 Market Breadth (DeanFi)",
        "=" * 40,
        f"Trading date:     {data.get('date', 'n/a')}",
        f"Generated at:     {meta.get('generated_at', 'n/a')}",
        f"Stocks analyzed:  {meta.get('total_stocks_analyzed', ad.get('total_stocks', 'n/a'))}",
        "",
        "Advance / Decline",
        f"  Advances:       {ad.get('advances', 'n/a')}",
        f"  Declines:       {ad.get('declines', 'n/a')}",
        f"  Unchanged:      {ad.get('unchanged', 'n/a')}",
        f"  A/D ratio:      {ad.get('advance_decline_ratio', 'n/a')}",
        f"  Advance %:      {ad.get('advance_percentage', 'n/a')}",
        "",
        "Volume breadth",
        f"  Adv volume %:   {vol.get('advancing_volume_pct', 'n/a')}",
        f"  Volume ratio:   {vol.get('volume_ratio', 'n/a')}",
        "",
        "52-week extremes (within 1%)",
        f"  Near 52w high:  {hl.get('stocks_near_52w_high', 'n/a')}",
        f"  Near 52w low:   {hl.get('stocks_near_52w_low', 'n/a')}",
        "",
        "Above moving average",
    ]
    for label, key in (
        ("20-day", "above_20_day_ma"),
        ("50-day", "above_50_day_ma"),
        ("200-day", "above_200_day_ma"),
    ):
        block = ma.get(key, {})
        lines.append(
            f"  {label:8} {block.get('count', 'n/a')} stocks ({block.get('percentage', 'n/a')}%)"
        )
    return "\n".join(lines)


def main() -> int:
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv
    try:
        payload, source = fetch_breadth(dry_run=dry_run)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(summarize(payload))
    print()
    if dry_run:
        print(f"[dry-run] Fetched from: {source}")
        print("[dry-run] Cache not written (pass no flag to save)")
    else:
        cfg = load_config().get("market_breadth", {})
        cache = ROOT / cfg.get("cache_path", DEFAULT_CACHE.relative_to(ROOT))
        print(f"Cached to: {cache}")
        print(f"Source:    {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
