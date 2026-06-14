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

## Storage layers (project convention)

| Layer | Location | Stores | Example |
|-------|----------|--------|---------|
| **Decisions & research** | `checklist.md` (this file) | Which source, why, field mapping | DeanFi chosen for SPX A/D |
| **Agent workflow** | `SKILL.md` | How to explore items — not project-specific data | Per-item report template |
| **Runtime config** | `config/sources.yaml` (when code exists) | URLs, refresh interval, cache path | `breadth.url`, `refresh_minutes: 15` |
| **Live / cached data** | `data/breadth/`, `data/meanreversion/`, `data/trends/weekly/` | Fetched JSON snapshots | `daily_breadth.json`, weekly state per symbol |
| **Application code** | `src/` fetcher modules | Fetch, validate, expose metrics | `market_breadth.py`, `mean_reversion.py`, `weekly_trend_state.py` (planned), `trend_analysis.py` |

Do **not** store daily metric values (e.g. today's `advances: 394`) in checklist or skill files — those belong in `data/` or a database once the fetcher runs.
