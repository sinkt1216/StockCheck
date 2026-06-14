---
name: stock-checklist
description: >-
  Build and evaluate a stock screening checklist by researching each required
  indicator or data item for free online sources vs custom implementation.
  Use when working on StockCheck, stock breakout monitoring, indicator
  sourcing, or when the user lists checklist items to explore.
---

# Stock Checklist

Systematically define screening requirements, research each item, and decide whether to use a free resource or build it yourself.

## Workflow

### 1. Capture the checklist

When the user lists required items, add them to [checklist.md](checklist.md) under **Items to explore**. Use their wording verbatim.

If the list is incomplete, ask what each item should measure and what timeframe/market it applies to before researching.

### 2. Explore one item at a time

Work through items in order unless the user prioritizes differently. For each item:

1. **Clarify** — What exactly should this indicator detect? Inputs, timeframe, thresholds?
2. **Search** — Look for free resources: APIs, libraries, screeners, formulas, public datasets.
3. **Evaluate** — Compare options on coverage, reliability, rate limits, licensing, and fit.
4. **Decide** — `Use free resource` or `Build custom`.
5. **Record** — Update the item's section in [checklist.md](checklist.md).

### 3. Research priorities

Prefer in this order:

1. **Python libraries** already suitable for the stack (e.g. `yfinance`, `pandas-ta`, `ta-lib`)
2. **Free APIs** with documented limits (Yahoo Finance, Alpha Vantage free tier, etc.)
3. **Published formulas** implementable from OHLCV data
4. **Build custom** when no reliable free source exists or logic is proprietary

Always verify whether a source is free for the intended use (commercial vs personal, redistribution, call volume).

### 4. Per-item report format

Use this template when documenting each explored item in `checklist.md`:

```markdown
### [Item name]

**Requirement:** [What it must detect or provide]

**Options found:**
| Source | Type | Cost | Pros | Cons |
|--------|------|------|------|------|
| ... | API / library / formula | Free / limited / paid | ... | ... |

**Decision:** Use free resource | Build custom

**Rationale:** [One or two sentences]

**Next step:** [Concrete action — e.g. spike in yfinance, implement RSI crossover]
```

### 5. After all items are explored

Summarize in chat:

- Count of items using free resources vs custom builds
- Shared dependencies to install once
- Recommended build order (data layer first, then indicators, then screening logic)

## Rules

- Do not skip research and assume an item must be built — search first.
- Do not recommend paid services unless the user asks; note them only as fallbacks.
- Keep `checklist.md` as the single source of truth; do not scatter findings across other files unless the user requests it.
- When building custom indicators, prefer simple, testable implementations over heavy abstractions.

## Additional resources

- Live checklist and findings: [checklist.md](checklist.md)
