---
name: static-verify
description: Run backend (ruff + mypy) and frontend (eslint + tsc) static analysis, plus the repo-wide profit-target stale-wording guard, together and report pass/fail with every finding grouped by file, distinguishing style/lint issues from real type errors. Use when asked to run static analysis/linting, before finishing a change that touches backend or frontend code, or as the "run static analysis / linting" step of a PR review or task QA pass.
---

# Static Verify

Backend and frontend each have their own configured lint + type-check tooling — this
skill runs both sides' tools and reports one consistent pass/fail summary. It does not
lower any bar or silence a finding on your behalf; a real finding gets fixed in the
code, or (per `CLAUDE.md`'s decision-memory rule) explicitly recorded as a deliberate,
justified exception in the relevant tool config, never just suppressed inline without
explanation.

## Steps

1. **Backend lint.** From `backend/` (`backend/.venv/bin/ruff`, or `source
   backend/.venv/bin/activate && ruff` in the same call — see `CLAUDE.md`'s backend
   environment notes; `pip install -e ".[dev]"` first if `ruff`/`mypy` aren't installed
   yet):
   ```
   ruff check .
   ```
   Findings here are lint/style issues (import order, unused imports, FastAPI-unsafe
   default-argument patterns, simplifiable conditionals, etc.) per `[tool.ruff]` in
   `backend/pyproject.toml`. Deliberately not narrowed to `app/`: unlike `[tool.mypy]`
   (which scopes to `files = ["app"]` below, for the reasons in step 2), `[tool.ruff]`
   has no such scoping and applies repo-wide (only `app/db/migrations/versions`
   excluded) — running the narrower `app/`-only command let real, auto-fixable findings
   in `tests/` go unnoticed by this skill's own gate across several review rounds until
   `backend-static-verify-cleanup` cleared them by hand; see that task's `decisions`.

2. **Backend type check.** Same environment:
   ```
   mypy
   ```
   (Config is `[tool.mypy]` in `backend/pyproject.toml`; it already scopes to `files =
   ["app"]`, so no extra path argument is needed.) Findings here are real type errors —
   treat these as more severe than ruff's lint findings, per the "distinguishing
   style/lint issues from real type errors" framing below.

3. **Frontend lint.** From `frontend/`:
   ```
   yarn lint
   ```
   (Runs `eslint .` per `frontend/package.json`'s `lint` script and `eslint.config.js`.)

4. **Frontend type check.** From `frontend/`:
   ```
   yarn tsc -b --noEmit
   ```
   Project-references build (`tsconfig.app.json` + `tsconfig.node.json`, both `strict:
   true`) — catches type errors across `src/`, `tests/`, and `.storybook/`.

5. **Profit-target stale-wording guard.** From the repo root (no venv/install needed —
   stdlib-only, same as `scripts/validate_tasks.py`):
   ```
   python3 scripts/check_profit_target_wording.py
   ```
   Guards against `suggest_profit_target`'s channel-source description silently
   reverting to the pre-fix wording describing the channel as sourced from the
   *current day's* data with a ~100-*day* warm-up, instead of the correct *weekly*
   chart with a ~100-*week* warm-up, in any of `backend/`, `frontend/src/`, or `docs/`
   — a bug class that recurred across 6 separate files/locations over 2 review rounds of PR #222
   (`backend-profit-target-weekly-channel`) precisely because nothing but a human
   re-grepping the whole repo by hand ever caught it. See
   `docs/tasks/backend-profit-target-weekly-channel-followups.json` and the script's
   own module docstring for the full rationale, including why `docs/tasks/` and
   `docs/ideas.md` are deliberately excluded. Non-zero exit + a per-location message
   list means a real finding — treat it the same as a lint finding below, not a
   separate category.

6. **Report one combined result**, even if only one side was touched by the change
   under review — say explicitly if a side was skipped and why (e.g. "frontend
   unchanged, last known state: clean"), don't just omit it silently. For each side,
   group findings by file, and within each side separate:
   - **Type errors** (mypy, tsc) — a real type mismatch is a correctness signal, not a
     style nit; treat as blocking in a review context unless there's a recorded reason
     it's a deliberate boundary-narrowing/widening (see `backend/app/api/routers/
     stocks.py`'s `cast(Screens, ...)` / `cast(Indicators, ...)` for a worked example
     and `docs/tasks/skill-static-verify.json`'s `decisions` for the rationale).
     Migration-generated code (`app/db/migrations/versions/`) is excluded from both
     ruff and mypy by config, not manually filtered here.
   - **Lint/style findings** (ruff, eslint) — usually non-blocking on their own unless
     the finding is actually a bug flake8-bugbear/pyflakes/eslint caught (an unused
     variable that should have been used, a real mutable-default bug, etc.).

7. **If either side is not yet clean:** don't just add a blanket ignore. First check
   whether the finding is a real bug (fix the code) or a legitimate, tool-specific false
   positive for this codebase's own conventions (e.g. ruff's B008 firing on every
   FastAPI `Depends(...)` default, which `[tool.ruff.lint.flake8-bugbear]`'s
   `extend-immutable-calls` already documents and resolves) — a new false-positive class
   gets a narrowly-scoped, commented ignore (a specific rule code, not a blanket
   `# noqa` / `# type: ignore`), with the reasoning written next to the ignore itself,
   not just in a chat reply.

## Notes

- No live network calls are needed for any of these five commands — they're pure
  static analysis over the checked-out tree.
- This skill only reports; it doesn't fix findings for you (that's ordinary
  implementation work, or `test-90`'s counterpart for coverage specifically). Load it
  from `pr-reviewer`/`task-qa-reviewer` in place of ad hoc inline lint commands, or run
  it directly whenever you want a static-analysis status check.
- If `backend/pyproject.toml`'s `[tool.ruff]`/`[tool.mypy]` sections or
  `frontend/eslint.config.js`/`tsconfig*.json` are ever removed or the dev dependencies
  uninstalled, that's a regression in its own right (per `architecture-review`'s
  Testing.md coverage-config check, the same principle applies to lint/type config) —
  flag it rather than silently treating "no config" as "nothing to check."
