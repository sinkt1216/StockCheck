# Stock Checklist

Track required screening items and research findings here.

## Items to explore

<!-- Add items below as the user lists them. One bullet per item. -->

-

## Explored items

### Market breadth (S&P 500)

**Requirement:** Daily S&P 500 constituent advance/decline counts and related breadth metrics (volume, 52-week highs/lows, % above MAs).

**Options found:**

| Source | Type | Cost | Pros | Cons |
|--------|------|------|------|------|
| DeanFi `daily_breadth.json` | Public JSON API | Free | No key, JSON, ~15 min updates, rich fields | Third-party dependency; S&P 500 only |
| StockCharts `!ADVSPX` / `!DECLSPX` | EOD indicator | Partial | Official index constituent counts | No free API; not on yfinance |
| Build custom (yfinance) | Self-computed | Free | Full control | Must maintain constituent list + rate limits |
| WSJ Markets Diary | Exchange A/D JSON | Free | Easy parse | Wrong universe (exchange, not SPX) |

**Decision:** Use free resource — DeanFi `daily_breadth.json`

**Rationale:** Already structured JSON with the exact SPX constituent A/D fields we need, updated during market hours, no auth. Same underlying approach as a custom yfinance build but maintained externally.

**Source URLs:**

- Primary (R2): `https://r2.deanfi.com/advance-decline/daily_breadth.json`
- Fallback (GitHub raw): `https://raw.githubusercontent.com/GibsonNeo/deanfi-data/main/advance-decline/daily_breadth.json`
- Repo: https://github.com/GibsonNeo/deanfi-data
- Related history: `advance-decline/ad_line_historical.json`, `ma_percentage_historical.json`

**Fields we consume** (from `data` object):

| Group | Fields | Use |
|-------|--------|-----|
| `advances_declines` | `advances`, `declines`, `unchanged`, `advance_decline_ratio`, `advance_percentage` | Core A/D monitoring |
| `volume_metrics` | `advancing_volume`, `declining_volume`, `volume_ratio`, `advancing_volume_pct` | Volume breadth confirmation |
| `new_highs_lows` | `stocks_near_52w_high`, `stocks_near_52w_low`, `high_low_ratio` | Participation extremes |
| `moving_averages` | `above_20_day_ma`, `above_50_day_ma`, `above_200_day_ma` (each: `count`, `percentage`) | Trend breadth |

**Next step:** ~~Add runtime config + fetcher~~ Done — `src/market_breadth.py`, cache under `data/breadth/`.

---

### Mean reversion (SPY / QQQ / IWM)

**Requirement:** Distance of major index ETFs from key moving averages and spread between MA pairs, with z-scores and overbought/oversold signals for mean-reversion context.

**Options found:**

| Source | Type | Cost | Pros | Cons |
|--------|------|------|------|------|
| DeanFi `meanreversion/*_snapshot.json` | Public JSON API | Free | SPY/QQQ/IWM, z-scores, signals, ~10 min updates | ETF proxies (not raw SPX/NDX index); third-party dependency |
| Build custom (yfinance) | Self-computed | Free | Full control, any symbol | Must replicate z-score logic and MA pairs |
| StockCharts `$SPXA200R` etc. | Breadth % above MA | Partial | Index-level breadth | Different metric (% constituents above MA, not ETF price distance) |

**Decision:** Use free resource — DeanFi mean reversion snapshots

**Rationale:** Complements market breadth: breadth shows *participation* (how many stocks are up); mean reversion shows *extension* (how far index ETFs are from MAs and whether spreads are stretched). Pre-computed z-scores and signal labels save custom work.

**Source URLs:**

- `ma_spreads_snapshot.json` — MA pair spreads (20/50, 20/200, 50/200)
  - R2: `https://r2.deanfi.com/meanreversion/ma_spreads_snapshot.json`
  - GitHub: `https://raw.githubusercontent.com/GibsonNeo/deanfi-data/main/meanreversion/ma_spreads_snapshot.json`
- `price_vs_ma_snapshot.json` — price distance from 20/50/200 MA
  - R2: `https://r2.deanfi.com/meanreversion/price_vs_ma_snapshot.json`
  - GitHub: `https://raw.githubusercontent.com/GibsonNeo/deanfi-data/main/meanreversion/price_vs_ma_snapshot.json`
- Historical: `ma_spreads_historical.json`, `price_vs_ma_historical.json` (same folder)

**Fields we consume** (per ETF in `indices`: SPY, QQQ, IWM):

| File | Group | Fields | Use |
|------|-------|--------|-----|
| `price_vs_ma_snapshot` | `metrics_by_ma` | `distance_percent`, `zscore`, `signal` per ma_20/50/200 | Overbought/oversold vs each MA |
| `price_vs_ma_snapshot` | top-level | `trend_alignment`, `current_price` | Overall trend context |
| `ma_spreads_snapshot` | `ma_pairs` | `spread_percent`, `zscore`, `signal`, `alignment` per pair | Stretched MA relationships |
| `ma_spreads_snapshot` | `moving_averages` | `ma_20`, `ma_50`, `ma_200` | Reference levels |

**Index mapping:** SPY → S&P 500, QQQ → Nasdaq-100, IWM → Russell 2000.

**Next step:** ~~Add runtime config + fetcher~~ Done — `src/mean_reversion.py`, cache under `data/meanreversion/`.

---

### Implied correlation (COR1M)

**Requirement:** Monitor Cboe 1-Month Implied Correlation Index — market expectation of average correlation among top 50 SPX names over ~1 month. High values = herd behavior / diversification breakdown; complements VIX and market breadth.

**Options found:**

| Source | Type | Cost | Pros | Cons |
|--------|------|------|------|------|
| Cboe Global Indices Feed | Licensed index feed | Paid | Official, real-time | Not free |
| Yahoo Finance `^COR1M` | Delayed EOD | Free | Known ticker | API returned almost no history in testing |
| Google Finance `COR1M:INDEXCBOE` | Delayed quote + chart RPC | Free | Quote + ~1yr daily history via `batchexecute` | Undocumented RPC; may break; delayed ~20 min |
| Investing.com | Web table | Free | Human-readable history | No sanctioned API |
| Build custom (options IV) | SPX + 50-stock options | Paid data | True implied correlation | Not practical for free stack |

**Decision:** Use free resource — Google Finance (`batchexecute` RPC)

**Rationale:** Verified programmatic pull: current COR1M level, change, previous close, and daily history (~249 points for 1Y window starting Jun 2025). No API key. Same delayed data shown on [Google Finance COR1M page](https://www.google.com/finance/quote/COR1M:INDEXCBOE). Yahoo/yfinance unreliable for this index.

**Source / method:**

- Symbol: `COR1M:INDEXCBOE`
- Quote RPC: `xh8wxf`
- Chart RPC: `AiCwsd` with window modes (`1D`=1, `1M`=3, `1Y`=6)
- Endpoint: `https://www.google.com/finance/_/GoogleFinanceUi/data/batchexecute`
- Requires `CONSENT=YES+` cookie for EU; quotes delayed per Google terms

**Fields we consume:**

| Field | Use |
|-------|-----|
| `quote.price`, `change`, `change_percent` | Current correlation risk level |
| `quote.previous_close` | Day-over-day context |
| `history[].date`, `history[].close` | Trend / regime (rising correlation into selloffs) |

**Validation (Jun 2026 spike):** price **10.74**, prev **13.18**, 1Y history **249** daily points from **2025-06-16** → **2026-06-12**.

**Next step:** ~~Add fetcher~~ Done — `src/implied_correlation.py`, cache under `data/correlation/cor1m.json`. Run: `python src/implied_correlation.py --window 1Y`.

**Related indices:** COR3M, COR6M, COR1Y (same Google Finance pattern, different symbol).

---

### Weekly trend state (10-week MA slope)

**Requirement:** Detect when an individual stock **starts** an overall weekly uptrend (regime change), not just a one-week bounce. Monitor any symbol in a watchlist or universe (e.g. S&P 500).

**Options found:**

| Source | Type | Cost | Pros | Cons |
|--------|------|------|------|------|
| Build custom (yfinance) | Weekly bars + MA slope | Free | Any symbol; full control of state logic | Must maintain weekly pipeline |
| DeanFi mean reversion | Daily ETF extension | Free | Z-scores, SPY/QQQ/IWM | Daily timeframe; extension not trend *start*; ETFs only |
| 1-week MA10 delta only | Trivial calc | Free | Simple | Too noisy; confuses pulse vs trend (rejected) |

**Decision:** Build custom — weekly trend state machine (yfinance)

**Rationale:** No free API publishes “uptrend start” per stock. A single week’s MA change (`MA10[w] - MA10[w-1]`) only measures a pulse. Overall uptrend requires **multi-week slope**, **weekly structure**, and **MA alignment**, combined in a **state machine** that fires on regime change (not every positive week). Complements daily mean reversion (extension) and market breadth (participation).

**Methodology:**

| Step | Rule |
|------|------|
| Weekly bars | Adjusted close, resample `W-FRI` (week-ending Friday) |
| Averages | MA10 and MA20 on weekly closes |
| Primary slope | 4-week **linear regression** on MA10 → `% per week` (`slope_4w_pct`) |
| Reference slope | 1-week MA10 change (`slope_1w_pct`) — context only, not primary signal |
| Structure | `higher_low`: close > prior 8-week rolling low; `breakout_12w`: close > prior 12-week high |
| Alignment | `ma_stack`: close > MA10 > MA20 |

**Trend states:**

| State | Condition (summary) |
|-------|---------------------|
| `DOWNTREND` | `slope_4w_pct < -0.15` |
| `BASE` | `\|slope_4w_pct\| <= 0.15` (flat / chop) |
| `EARLY_UP` | `slope_4w_pct > 0.15` (rising, not yet fully confirmed) |
| `CONFIRMED_UP` | `EARLY_UP` + `ma_stack` + `breakout_12w` |
| `MATURE_UP` | `slope_4w_pct > 1.0` + `ma_stack` (established trend) |

**Alert signals (fire once on state change):**

| Signal | Rule |
|--------|------|
| `early_turn` | `slope_4w_pct` crosses above `+0.15` from `<= +0.15` |
| `confirmed_turn` | `early_turn` + `ma_stack` + `higher_low` |
| Monitor target | `BASE` or `DOWNTREND` → `EARLY_UP` (new uptrend start) |

**Default thresholds** (tunable in config): `slope_turn = 0.15`, `slope_mature = 1.0`, regression window = 4 weeks.

**Output fields per symbol per week:**

| Field | Use |
|-------|-----|
| `week_end`, `close`, `ma10`, `ma20` | Price context |
| `slope_1w_pct`, `slope_4w_pct` | Slope diagnostics |
| `higher_low`, `ma_stack`, `breakout_12w` | Structure / confirmation flags |
| `early_turn`, `confirmed_turn` | Event flags |
| `state` | Current regime |

**Validation case study — GOOG (Jan–Mar 2026):**

| Week FRI | Close | slope_4w | State | Note |
|----------|-------|----------|-------|------|
| 2026-01-23 | 328 | +1.58%/wk | MATURE_UP | Already in uptrend |
| 2026-01-30 | 338 | +1.48%/wk | MATURE_UP | 12w breakout (local peak) |
| 2026-02-13 | 306 | +0.26%/wk | EARLY_UP | Lost MA stack |
| 2026-02-20 | 314 | -0.13%/wk | BASE | Trend stalling |
| 2026-03-13 | 301 | -0.31%/wk | DOWNTREND | Regime shift down |
| 2026-03-27 | 274 | -1.07%/wk | DOWNTREND | Accelerating decline |

Demonstrates why 1-week slope alone misleads: Jan had high 1w/4w slopes (mature), Mar had persistent negative 4w slope (downtrend) before large weekly drops.

**Related code:** `src/trend_analysis.py` — daily DeanFi-style extension/z-score for any symbol (different timeframe and purpose).

**Next step:** Implement `src/weekly_trend_state.py` + `config/sources.yaml` section (`weekly_trend`: thresholds, universe); cache under `data/trends/weekly/`. Support `--symbol`, `--as-of`, and `--scan` with state-change alerts only.

---

### Long-term multiple-top breakout (weekly) — standalone only

**Status:** Removed from `weekly_scan.py` and `weekly_backtest.py`. Use `python src/multi_top_breakout.py` for optional research only. Scan/backtest use the **buy** rule (slope + volume spike).

**Requirement:** Detect when a stock breaks a **long-term horizontal resistance** formed by **multiple weekly tops** over years (the “green line” on a weekly chart), signaling escape from a multi-year base and the potential start of a new uptrend. Used together with **Weekly trend state (10-week MA slope)** — structural break is the primary event; weekly MA slope confirms regime change.

**Reference pattern:** MU — multi-year ceiling (~164 area on weekly chart), multiple failed highs, then weekly breakout into sustained uptrend. User will supply ticker + timeframe for backtest validation.

**Options found:**

| Source | Type | Cost | Pros | Cons |
|--------|------|------|------|------|
| DeanFi support/resistance | Daily pivot JSON | Free | SPY/QQQ/IWM pivots | Prior-session pivots; wrong horizon for multi-year ceiling |
| StockCharts horizontal S/R | Chart tool | Partial | Visual multi-touch lines | No free API; manual per symbol |
| 52-week high breakout | Simple rule | Free | Easy to compute | Not the same — ignores years of repeated tops at one level |
| Build custom (yfinance) | Weekly swing-high clustering | Free | Any symbol; tunable touch count / span | Must define clustering logic; no external validation feed |

**Decision:** Build custom — weekly multi-top resistance + breakout detection (yfinance)

**Rationale:** No free API publishes “multi-year multiple-top resistance” per stock. DeanFi pivots are daily and index-focused. The pattern requires **clustering weekly swing highs** over a long lookback, then detecting **weekly close** above that level. Complements (does not replace) weekly MA slope: breakout = structure; slope = trend confirmation.

**Methodology:**

| Step | Rule |
|------|------|
| Weekly bars | Adjusted OHLC, resample `W-FRI` (week-ending Friday) |
| Lookback | Default **3 years** (~156 weeks); tunable 2–5 years for backtest |
| Swing high | Week `t` is a swing high if `high[t]` > max(`high[t-1..t-N]`, `high[t+1..t+N]`); default `N = 3` |
| Touch cluster | Group swing highs within **±2.5%** of each other (`touch_tolerance_pct`) |
| Valid resistance | Cluster has **≥ 3 touches** (`min_touches`), span **≥ 52 weeks** (`min_span_weeks`) between first and last touch |
| Resistance level | **Max** touch in cluster (conservative ceiling) — alternative: median (document if changed) |
| Base quality (optional) | ≥ 60% of lookback weeks closed **below** resistance; last touch ≥ 8 weeks before eval week |
| Breakout | **Weekly close** > `resistance × (1 + breakout_buffer_pct)`; default buffer **1.0%** (not intraday wick) |
| Breakout freshness | First break within last **8 weeks** (`breakout_freshness_weeks`) for “new break” screens |
| Hold rule (strict) | 1 close above (default) or 2 consecutive weekly closes above (`hold_weeks = 2`) |
| Prior context | Prior 4–8 weeks mostly closed below resistance (not already extended far above) |

**Default thresholds** (tunable in `config/sources.yaml` → `multi_top_breakout`):

| Parameter | Default | Notes |
|-----------|---------|-------|
| `lookback_years` | 3 | Extend to 5 for very long bases (MU-style) |
| `swing_lookback_weeks` | 3 | Local peak definition |
| `touch_tolerance_pct` | 2.5 | Same “top” band |
| `min_touches` | 3 | Double/triple top minimum |
| `min_span_weeks` | 52 | Tops must span ≥ 1 year |
| `breakout_buffer_pct` | 1.0 | Reduce false breaks |
| `breakout_freshness_weeks` | 8 | “Just broke” window |
| `hold_weeks` | 1 | Consecutive closes above |
| `min_weeks_since_last_touch` | 8 | Avoid chop-at-line false positives |
| `base_below_resistance_pct` | 60 | % of lookback weeks close < resistance |

**Screen stages** (single symbol or scan):

| Stage | Resistance rule | Weekly MA slope (see above section) |
|-------|-----------------|-------------------------------------|
| `WATCH` | Price within 0–5% **below** resistance; valid cluster exists | `BASE` or flattening; `\|slope_4w_pct\| ≤ 0.15` |
| `BREAK` | Fresh weekly close above resistance + buffer | `early_turn` or `slope_4w_pct > 0.15` within 0–2 weeks of break |
| `CONFIRMED` | Break within last 4–12 weeks; still above resistance | `CONFIRMED_UP`: `ma_stack` + `breakout_12w` + `slope_4w_pct > 0.15` |
| `EXTENDED` | Break > 12 weeks ago or > 25% above resistance | `MATURE_UP` or `slope_4w_pct > 1.0` — trend mature; chase risk |

**Combined pass rule** (default for “green line + uptrend start”):

```
multi_top.breakout_fresh == true
AND weekly_close > resistance × (1 + breakout_buffer_pct)
AND (early_turn OR slope_4w_pct > 0.15)
AND close > weekly_MA10
```

Optional tighten: require `ma_stack` within 2 weeks of break. Optional loosen: `BREAK` stage only (no slope on exact break week).

**Output fields per symbol per eval week:**

| Field | Use |
|-------|-----|
| `week_end`, `close`, `high` | Price context |
| `resistance_level`, `touch_count`, `touch_dates`, `span_weeks` | Cluster identity (“green line”) |
| `pct_below_resistance`, `weeks_since_last_touch` | Pre-break / watchlist context |
| `breakout`, `breakout_week`, `weeks_since_break`, `pct_above_resistance` | Break event |
| `hold_ok` | Meets `hold_weeks` rule |
| `stage` | `WATCH` / `BREAK` / `CONFIRMED` / `EXTENDED` / `NONE` |
| `weekly_trend.state`, `slope_4w_pct`, `early_turn`, `ma_stack` | Joined from weekly trend state (same week) |
| `combined_signal` | `watch` / `break` / `confirmed` / `extended` / null — `watch` when `WATCH` stage + (rising slope **or** `volume_spike`) |

**What this is not:**

- Not 52-week high breakout alone
- Not DeanFi daily pivot P/R1/S1
- Not daily 200 MA extension (`src/trend_analysis.py`)

**Validation:** Pending — user will provide **ticker** and **timeframe** to backtest both this indicator and weekly MA slope on the same bars.

**Related code:** `src/weekly_trend_state.py` (planned); `src/multi_top_breakout.py` (planned).

**Next step:** Implement `src/multi_top_breakout.py` + `config/sources.yaml` section (`multi_top_breakout`: thresholds); cache under `data/breakouts/multi_top/`. CLI: `--symbol`, `--as-of`, `--lookback-years`. Then backtest vs user-supplied ticker/timeframe alongside weekly trend state.

---

### NYSE universe (common equity scan)

**Requirement:** Weekly scan universe should be **common equity only** — no ETFs, exchange-traded debt (baby bonds), preferreds, warrants, units, or rights. ADRs of ordinary/common shares are **included** (e.g. BABA, BHP).

**Source:** Nasdaq Trader `otherlisted.txt` (NYSE exchange code `N`), filtered by `src/build_universe.py` → `data/universe/nyse.json`.

**Excluded by name/symbol rules:**

| Category | How detected | Examples |
|----------|--------------|----------|
| ETFs / test issues | `ETF` flag, `TEST` flag, name contains `ETF` / `ETN` / `FUND` | — |
| Exchange-traded debt | `%` coupon + `Notes` / `Debenture` / `Subordinated`, or `Notes due` | HCXY (Hercules 6.25% Notes 2033), SAJ |
| Preferred | `Preferred`, `Pfd`, `PREF.`, `PFD.` in name | BNS (Scotia Pfd series) |
| Warrants / units / rights | Name contains `Warrant`, `Unit`, `Right` | — |
| Structured receipts | `Depositary Shares of` (debt/preferred), `Receipt` | — |

**Not excluded:** ADRs (`American Depositary Shares` representing common stock), REIT common shares, dual-class common (symbol quirks like `BRK.B` may still fail on Yahoo).

**Commands:**

```bash
python src/build_universe.py                    # NYSE → nyse.json
python src/build_universe.py --exchange NASDAQ  # Nasdaq → nasdaq.json
python src/weekly_scan.py                       # full scan (~20 min NYSE)
python src/weekly_scan.py --universe data/universe/nasdaq.json
python src/weekly_scan.py --enrich-volume data/scans/YYYY-MM-DD_nasdaq.json
python src/weekly_scan.py --enrich-weekly-volume data/scans/YYYY-MM-DD_nasdaq.json
python src/weekly_scan.py --refilter data/scans/YYYY-MM-DD.json   # re-apply hit rules + universe filter without re-fetching
```

**Hit file filters** (`*_hits.json`) — `combined_signal: buy` only:

| Rule | Detail |
|------|--------|
| `price_above_ma10_ma20` | `close > MA10 > MA20` |
| `slope_1w_pct` | > 0 |
| `slope_4w_pct` | > 0 |
| Slope acceleration | `slope_4w_delta > 0` OR `slope_1w_delta > 0` |
| `volume_spike` | Weekly volume > 20-week MA |
| `avg_volume_50d` | > 300,000 |

**Reference only** (on each scan row, not required for buy): `golden_cross`, `golden_cross_recent`, `ma10_above_ma20`.

Multi-top resistance is **not** used in scan or backtest hits (standalone CLI only).

```bash
python src/weekly_scan.py --refilter data/scans/YYYY-MM-DD_nasdaq.json
```

---

### Liquidity (50-day average volume)

**Requirement:** Screen only names with enough daily liquidity — **50-day average volume > 300,000 shares**.

**Source:** yfinance daily bars (`period=4mo`, mean of last 50 trading sessions) → field `avg_volume_50d` on each scan row.

**Config:** `config/sources.yaml` → `liquidity.min_avg_volume_50d: 300000`

**Hit rule:** Rows missing volume data or below threshold are excluded from `*_hits.json` (full scan JSON keeps all rows with volume annotated).

**Commands:**

```bash
python src/weekly_scan.py --enrich-volume data/scans/2026-06-21_nasdaq.json   # backfill volume + re-filter hits
```

New full scans fetch volume per symbol automatically.

---

### Volume spike (weekly watch signal)

**Requirement:** `combined_signal = watch` when price is near resistance (`mt_stage == WATCH`) **and** either:
- `slope_4w_pct > 0` **and** `slope_4w_delta > 0` (rising slope), **or**
- **Weekly volume spike:** current week volume **>** 20-week moving average of weekly volume

**Fields:** `weekly_volume`, `volume_ma20`, `volume_spike` (bool) on each scan row.

**Config:** `config/sources.yaml` → `weekly_scan.volume_ma_weeks: 20`

**Note:** `--refilter` applies spike logic only if `volume_spike` is already on rows (from a full scan). Re-scan or backtest for fresh weekly volume.

---

## Storage layers (project convention)

| Layer | Location | Stores | Example |
|-------|----------|--------|---------|
| **Decisions & research** | `checklist.md` (this file) | Which source, why, field mapping | DeanFi chosen for SPX A/D |
| **Agent workflow** | `SKILL.md` | How to explore items — not project-specific data | Per-item report template |
| **Runtime config** | `config/sources.yaml` (when code exists) | URLs, refresh interval, cache path | `breadth.url`, `refresh_minutes: 15` |
| **Live / cached data** | `data/breadth/`, `data/meanreversion/`, `data/correlation/`, `data/trends/weekly/`, `data/breakouts/multi_top/`, `data/universe/`, `data/scans/` | Fetched JSON snapshots | `daily_breadth.json`, `cor1m.json`, `nyse.json`, `YYYY-MM-DD_hits.json` |
| **Application code** | `src/` fetcher modules | Fetch, validate, expose metrics | `build_universe.py`, `weekly_scan.py`, `weekly_trend_state.py`, `multi_top_breakout.py`, `market_breadth.py`, `mean_reversion.py`, `implied_correlation.py`, `trend_analysis.py` |

Do **not** store daily metric values (e.g. today's `advances: 394`) in checklist or skill files — those belong in `data/` or a database once the fetcher runs.
