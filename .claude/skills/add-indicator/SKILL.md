---
name: add-indicator
description: Add or modify a technical indicator (EMA, MACD, Force Index, Stochastic, Elder-Ray, Autoenvelope, etc.) in the backend indicator engine, with hand-computed reference-value tests and correct wiring into the signal engine. Use when asked to add a new indicator, change an indicator's parameters, or fix indicator math.
---

# Add Indicator

Backend indicator work follows `docs/architecture/Backend.md` §4 and the coverage discipline in `docs/architecture/Testing.md`. Read both before starting if this is the first time touching `app/indicators/`.

## Steps

1. **Check Analyse.md first.** `docs/Analyse.md` §4 (Indicator Summary Table) and §2 (Triple Screen) define which indicators exist, their exact parameters (e.g. EMA 13/26, Stochastic %K 5/%D 3/smooth 3, Force Index 2-EMA and 13-EMA), and their role. If the indicator or parameter set isn't in Analyse.md yet, that's a methodology decision — stop and confirm with the user before writing code, don't invent parameters.

2. **Implement as a pure function** in `app/indicators/<name>.py`: `DataFrame in -> Series/DataFrame out`, no I/O, no global state. Indicators are hand-written directly against `pandas` (`ewm`/`rolling`), not a TA library — `pandas-ta` was dropped (see `docs/architecture/Backend.md` §1) because its only installable release requires Python 3.12+ and its formulas don't always match Elder's book definitions anyway. Implement straight from the Analyse.md §4 definition, don't assume a generic TA-library formula (Force Index and Elder-Ray in particular are easy to get subtly wrong).

3. **Write the reference-value test first.** In `tests/unit/indicators/test_<name>.py`, construct a small fixed OHLCV series (5-20 bars), hand-compute (or independently verify, e.g. via spreadsheet) the expected output for at least 2-3 points, and assert against those exact values — not just shape/type. This is the bar Testing.md sets; a test that only checks "returns a Series of the right length" does not satisfy it even if coverage is green.

4. **Wire into the signal engine if applicable.** If the indicator feeds Screen 1 (tide), Screen 2 (wave), the Impulse gate, or the confidence breakdown, update `app/signals/` accordingly (`triple_screen.py`, `impulse.py`, or `confidence.py`), and add/adjust the corresponding case in the signal engine test suite (`tests/unit/signals/`) covering the new indicator's effect on signal/confidence output.

5. **Update docs if behavior changed.** If parameters or the indicator's role changed, update `docs/Analyse.md` §4 and, if it affects the API response shape, `docs/architecture/API.md`'s `indicators`/`confidence_breakdown` example.

6. **Record any judgment call.** If step 1 or step 2 required resolving something Analyse.md doesn't fully pin down (a rounding/edge-case choice, how to handle the warm-up period before an EMA has enough bars, a case where a library-style formula and Elder's book definition could both be read as "the" definition), append an entry to this task's `decisions` array in its `docs/tasks/<id>.json` file — `decision` (what you chose) and `rationale` (why, and what you rejected). Skip this step if nothing was actually ambiguous; don't manufacture a decision entry for a straightforward implementation.

7. **Run coverage before finishing.** Use the `check-coverage` skill (or `pytest --cov=app --cov-report=term-missing --cov-fail-under=90`) to confirm the new code doesn't drop the backend below 90%.

## Common Mistakes to Avoid

- Trusting a library default parameter without checking it against Elder's book definition.
- Testing only that the function runs, not that its output is numerically correct.
- Adding an indicator to `indicators/` without deciding whether/how it plugs into the signal engine — an indicator that exists but isn't wired in is dead code.
