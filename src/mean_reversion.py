"""Fetch and summarize mean reversion snapshots from DeanFi."""

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

DEFAULT_DATASETS = {
    "ma_spreads": {
        "primary_url": "https://r2.deanfi.com/meanreversion/ma_spreads_snapshot.json",
        "fallback_url": (
            "https://raw.githubusercontent.com/GibsonNeo/deanfi-data/main/"
            "meanreversion/ma_spreads_snapshot.json"
        ),
        "cache_path": "data/meanreversion/ma_spreads_snapshot.json",
    },
    "price_vs_ma": {
        "primary_url": "https://r2.deanfi.com/meanreversion/price_vs_ma_snapshot.json",
        "fallback_url": (
            "https://raw.githubusercontent.com/GibsonNeo/deanfi-data/main/"
            "meanreversion/price_vs_ma_snapshot.json"
        ),
        "cache_path": "data/meanreversion/price_vs_ma_snapshot.json",
    },
}


def load_config(config_path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    if yaml is None or not config_path.is_file():
        return {"mean_reversion": {"datasets": DEFAULT_DATASETS}}
    with config_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def fetch_json(url: str, timeout: int = 30) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "StockCheck/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_dataset(
    name: str,
    cfg: dict[str, Any],
    *,
    dry_run: bool,
) -> tuple[dict[str, Any], str]:
    primary = cfg.get("primary_url")
    fallback = cfg.get("fallback_url")
    errors: list[str] = []

    for url in (primary, fallback):
        if not url:
            continue
        try:
            payload = fetch_json(url)
            if not dry_run:
                cache = ROOT / cfg.get("cache_path", f"data/meanreversion/{name}.json")
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return payload, url
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
            errors.append(f"{url}: {exc}")

    raise RuntimeError(f"{name} fetch failed:\n" + "\n".join(errors))


def fetch_mean_reversion(
    *,
    dry_run: bool = False,
    config_path: Path = DEFAULT_CONFIG,
) -> dict[str, tuple[dict[str, Any], str]]:
    cfg = load_config(config_path).get("mean_reversion", {})
    datasets = cfg.get("datasets", DEFAULT_DATASETS)
    results: dict[str, tuple[dict[str, Any], str]] = {}

    for name, dataset_cfg in datasets.items():
        results[name] = fetch_dataset(name, dataset_cfg, dry_run=dry_run)

    return results


def _fmt_pair(label: str, pair: dict[str, Any]) -> str:
    return (
        f"    {label}: spread {pair.get('spread_percent', 'n/a')}% "
        f"(z={pair.get('zscore', 'n/a')}, {pair.get('signal', 'n/a')})"
    )


def summarize(results: dict[str, tuple[dict[str, Any], str]]) -> str:
    spreads, _ = results["ma_spreads"]
    price_ma, _ = results["price_vs_ma"]
    meta = spreads.get("metadata", {})

    lines = [
        "Mean Reversion Snapshot (DeanFi)",
        "=" * 40,
        f"Generated at:  {meta.get('generated_at', 'n/a')}",
        f"ETFs tracked:  {', '.join(spreads.get('indices', {}).keys())}",
        "",
    ]

    for symbol in ("SPY", "QQQ", "IWM"):
        s = spreads.get("indices", {}).get(symbol)
        p = price_ma.get("indices", {}).get(symbol)
        if not s or not p:
            continue

        lines.extend(
            [
                f"{symbol} — {s.get('tracks_index', s.get('name', symbol))} @ ${s.get('current_price', 'n/a')}",
                f"  Trend alignment: {p.get('trend_alignment', 'n/a')}",
                "  Price vs MA:",
            ]
        )
        for ma_key, label in (("ma_20", "20-day"), ("ma_50", "50-day"), ("ma_200", "200-day")):
            m = p.get("metrics_by_ma", {}).get(ma_key, {})
            lines.append(
                f"    {label:8} {m.get('distance_percent', 'n/a')}% "
                f"(z={m.get('zscore', 'n/a')}, {m.get('signal', 'n/a')})"
            )

        lines.append("  MA spreads:")
        pairs = s.get("ma_pairs", {})
        lines.append(_fmt_pair("20 vs 50 ", pairs.get("short_term_vs_intermediate", {})))
        lines.append(_fmt_pair("20 vs 200", pairs.get("short_term_vs_long_term", {})))
        lines.append(_fmt_pair("50 vs 200", pairs.get("intermediate_vs_long_term", {})))
        lines.append("")

    return "\n".join(lines).rstrip()


def main() -> int:
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv
    try:
        results = fetch_mean_reversion(dry_run=dry_run)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(summarize(results))
    print()
    if dry_run:
        for name, (_, source) in results.items():
            print(f"[dry-run] {name}: {source}")
        print("[dry-run] Cache not written (pass no flag to save)")
    else:
        cfg = load_config().get("mean_reversion", {}).get("datasets", DEFAULT_DATASETS)
        for name in results:
            cache = ROOT / cfg[name].get("cache_path", f"data/meanreversion/{name}.json")
            print(f"Cached {name}: {cache}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
