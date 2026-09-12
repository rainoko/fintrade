---
name: check-coverage
description: Run backend (pytest-cov) and frontend (vitest --coverage) test suites together and report both against the project's 90% coverage gate, flagging which files fall short. Use when asked to check coverage, verify the 90% gate, or before finishing a change that touches backend or frontend code.
---

# Check Coverage

The project requires 90% line/branch coverage on both backend and frontend as a hard CI gate — see `docs/architecture/Testing.md`. This skill runs both suites and reports status; it does not lower the bar or waive it.

## Steps

1. **Backend.** From the backend project root:
   ```
   pytest --cov=app --cov-report=term-missing --cov-fail-under=90
   ```
   If it fails under 90%, the `term-missing` output lists uncovered line ranges per file — use that to target new tests, not to pad coverage with trivial assertions.

2. **Frontend.** From the frontend project root:
   ```
   vitest run --coverage
   ```
   Thresholds (90% lines/branches/functions/statements) are enforced via `vite.config.ts` per `docs/architecture/Testing.md`; a run below threshold exits non-zero.

3. **Report status for both sides explicitly** — don't report only the one that was touched. A change scoped to the backend can still be checked against the frontend's last-known coverage state if nothing there changed, but say so rather than omitting it silently.

4. **If either is below 90%:** identify the uncovered lines, and check whether they're genuinely untested logic or dead/unreachable code that should be removed instead. Don't write a test whose only purpose is to execute the line without asserting anything meaningful — `docs/architecture/Testing.md`'s "What 90% Coverage Does Not Guarantee" section explicitly flags shallow assertions as not meeting the bar in spirit even when the number is green.

5. **If both are ≥90%:** report the actual numbers achieved, not just "passed" — makes regressions easier to spot over time.

## Notes

- No test in either suite should require live network access (per Testing.md) — if coverage runs are flaky or slow due to real HTTP calls, that's a bug in the test setup (a provider/API call not mocked), not a coverage tooling issue. Fix the mock, don't skip the test.
- Exact commands assume `backend/` and `frontend/` as the project roots per `docs/architecture/Backend.md` and `docs/architecture/Frontend.md`'s module layouts — adjust paths if the scaffold differs once code exists.
