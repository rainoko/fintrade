---
name: test-90
description: Actively write tests to close coverage gaps until backend and/or frontend reach the required 90% gate. Unlike check-coverage (which only reports status), this skill identifies specific uncovered logic and writes real tests for it. Use when asked to "get to 90%", "make coverage pass", "close coverage gaps", or after check-coverage reports a shortfall.
---

# Test to 90%

This skill *closes* coverage gaps; it does not lower the bar to close them. See `docs/architecture/Testing.md` for the gate definition and what it does and doesn't guarantee.

## Steps

1. **Get current status.** Run the commands from the `check-coverage` skill:
   - Backend: `pytest --cov=app --cov-report=term-missing --cov-fail-under=90`
   - Frontend: `vitest run --coverage`

   Use the `term-missing` / coverage report output to get the exact uncovered line/branch ranges per file — work from that list, don't guess at gaps.

2. **Prioritize by value, not by ease.** Untested logic in `app/signals/`, `app/indicators/`, `app/portfolio/risk.py`, and API error paths (404/422/503 cases in `docs/architecture/API.md`) matters far more than an untested getter. If multiple files are below threshold, close the highest-value gaps first even if a trivial file would be faster to finish.

3. **Write real tests for each gap, matching the standard already set:**
   - Indicator gaps → hand-computed reference-value assertions (`add-indicator` skill's testing step), not shape/type checks.
   - Signal engine gaps → explicit Screen 1/2/3 + Impulse combination scenarios (`verify-elder-signal` skill's checklist is a good source of scenarios to turn into tests).
   - API route gaps → the error cases API.md lists (unknown ticker, provider unavailable, insufficient history), asserting status code and `detail` shape.
   - Frontend component/hook gaps → error/empty/loading states via MSW-mocked responses, and confidence-band boundary values (0%, 100%, Low/Medium/High edges), not just the happy path.

4. **Don't fake the number.** Never add a test that calls code without asserting anything meaningful just to execute the line, and never delete or stub out real logic (error handling, edge-case branches) solely to make it easier to cover. If a line is genuinely unreachable dead code, delete the dead code — don't leave it and don't fake-cover it.

5. **Re-run and iterate** until both suites report ≥90%, re-checking `term-missing` output after each batch rather than assuming a fix worked.

6. **Report the before/after numbers per side** and list which files received new tests, so the change is auditable — not just "coverage now passes."

## Relationship to Other Skills

- `check-coverage` — read-only status check; run it first (or as step 1 here) to know what's missing.
- `add-indicator` / `add-api-endpoint` — when a coverage gap exists *because* a feature's tests were never written as part of adding it, those skills' testing steps are the reference for what a real test looks like here.
