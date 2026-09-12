# fintrade

Stock/portfolio analysis app that signals BUY/SELL/HOLD with a confidence percentage, using Dr. Alexander Elder's Triple Screen methodology. Start at [docs/Analyse.md](docs/Analyse.md) for the methodology and [docs/Architecture.md](docs/Architecture.md) for the system design — read both before making a change that touches signal logic or project structure.

## Repo layout

- `docs/Analyse.md` — the analytical methodology (Triple Screen, Impulse System, confidence scoring, portfolio risk rules). Source of truth for *what* the app computes.
- `docs/Architecture.md` + `docs/architecture/{Backend,Frontend,API,Testing}.md` — system design. Source of truth for *how* it's built.
- `docs/tasks/` — the feature task board (see below).
- `backend/` — Python/FastAPI backend.
- `frontend/` — TypeScript/React frontend (not yet scaffolded).
- `.claude/skills/` — repeatable workflows (see below).
- `.claude/agents/` — task-scoped subagents (see below).

## Task board (`docs/tasks/`)

Each feature is one JSON file in `docs/tasks/`, plus `docs/tasks/index.json` as the summary index. Shape:

```json
{
  "id": "kebab-case-id",
  "title": "...",
  "area": "backend/indicators",
  "skill": "add-indicator | null",
  "state": "planned | implementing | testing | done",
  "depends_on": ["other-task-id"],
  "references": ["docs/Analyse.md#section"],
  "description": "...",
  "checklist": [{ "step": "...", "done": false }],
  "test": {
    "reviewed_at": "ISO 8601 timestamp",
    "method": ["static_analysis", "unit_tests", "browser_walkthrough"],
    "verdict": "pass | gaps_found",
    "gap_analysis": [{ "summary": "...", "severity": "blocker | major | minor", "evidence": "..." }]
  }
}
```

`skill` names the `.claude/skills/` workflow that governs the task (`null` for pure scaffolding/infra tasks with no dedicated skill — don't force a fit). The `test` object is written by the `task-qa-reviewer` agent (see below); it's absent until a task has been reviewed.

**`docs/tasks/index.json`'s per-task `state` is a mirror, not a separate source of truth.** Whenever a task file's `state` changes, update `index.json`'s entry for that task in the same change — don't let them drift.

To decide what to work on next, use the `next-task` agent rather than eyeballing the board — it reads the dependency graph and current states for you.

## Skills (`.claude/skills/`)

- `add-indicator` — add/change a technical indicator, with hand-computed reference-value tests.
- `add-api-endpoint` — add/change a FastAPI endpoint, keeping schema, OpenAPI snapshot, and frontend types in sync.
- `check-coverage` — run backend + frontend coverage together and report against the 90% gate.
- `test-90` — actively close coverage gaps (the write-tests counterpart to `check-coverage`).
- `verify-elder-signal` — review signal/confidence/risk code against `docs/Analyse.md`.
- `architecture-review` — review code structure against `docs/Architecture.md` and its sub-docs.

## Agents (`.claude/agents/`)

- `elder-signal-reviewer` — read-only audit of trading logic against `docs/Analyse.md` (loads the `verify-elder-signal` skill).
- `architecture-reviewer` — read-only audit of code structure against the architecture docs (loads the `architecture-review` skill).
- `next-task` — reads `docs/tasks/`, recommends what to work on next based on dependencies and current state.
- `task-qa-reviewer` — verifies a task by running static analysis, the test suite, and (for UI-facing work) an actual browser walkthrough; writes its findings into that task's JSON file. Run this before flipping a task to `done`.

## API documentation standard

The OpenAPI contract is the single source of truth the frontend builds against (`backend/openapi.json`, a committed snapshot — see `docs/architecture/API.md` §Contract Snapshot & Parallel Development). **Every route must be well-explained, not just correctly typed:**

- `response_model` set, and every documented error case declared in `responses={...}` (404/422/503 etc., using the `ErrorDetail` schema) — not just the success path.
- An explicit `operation_id` (clean generated frontend function/type names — don't rely on FastAPI's auto-generated ones).
- A `summary`, and a docstring (FastAPI uses it as `description`) explaining what the endpoint actually does, not just restating its name.
- Pydantic schema fields get a `description` in `app/api/schemas.py` wherever the field's meaning isn't obvious from its name alone (units, ranges, what triggers a null, etc.).

Run `python scripts/export_openapi.py` from `backend/` and commit the updated `backend/openapi.json` any time a schema or route signature changes — before the frontend consumes the change. The `add-api-endpoint` skill and `architecture-reviewer` agent both check for this.

## Testing standard

90% line/branch coverage is a hard gate on both backend and frontend (`docs/architecture/Testing.md`). No test — on either side — makes a live network call; market data providers and the API boundary are always mocked. See `check-coverage` / `test-90`.

## Backend environment notes

Backend `pyproject.toml` pins `requires-python>=3.12` and `pandas>=2.2,<3` (pandas 3.x resolves by default if unpinned; `pandas-ta` is intentionally not a dependency — see `docs/architecture/Backend.md` §1). Virtualenvs (`.venv/`) are ephemeral and gitignored — create one to install/test, remove it when done rather than leaving it in the tree.
