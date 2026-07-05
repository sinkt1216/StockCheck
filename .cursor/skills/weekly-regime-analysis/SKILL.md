---
name: weekly-regime-analysis
description: >-
  Analyze equity regime changes (bear market, correction, bull resumption) using
  weekly MA10/20/50 slopes, MA spreads, MACD, and RSI on SPY or other symbols.
  Use when backtesting a date range, comparing indicator sensitivity, diagnosing
  how a bear or correction started or ended, or when the user asks about MACD,
  RSI, MA slope/spread regime signals. Independent of weekly_trend_state /
  stock-checklist trend state machine unless the user explicitly asks for that.
---

# Weekly Regime Analysis

Standalone weekly-bar regime study: **MA slopes**, **MA spreads**, **MACD**, **RSI**. Do not use `weekly_trend_state.py` or `weekly_backtest.py` state machine unless the user requests it.

## Run the analysis

```bash
python scripts/spy_indicator_regime.py --from YYYY-MM-DD --to YYYY-MM-DD [--period 2018-2020|2007-2009]
```

- Default symbol: **SPY** (extend script if user needs another ticker).
- Save output: `data/backtests/{SYMBOL}_indicator_regime_{from}_{to}.txt`
- `--period` selects preset episode definitions for timing tables; add new presets in the script when validating new eras.

Always **run the script** for the user's date range; do not guess indicator values.

## Indicator definitions (weekly W-FRI close)

| Column | Meaning |
|--------|---------|
| **slp10 / slp20 / slp50** | 4-week linear regression slope of MA10/20/50, normalized as **%/week** |
| **10-20 / 20-50 / 10-50** | `(short MA − long MA) / long MA × 100` |
| **RSI** | RSI(14) on weekly close |
| **MACD / Sig / Hist** | MACD(12/26/9); **Hist = MACD − Sig** |
| **dd26w** | Drawdown from 26-week high (%) |

## Sensitivity ranking (validated 2007–2009, 2018–2020)

**Fastest → slowest** for direction changes:

1. **MACD Hist** (weakens before cross; often earliest heads-up)
2. **RSI** crossing **50** (below = risk-off, above = risk-on)
3. **MACD line vs Sig** bear/bull cross
4. **slope10** → **slope20** → **slope50**
5. **spread 10–20** → **spread 20–50** (structure; slowest to break and heal)

## Checklists

### Early warning (raise alert) — 2+ of:

- RSI breaks below **50**
- MACD crosses below signal; Hist turns negative and expands
- Hist positive but **shrinking** for 2+ weeks near a high
- slope10 turns negative while slope20 still positive
- spread 10–20 compressing toward 0% from a wide positive base (+2% to +5%)

### Confirmed bear (not a shallow dip) — 3+ of:

- slope10 **< −0.5%/wk** sustained
- spread **10–20 < 0%**
- RSI **< 40**
- MACD Hist **< −2** and expanding
- slope20 also negative

### Shallow correction only — if:

- slope10 stays positive through the dip
- spread 10–20 stays **> +2%**
- RSI does not break below **45**
- MACD Hist does not go below **−1**

### Recovery sequence (typical order)

1. Hist stops expanding negative / turns up (often weeks before RSI > 50)
2. **MACD bullish cross** (line > signal)
3. **slope10 > 0**
4. **RSI > 50**
5. **spread 10–20 > 0** (structure repaired — last)

In long bears, **local rally peaks** may show no fresh warnings (all indicators already bearish). **Warnings can fire months before the absolute price high** (e.g. Aug 2007 before Oct 2007 top).

## Workflow

1. Confirm symbol, `--from`, `--to`, and whether user wants full weekly table or episode summary only.
2. Run `scripts/spy_indicator_regime.py`; read output file.
3. Identify drawdown episodes in range (user may name peaks/troughs; otherwise use dd26w local extremes).
4. For each episode, report:
   - Peak / trough week with key indicator values
   - **START** signals with **weeks after peak**
   - **RECOVERY** signals with **weeks after trough**
   - Sensitivity order for that episode
5. Compare to checklists above; note shallow vs confirmed bear.
6. Present full weekly table on request (split by year if long).

## Report template

```markdown
## [SYMBOL] regime analysis — [from] to [to]

### Summary
[1–2 sentences: main episodes, whether checklists held]

### Episode: [name] (drawdown X%)
**Peak [date]:** close, slp10/20/50, spreads, RSI, Hist
**Trough [date]:** ...

**Bear / correction start (order):**
| Signal | Date | Weeks after peak |
...

**Recovery (order):**
| Signal | Date | Weeks after trough |
...

### Checklist fit
- Early warning: [met / partial / no]
- Confirmed bear: [yes / no — why]
- Recovery stage as of [end date]: [momentum / trend / structure]

### vs prior eras
[1–3 bullets vs patterns in patterns.md]
```

## Rules

- Prefer **weekly** bars for this skill; do not mix with daily RSI/MACD unless user asks.
- Hist sensitivity ≠ reliability: early signals whipsaw in mild pullbacks (May 2019, Aug 2007).
- spread 10–20 can be negative **at a nominal price high** after prior damage (Oct 2007).
- Do not store live scan counts in this skill; outputs live in `data/backtests/`.

## Additional resources

- Validated cross-era patterns: [patterns.md](patterns.md)
- Script: [scripts/spy_indicator_regime.py](../../../scripts/spy_indicator_regime.py)
