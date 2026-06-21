"""Build symbol universe JSON from exchange symbol directories."""

from __future__ import annotations

import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "data" / "universe" / "nyse.json"

NASDAQ_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

# otherlisted.txt Exchange column: N = NYSE, A = AMEX, P = ARCA, Z = BATS, V = IEX
EXCHANGE_CODES = {
    "NYSE": "N",
    "AMEX": "A",
    "ARCA": "P",
}


def _fetch_lines(url: str) -> list[str]:
    req = urllib.request.Request(url, headers={"User-Agent": "StockCheck/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        text = resp.read().decode("utf-8")
    return text.strip().splitlines()


def _is_common_stock(symbol: str, name: str, *, etf: str, test_issue: str) -> bool:
    if etf.upper() == "Y" or test_issue.upper() == "Y":
        return False
    if not symbol or len(symbol) > 5:
        return False
    # Skip preferred, warrants, units, rights (symbol suffixes or name hints)
    if any(ch in symbol for ch in ("$", "+", "=", "^", "~")):
        return False
    upper_name = name.upper()
    skip_words = (" ETF", " ETN", " FUND", " TRUST", "WARRANT", " PREFERRED", " UNIT", " RIGHT")
    if any(w in upper_name for w in skip_words):
        return False
    return True


def fetch_nyse_symbols() -> list[dict[str, str]]:
    lines = _fetch_lines(OTHER_LISTED)
    symbols: list[dict[str, str]] = []
    for line in lines[1:]:  # skip header
        if line.startswith("File Creation"):
            break
        parts = line.split("|")
        if len(parts) < 8:
            continue
        symbol, name, exchange, _cqs, etf, _lot, test_issue, _nasdaq_sym = parts[:8]
        if exchange != EXCHANGE_CODES["NYSE"]:
            continue
        if not _is_common_stock(symbol, name, etf=etf, test_issue=test_issue):
            continue
        symbols.append(
            {
                "symbol": symbol.strip().upper(),
                "name": name.strip(),
                "market": "US",
                "exchange": "NYSE",
            }
        )
    symbols.sort(key=lambda x: x["symbol"])
    return symbols


def build_universe(*, exchange: str = "NYSE") -> dict:
    exchange = exchange.upper()
    if exchange != "NYSE":
        raise ValueError(f"Trial build supports NYSE only (got {exchange})")
    entries = fetch_nyse_symbols()
    return {
        "updated": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": OTHER_LISTED,
        "exchange": exchange,
        "count": len(entries),
        "symbols": entries,
    }


def main() -> int:
    exchange = "NYSE"
    output = DEFAULT_OUTPUT
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        if argv[i] == "--exchange" and i + 1 < len(argv):
            exchange = argv[i + 1].upper()
            i += 2
        elif argv[i] == "--output" and i + 1 < len(argv):
            output = Path(argv[i + 1])
            i += 2
        else:
            i += 1

    try:
        payload = build_universe(exchange=exchange)
    except (urllib.error.URLError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {payload['count']} {exchange} symbols to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
