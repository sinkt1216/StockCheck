"""Build symbol universe JSON from exchange symbol directories."""

from __future__ import annotations

import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUTS = {
    "NYSE": ROOT / "data" / "universe" / "nyse.json",
    "NASDAQ": ROOT / "data" / "universe" / "nasdaq.json",
}

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


# Name hints for coupon-bearing debt / preferred (baby bonds, notes, debentures).
_DEBT_NAME_HINTS = (
    "NOTES",
    "NOTE ",
    "DEBENTURE",
    "SUBORDINATED",
    "SENIOR NOTE",
    "JUNIOR SUBORDINATED",
    "FIXED-TO-FLOATING",
    "FIXED RATE SENIOR",
    "PERPETUAL SUBORDINATED",
)

# Non-common-equity listings (ETFs, structured products, preferred, warrants, etc.).
_SKIP_NAME_WORDS = (
    " ETF",
    " ETN",
    " FUND",
    "WARRANT",
    " PREFERRED",
    " PREF.",
    " PFD.",
    " UNIT",
    " UNITS",
    " RIGHT",
    " RIGHTS",
    " DEPOSITARY SHARES OF",  # depositary shares *of* debt/preferred, not ADRs
    " RECEIPT",
)


def _is_common_stock(symbol: str, name: str, *, etf: str, test_issue: str) -> bool:
    """Common equity only — excludes ETFs, debt, preferred, warrants, units."""
    if etf.upper() == "Y" or test_issue.upper() == "Y":
        return False
    if not symbol or len(symbol) > 5:
        return False
    if any(ch in symbol for ch in ("$", "+", "=", "^", "~")):
        return False
    upper_name = name.upper()
    if any(w in upper_name for w in _SKIP_NAME_WORDS):
        return False
    if "%" in name and any(h in upper_name for h in _DEBT_NAME_HINTS):
        return False
    if " NOTES DUE" in upper_name or " NOTE DUE" in upper_name:
        return False
    if " PFD " in upper_name or upper_name.endswith(" PFD") or " PREFERRED STOCK" in upper_name:
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


def fetch_nasdaq_symbols() -> list[dict[str, str]]:
    lines = _fetch_lines(NASDAQ_LISTED)
    symbols: list[dict[str, str]] = []
    for line in lines[1:]:
        if line.startswith("File Creation"):
            break
        parts = line.split("|")
        if len(parts) < 8:
            continue
        symbol, name, _market_cat, test_issue, _fin_status, _lot, etf, next_shares = parts[:8]
        if next_shares.upper() == "Y":
            continue
        if not _is_common_stock(symbol, name, etf=etf, test_issue=test_issue):
            continue
        symbols.append(
            {
                "symbol": symbol.strip().upper(),
                "name": name.strip(),
                "market": "US",
                "exchange": "NASDAQ",
            }
        )
    symbols.sort(key=lambda x: x["symbol"])
    return symbols


def build_universe(*, exchange: str = "NYSE") -> dict:
    exchange = exchange.upper()
    if exchange == "NYSE":
        entries = fetch_nyse_symbols()
        source = OTHER_LISTED
    elif exchange == "NASDAQ":
        entries = fetch_nasdaq_symbols()
        source = NASDAQ_LISTED
    else:
        raise ValueError(f"Supported exchanges: NYSE, NASDAQ (got {exchange})")
    return {
        "updated": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
        "exchange": exchange,
        "count": len(entries),
        "symbols": entries,
    }


def main() -> int:
    exchange = "NYSE"
    output: Path | None = None
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

    if output is None:
        output = DEFAULT_OUTPUTS.get(exchange.upper(), ROOT / "data" / "universe" / f"{exchange.lower()}.json")

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
