# Validated regime patterns (SPY weekly)

Empirical findings from `2007-05-28 → 2009-08-24` and `2018-01-22 → 2020-04-20`. Thresholds are guides, not laws.

## Bear / correction START — typical cascade

```
MACD Hist fades → RSI < 50 + MACD bear cross → slope10 < 0 → slope20 < 0
  → spread 10-20 < 0 → slope50 < 0 → spread 20-50 < 0
```

| Episode | Depth | First formal warnings | Notes |
|---------|-------|----------------------|-------|
| Aug 2007 flare | −5.7% | RSI, slope10 | Spreads never broke |
| Oct07–Mar08 | −16% | RSI/MACD/slope10 **Aug 2007** (before Oct top) | spread 10–20 negative before Oct peak |
| Q4 2018 | −17% | RSI/MACD Oct 12; slope10 Oct 19 | spread 10–20 Nov 16 |
| 2022-style (ref) | — | Same order as Q4 2018 | — |
| COVID | −32% | RSI/MACD Feb 28; slope10 Mar 6 | Compressed to ~2–4 weeks |
| GFC crash leg Aug–Nov 08 | −38% | **None at Aug peak** — already in bear | Crash inside bear |
| Full GFC Oct07–Mar09 | −55% | Same as first leg from Aug 2007 | Mar 09 ultimate low |

## Trough indicator fingerprints (real bears)

| | slope10 | RSI | Hist | spread 10–20 |
|--|---------|-----|------|--------------|
| Q4 2018 | −1.10%/wk | 32 | −3.5 | −3.5% |
| COVID | −1.87%/wk | 22 | −9.1 | −1.3% |
| GFC Mar 2009 | −1.75%/wk | 28 | −0.2* | −3.4% |

\*MACD negative so long that Hist near zero at trough; turn was Hist rising from deep negative (Nov 08 – Jan 09).

## RECOVERY — typical cascade

```
Hist bottoms → MACD bull cross → slope10 > 0 → RSI > 50 → spread 10-20 > 0
```

| Trough | MACD cross | slope10 > 0 | RSI > 50 | spread 10–20 > 0 |
|--------|------------|-------------|----------|------------------|
| Q4 2018 Dec 21 | +6w | +7w | +6w | +10w |
| Mar 2009 | +2w | +5w | +9w | +10w |
| Mar 2008 | +4w | +4w | +5w | +9w |
| Nov 2008 | +6w | +11w | **not in 16w** | **not in 16w** |
| COVID Mar 20 | not by Apr 20 | not by Apr 20 | not by Apr 20 | spreads still worsening |

## Mild vs confirmed — quick filter

| | Mild (Aug 07, May 19, Feb 18) | Confirmed bear |
|--|--------------------------------|----------------|
| slope10 at trough | ≥ 0 | < −0.5%/wk |
| spread 10–20 at trough | > +2% | < 0 |
| RSI at trough | > 45 | < 35 |
| Hist at trough | > −1 | < −2 (or long negative then inflects) |

## Breadth confirmation (S&P 500, weekly)

From `scripts/breadth_regime_analysis.py` over the same two eras. **Caveat:** breadth is computed from today's constituent list, so pre-2010 levels are survivorship-biased and read too healthy — use the *timing* and the *relative* collapse, not the absolute percentages.

| Episode | Peak %>MA20 | Trough %>MA20 | Trough %>MA10 | Trough H/L (new lows) |
|---------|-------------|---------------|---------------|------------------------|
| Feb 2018 correction | 86% | 41% | 16% | 0.09 (44) |
| Q4 2018 bear | 76% | 12% | 6% | 0.00 (208) |
| May 2019 pullback | 86% | 48% | 30% | 1.02 (44) |
| COVID | 77% | 2% | 2% | 0.01 (377) |
| Aug 2007 flare | 62% | 30% | 27% | 0.87 (23) |
| Oct07–Mar08 | 76% | 18% | 29% | 0.09 (110) |
| Nov 2008 low | 47%\* | 2% | 4% | 0.00 (261) |
| Mar 2009 low | — | 10% | 6% | 0.01 (236) |

\*Aug 2008 "peak" already sat below 50% — a local peak inside a bear, matching the indicator script showing every signal already bearish there.

**Breadth confirms, it does not lead.** `% above MA20 < 50` fires the *same week* as the RSI < 50 / MACD bear cross in both clean cases (Q4 2018: all three on 2018-10-12, 3w after peak; COVID: all three on 2020-02-28, 2w after peak). Breadth adds depth, not earliness.

### Depth discriminator at the trough

| | Shallow dip | Confirmed bear |
|--|-------------|----------------|
| % above MA20 | > 40% | < 20% |
| % above MA10 | can still collapse (16–30%) | < 10% |
| New 52w lows | double digits (~40) | hundreds (208–377) |

The **MA10-vs-MA20 split** is the tell for a shallow dip: Feb 2018 and May 2019 both crushed short-term breadth (16%, 30% above MA10) while MA20 breadth held above 40%. In real bears both collapse together. Aug 2007 sat in between (30% / 27%) — a genuine warning that preceded the October top by months.

**H/L ratio alone is noisy**: Feb 2018 hit 0.09 at its trough, as bearish as Oct07–Mar08, yet it was a 2-week dip. The raw new-low *count* separates them (44 vs 110+).

### Breadth recovery timing

Shallow dips repair breadth almost immediately (`% > MA20` back above 50 within 0–1w of the trough); real bears take ~3–5w, and the worst legs do not repair inside 16 weeks (Nov 2008, and COVID as of 2020-04-20). Same ordering as the momentum-then-structure recovery cascade above.

## Multi-year bear caveats

1. Early warnings can precede the **absolute** high by months.
2. **Local peaks inside a bear** give no clean start signals.
3. **Bear-market rallies** can show MACD recovery without RSI > 50 or positive spreads (Nov 2008).
4. **Spread 10–20** is the slowest heal — momentum can recover weeks before structure.
