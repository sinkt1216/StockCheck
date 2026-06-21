"""Fetch Cboe implied correlation indices from Google Finance (delayed, free)."""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "sources.yaml"
DEFAULT_SYMBOL = "COR1M:INDEXCBOE"
DEFAULT_CACHE = ROOT / "data" / "correlation" / "cor1m.json"
BATCHEXECUTE_URL = "https://www.google.com/finance/_/GoogleFinanceUi/data/batchexecute"
QUOTE_PAGE = "https://www.google.com/finance/quote/{symbol}"
WINDOW_MODES = {
    "1D": 1,
    "1M": 3,
    "1Y": 6,
}
DEFAULT_WINDOW = "1Y"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
    "Cookie": "CONSENT=YES+",
}


def load_config(config_path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    if yaml is None or not config_path.is_file():
        return {
            "implied_correlation": {
                "symbol": DEFAULT_SYMBOL,
                "cache_path": str(DEFAULT_CACHE.relative_to(ROOT)),
                "default_window": DEFAULT_WINDOW,
                "refresh_minutes": 60,
            }
        }
    with config_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def ticker_tuple(ticker: str) -> list[Any]:
    if "-" in ticker and ":" not in ticker:
        base, quote = ticker.split("-", 1)
        return [None, None, [base, quote]]
    sym, exchange = ticker.split(":", 1)
    return [None, [sym, exchange]]


def build_body(requests: list[dict[str, Any]]) -> bytes:
    arr = [
        [r["id"], json.dumps(r["req"], separators=(",", ":")), None, str(i + 1)]
        for i, r in enumerate(requests)
    ]
    payload = f"f.req={urllib.parse.quote(json.dumps([arr], separators=(',', ':')))}"
    return payload.encode("utf-8")


def parse_batchexecute(raw: str) -> list[dict[str, Any]]:
    stripped = re.sub(r"^\)\]\}'\n\n?", "", raw)
    results: list[dict[str, Any]] = []
    lines = stripped.split("\n")
    i = 0
    while i < len(lines):
        if re.fullmatch(r"[0-9a-fA-F]+", lines[i].strip()) and i + 1 < len(lines):
            try:
                for entry in json.loads(lines[i + 1]):
                    if entry[0] == "wrb.fr":
                        results.append({"id": entry[1], "data": json.loads(entry[2])})
            except json.JSONDecodeError:
                pass
            i += 2
        else:
            i += 1
    return results


def rpc_call(symbol: str, requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rpcids = ",".join(dict.fromkeys(r["id"] for r in requests))
    url = (
        f"{BATCHEXECUTE_URL}?rpcids={rpcids}"
        f"&source-path=/finance/quote/{urllib.parse.quote(symbol, safe='')}"
        "&hl=en&gl=us&rt=c"
    )
    req = urllib.request.Request(url, data=build_body(requests), headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return parse_batchexecute(resp.read().decode("utf-8", "replace"))


def chart_points(chart_raw: list[Any]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for period in chart_raw[3] or []:
        for pt in period[1] or []:
            if not isinstance(pt, list) or len(pt) < 2:
                continue
            if not isinstance(pt[0], list) or not isinstance(pt[1], list):
                continue
            date_parts = pt[0]
            if len(date_parts) < 3:
                continue
            y, m, d = date_parts[0], date_parts[1], date_parts[2]
            points.append(
                {
                    "date": f"{int(y):04d}-{int(m):02d}-{int(d):02d}",
                    "close": float(pt[1][0]),
                    "volume": pt[2] if len(pt) > 2 else None,
                }
            )
    return points


def parse_quote(raw: list[Any]) -> dict[str, Any]:
    q = raw[0][0][0]
    return {
        "symbol": q[21] if len(q) > 21 and isinstance(q[21], str) else None,
        "name": q[2],
        "price": float(q[5][0]),
        "change": float(q[5][1]),
        "change_percent": float(q[5][2]),
        "previous_close": float(q[7]) if q[7] is not None else None,
        "currency": q[4],
    }


def fetch_implied_correlation(
    *,
    symbol: str | None = None,
    window: str = DEFAULT_WINDOW,
    dry_run: bool = False,
    config_path: Path = DEFAULT_CONFIG,
) -> dict[str, Any]:
    cfg = load_config(config_path).get("implied_correlation", {})
    symbol = (symbol or cfg.get("symbol", DEFAULT_SYMBOL)).upper()
    window = window.upper()
    mode = WINDOW_MODES.get(window)
    if mode is None:
        supported = ", ".join(sorted(WINDOW_MODES))
        raise ValueError(f"Unsupported window {window!r}; use one of: {supported}")

    t = ticker_tuple(symbol)
    requests = [
        {"id": "xh8wxf", "req": [[t], 1]},
        {"id": "AiCwsd", "req": [[t], mode]},
    ]
    try:
        results = rpc_call(symbol, requests)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Google Finance fetch failed for {symbol}: {exc}") from exc

    quote_raw = next((r["data"] for r in results if r["id"] == "xh8wxf"), None)
    chart_raw = next((r["data"] for r in results if r["id"] == "AiCwsd"), None)
    if quote_raw is None or chart_raw is None:
        raise RuntimeError(f"Incomplete Google Finance response for {symbol}")

    quote = parse_quote(quote_raw)
    history = chart_points(chart_raw[0][0])
    payload = {
        "symbol": symbol,
        "window": window,
        "quote": quote,
        "history": history,
        "source": "google_finance_batchexecute",
        "delayed": True,
        "fetched_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }

    if dry_run:
        return payload

    cache = ROOT / cfg.get("cache_path", DEFAULT_CACHE.relative_to(ROOT))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def summarize(payload: dict[str, Any]) -> str:
    quote = payload["quote"]
    history = payload.get("history", [])
    lines = [
        f"Implied Correlation - {payload['symbol']} (Google Finance, delayed)",
        "=" * 52,
        f"Name:             {quote.get('name')}",
        f"Level:            {quote.get('price')}",
        f"Change:           {quote.get('change')} ({quote.get('change_percent')}%)",
        f"Previous close:   {quote.get('previous_close')}",
        f"Window:           {payload.get('window')}",
        f"History points:   {len(history)}",
    ]
    if history:
        lines.extend(
            [
                "",
                "Recent closes:",
                f"  {history[0]['date']}: {history[0]['close']}",
                f"  {history[-1]['date']}: {history[-1]['close']}",
            ]
        )
    if len(history) >= 2:
        first, last = history[0]["close"], history[-1]["close"]
        delta = last - first
        lines.append(f"\nRange move: {delta:+.2f} over {history[0]['date']} -> {history[-1]['date']}")
    lines.append("\nNote: delayed data via Google Finance RPC; not Cboe real-time feed.")
    return "\n".join(lines)


def main() -> int:
    window = DEFAULT_WINDOW
    symbol: str | None = None
    dry_run = "--dry-run" in sys.argv
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--window" and i + 1 < len(argv):
            window = argv[i + 1].upper()
            i += 2
            continue
        if arg == "--symbol" and i + 1 < len(argv):
            symbol = argv[i + 1].upper()
            i += 2
            continue
        if not arg.startswith("-") and symbol is None:
            symbol = arg.upper()
        i += 1

    try:
        payload = fetch_implied_correlation(symbol=symbol, window=window, dry_run=dry_run)
    except (RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(summarize(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
