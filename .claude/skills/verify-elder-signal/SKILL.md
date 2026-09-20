---
name: verify-elder-signal
description: Review signal-engine, indicator, or confidence-scoring code against the Elder Triple Screen methodology defined in docs/Analyse.md, to catch drift between the documented rules and the implementation. Use when asked to review, audit, or sanity-check the signal/confidence logic, or before merging a change that touches app/signals/ or app/portfolio/.
---

# Verify Elder Signal

`docs/Analyse.md` is the methodology source of truth. Code in `app/signals/` and `app/portfolio/` (per `docs/architecture/Backend.md`) must implement it faithfully — this skill is a checklist for catching cases where the code has quietly diverged from the doc (or vice versa: the doc is stale relative to a deliberate code change that was never written back).

## Checklist

Read `docs/Analyse.md` and the code under review side by side, and confirm:

### Screen 1 — Tide (§2/§3)
- Tide is the **weekly Impulse System color** (`app.signals.impulse.evaluate_impulse` run on
  `weekly_ohlcv`, mapped GREEN→BULLISH / RED→BEARISH / BLUE→NEUTRAL), per Elder ch. 39
  (`backend-weekly-impulse-screen1`, docs/ideas.md) — **not** a standalone weekly-MACD-
  Histogram-slope-plus-13/26-week-EMA test; that was the *original*, now-superseded version of
  Triple Screen. If you find code computing Tide from an EMA(13)-vs-EMA(26) level comparison
  instead of weekly Impulse, that's the bug (a regression back to the pre-correction
  methodology), not the doc being wrong.
- `weekly_macd_histogram_slope` may still be exposed alongside `trend` as informational
  context (it's still a real, useful read of weekly momentum) but must not be what decides
  `trend` — confirm it's genuinely no longer load-bearing for the trend decision itself.
- Tide outputs exactly `BULLISH | BEARISH | NEUTRAL` — no silent default to one of these on
  missing/ambiguous data.

### Screen 2 — Wave (§2)
- Oscillator direction is evaluated **against** the tide (oversold dip during bullish tide, overbought rally during bearish tide) — not oscillator extremes in isolation.
- Force Index uses both the 2-EMA (entry timing) and 13-EMA (trend confirmation) per §2/§4 — not just one.

### Screen 3 — Trigger (§2)
- Trigger logic matches the documented approximation (close crosses prior day's high/low) unless intraday data is in use, in which case confirm the doc was updated to reflect that (§9 flags this as an open decision — check it's still open, not silently resolved one way in code without a doc update).

### Impulse Gate (§3)
- Green/Red/Blue is computed from EMA(13) direction **and** MACD-Histogram direction together, not either alone.
- The gate actually blocks/downgrades signals as specified (Red blocks fresh BUY, Green blocks fresh SELL) — check this is enforced before a signal is emitted, not just computed and ignored.
- This app computes Impulse on **two independent timeframes** (§3, ch. 39/40): the **weekly**
  color drives Screen 1/Tide (see above), and a separate **daily** color is the fresh-entry
  gate `_determine_signal` enforces. Confirm the two are genuinely decoupled — a change to one
  timeframe's computation shouldn't silently affect the other (e.g. both should share the same
  `evaluate_impulse` function, called once per timeframe with that timeframe's own OHLCV, not a
  single call whose result gets reused for both purposes).

### Confidence Score (§6)
- Weights match: tide 30%, impulse gate 20%, oscillator extremity 25%, Elder-Ray confirmation 15%, volume confirmation 10% — sum to 100%.
- Each component score is genuinely derived from indicator values (e.g. oscillator extremity scaled by how deep into oversold/overbought territory), not a placeholder constant.
- The API response includes the `confidence_breakdown` per-component detail (`docs/architecture/API.md`), not just the final number — losing this makes the score unauditable.

### Portfolio Risk Overlay (§7)
- 2% rule and 6% rule are computed off **current** equity and **current** position risk, not values frozen at entry time.
- Existing-position exit flags are evaluated independently of the fresh-entry signal logic — a HOLD signal must not suppress a stop-hit or 6%-rule-breach exit flag.
- Protective stop = swing low − volatility buffer, not a fixed percentage stop (unless a documented deviation was made).

## If a Mismatch Is Found

- If the **code** diverges from Analyse.md without a documented reason: flag it as a bug, fix the code (or raise it to the user if the divergence looks intentional but undocumented).
- If the **doc** is stale relative to a deliberate, reasoned code change: update `docs/Analyse.md` in the same change rather than leaving the two out of sync — don't fix one side silently while leaving the other wrong.
- Before calling a divergence "deliberate," check the corresponding task's `decisions` array in `docs/tasks/<id>.json` (see `CLAUDE.md`'s Decision memory section). A deliberate choice with no `decisions` entry is itself a gap — the code may be right, but the reasoning is undocumented and unreviewable by the next person. Ask for it to be recorded rather than assuming it's fine.

## Recording a decision (when used during implementation, not just review)

Several checklist items in `docs/tasks/` explicitly can't be resolved from Analyse.md alone — e.g. `indicator-autoenvelope`'s envelope-width formula, or `screen3-trigger`'s intraday-vs-EOD approximation. If you're using this skill's checklist to *implement* one of these rather than only review it, append an entry to that task's `decisions` array (`decision` + `rationale`) once you resolve the ambiguity. Don't leave the resolution implicit in the code for a future reviewer to reverse-engineer.

## Output

Report findings as: which section of Analyse.md, what the doc says, what the code does, and whether it's a bug or a doc-staleness issue. Don't just say "looks fine" without walking the checklist above explicitly.
