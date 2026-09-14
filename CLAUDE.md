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
- `.devcontainer/` — the dev container all development happens in (see below).

## Dev container

Development happens inside `.devcontainer/` — it provisions Python 3.12, Node 22, git, the GitHub CLI, and Claude Code itself, so there's nothing to install on the host beyond a Dev Containers-capable editor. `.devcontainer/post-create.sh` runs once per container creation: it builds the backend venv and runs `.devcontainer/setup-help.sh` (re-runnable as `fintrade-help`), which prints setup steps for the GitHub MCP server and an SSH authentication key, and **automatically applies the git commit-signing config** (`gpg.format`, `user.signingkey`, `commit.gpgsign`, `allowed_signers`) as soon as a key exists — only the parts that need a human decision (generating the key, registering it on GitHub) stay manual.

The container generates and keeps its own SSH key in a private named volume (`fintrade-ssh-${devcontainerId}`) rather than mounting the host's real `~/.ssh` — Claude Code's own dev container guidance warns against mounting host secrets into a container it operates in, since a compromised container could exfiltrate them. If you ever add a mount or credential to `.devcontainer/devcontainer.json`, apply the same rule: container-scoped and revocable, never a bind-mount of a host secret.

## Task board (`docs/tasks/`)

Each feature is one JSON file in `docs/tasks/`, plus `docs/tasks/index.json` as the summary index. Shape:

```json
{
  "id": "kebab-case-id",
  "title": "...",
  "area": "backend/indicators",
  "skill": "add-indicator | null",
  "state": "planned | implementing | testing | waiting_input | done",
  "depends_on": ["other-task-id"],
  "references": ["docs/Analyse.md#section"],
  "description": "...",
  "checklist": [{ "step": "...", "done": false }],
  "decisions": [
    { "timestamp": "ISO 8601 timestamp", "recorded_by": "skill/agent name, or 'manual'", "decision": "what was decided", "rationale": "why, including any alternative considered and rejected" }
  ],
  "questions": [
    { "timestamp": "ISO 8601 timestamp", "raised_by": "skill/agent name", "question": "what needs a human decision", "context": "why the worker couldn't resolve this itself" }
  ],
  "git": { "branch": "task/kebab-case-id", "pr_number": 12, "pr_url": "...", "pushed_at": "ISO 8601 timestamp" },
  "test": {
    "reviewed_at": "ISO 8601 timestamp",
    "method": ["static_analysis", "unit_tests", "browser_walkthrough"],
    "verdict": "pass | gaps_found",
    "gap_analysis": [{ "summary": "...", "severity": "blocker | major | minor", "evidence": "..." }]
  },
  "review": {
    "reviewed_at": "ISO 8601 timestamp",
    "pr_url": "...",
    "verdict": "accepted | needs_work",
    "comments": [{ "summary": "...", "file": "...", "line": 0 }],
    "notes": "..."
  },
  "pr_decision": {
    "confirmed_at": "ISO 8601 timestamp",
    "verdict": "merge",
    "notes": "..."
  }
}
```

`skill` names the `.claude/skills/` workflow that governs the task (`null` for pure scaffolding/infra tasks with no dedicated skill — don't force a fit). `state: "waiting_input"` means a `questions` entry needs a human decision before the task can resume (see below) — it's distinct from a task simply waiting on `depends_on`. `test` is written by the `task-qa-reviewer` agent (see below); `git` is written by `task-worker` when it pushes a branch and opens a PR; `review` is written by `pr-reviewer` after checking out that PR; `pr_decision` is written by `pr-decision` on a `merge` decision only — its one durable, independently-checkable trace that a genuine re-verification happened (it deliberately posts no PR review/comment of its own on that path), which `pr-merger` checks for before trusting a dispatch instruction that says "pr-decision already confirmed this." Once `pr-merger` actually merges a task's PR, the task JSON that lands on `main` is just whatever was already on the PR branch (a squash merge, so no separate sync step) — there's no `git.merged_at`/`merge_commit` field, since `main`'s branch-protection ruleset rejects every direct push, including a bookkeeping-only one, so nothing can add it after the fact without a whole extra PR for one timestamp; the merge commit itself (`gh pr view <n> --json mergeCommit`) is the source of truth if that's ever needed. All of `test`, `git`, `review`, `pr_decision`, `decisions`, `questions` are absent until something has actually happened to populate them.

### Decision memory (`decisions`)

Whoever works a task — human or agent — makes judgment calls that aren't fully pinned down by `docs/Analyse.md` or `docs/architecture/*.md`: which of several valid technical approaches to use, how to interpret an ambiguous parameter, how to resolve a checklist item phrased as "decide X" (e.g. the duplicate-ticker behavior flagged in `api-portfolio-add-position`). **Record these in the task's own `decisions` array as they're made** — not only in a code comment or a chat reply, both of which are invisible to the next session or agent that picks the task back up. A decision entry needs `decision` (what) and `rationale` (why, including what you rejected and why) to be useful; a bare "changed X" isn't a decision record.

This is enforced by the `add-indicator`, `add-api-endpoint`, and `verify-elder-signal` skills (which write entries), and checked by `next-task` (which surfaces existing entries when resuming in-progress work) and `task-qa-reviewer` (which flags an undocumented decision as a gap).

**`docs/tasks/index.json`'s per-task `state` is a mirror, not a separate source of truth.** Whenever a task file's `state` changes, update `index.json`'s entry for that task in the same change — don't let them drift.

To decide what to work on next, use the `next-task` agent rather than eyeballing the board — it reads the dependency graph and current states for you.

### Blocked tasks and open questions (`questions`)

`decisions` is for judgment calls a worker *can* make itself and just needs to record. `questions` is its counterpart for the rarer case where the call genuinely belongs to the user — a missing external credential, a conflicting requirement, a product decision the docs don't and can't settle. When that happens mid-task, the right move is not to stop and ask interactively: append an entry to the task's `questions` array, set `state` to `"waiting_input"`, mirror `index.json`, and move on to other work. `next-task` surfaces waiting-input tasks and their open questions so a human session can answer them; answering one means editing the task (often adding a `decisions` entry that records the answer) and moving `state` back to `"planned"` or `"implementing"` to resume it. See "Autonomous pipeline" below for how `orchestrate-tasks` uses this to keep working instead of stalling on one task.

## Autonomous pipeline (orchestrator → worker → reviewer → decision → merger)

The `orchestrate-tasks` skill runs the task board hands-off. It dispatches `task-worker` (implements one task on its own branch, pushes, opens a PR), `pr-reviewer` (checks out that PR, reviews it, records accepted or needs-work as a PR comment), `pr-decision` (once `pr-reviewer` accepts, independently re-verifies the accept), and `pr-merger` (once `pr-decision` independently confirms it, actually merges the PR) in a loop, moving to the next ready task without waiting on a human at each step except a merge failure or a genuine infrastructure blocker.

- **Branch naming**: `task/<task-id>`, always cut from the latest `main`.
- **Merging requires two independent confirmations first**: `task-worker` and `pr-reviewer` never merge anything, under any verdict. `pr-decision` never merges either — it only reports `decision: merge`. Only `pr-merger` runs `gh pr merge`, and only after both `pr-reviewer` has accepted *and* `pr-decision` has independently re-verified that accept. `main`'s branch ruleset needs 0 approving reviews and GitHub blocks self-approval anyway (all four agents share one `gh` account), so a formal GitHub-native approval was never going to be the real gate here — the two independent agent passes are. A merge failure (conflict, a failing check, a branch-protection rejection) stops the whole `orchestrate-tasks` run for the user rather than being retried or routed around; see `.claude/agents/pr-merger.md`.
- **Every non-blocking finding becomes a tracked task, not just a PR comment**: `pr-reviewer` (and, when it overrides an accept, `pr-decision`) records every finding in the task's own `review.comments` as before, but a *non-blocking* one also gets a `checklist` entry on a `docs/tasks/<id>-followups.json` task (created if one doesn't already exist for that task id, `state: "planned"`, `depends_on: [<id>]`) — a PR comment disappears from view once the PR merges, so anything worth remembering needs to live on the board itself.
- **A human PR comment always wins over an automated verdict**: before picking a new task, `orchestrate-tasks` checks every open task PR for comments/reviews from a real human account (not the shared automation account) asking for something to be fixed. That overrides whatever `review.verdict`/task `state` currently say, even `"done"`/accepted — the task goes back to being worked, no `questions`/`waiting_input` detour needed for this case since it's already a direct, actionable human instruction.
- **Ambiguity, not interruption**: an ordinary judgment call becomes a `decisions` entry and work continues (above). Something only the user can actually decide becomes a `questions` entry and the task moves to `waiting_input` instead of stopping the whole run (above).
- **The things that do stop the loop**: an infrastructure blocker that would fail every task the same way (most likely no GitHub push/PR access — checked once before starting), and a merge failure on any individual PR (checked per-merge, stops just that run so the user can look at it — see above).
- **One agent at a time on the shared working tree**: `task-worker`, `pr-reviewer`, `pr-decision`, and `pr-merger` all operate against the same git checkout with no per-agent isolation — never dispatch a new one while another is still in flight, even for an unrelated task. This applies to the orchestrator itself too: only edit `.claude/` or run your own git commands (checkout, merge, etc.) between dispatches, never while an agent is running, or the same race applies to you. It also means agent *instructions* are whatever `.claude/agents/*.md` says on the branch currently checked out at dispatch time — a subagent's own internal `gh pr checkout` mid-run doesn't retroactively change the instructions it was already given, but it does mean the orchestrator's working tree is left on that PR's branch afterward, which matters for what the *next* dispatch reads. Keep the orchestrator's own checkout on a branch with current `.claude/` instructions (`main`, once these land there) before dispatching again.

## Skills (`.claude/skills/`)

- `add-indicator` — add/change a technical indicator, with hand-computed reference-value tests.
- `add-api-endpoint` — add/change a FastAPI endpoint, keeping schema, OpenAPI snapshot, and frontend types in sync.
- `check-coverage` — run backend + frontend coverage together and report against the 90% gate.
- `test-90` — actively close coverage gaps (the write-tests counterpart to `check-coverage`).
- `verify-elder-signal` — review signal/confidence/risk code against `docs/Analyse.md`.
- `architecture-review` — review code structure against `docs/Architecture.md` and its sub-docs.
- `orchestrate-tasks` — run the whole task board autonomously: dispatch `task-worker`, `pr-reviewer`, `pr-decision`, and `pr-merger` in a loop (branch → PR → review → independent double-check → merge) until the board is done or genuinely waiting on user input.

## Agents (`.claude/agents/`)

- `elder-signal-reviewer` — read-only audit of trading logic against `docs/Analyse.md` (loads the `verify-elder-signal` skill).
- `architecture-reviewer` — read-only audit of code structure against the architecture docs (loads the `architecture-review` skill).
- `next-task` — reads `docs/tasks/`, recommends what to work on next based on dependencies and current state.
- `task-qa-reviewer` — verifies a task by running static analysis, the test suite, and (for UI-facing work) an actual browser walkthrough; writes its findings into that task's JSON file. Run this before flipping a task to `done`.
- `task-worker` — implements one task end to end on branch `task/<id>` and opens a PR; records genuine ambiguities as a `questions` entry + `waiting_input` state instead of asking interactively. Used by `orchestrate-tasks`.
- `pr-reviewer` — checks out a task's PR and gives it a full review (tests/coverage, code quality, methodology/architecture conformance as relevant); records accepted or needs-work as a PR comment (never a formal approve/request-changes review) and files a tracked follow-up task for every non-blocking finding. Never merges. Used by `orchestrate-tasks`.
- `pr-decision` — given a `pr-reviewer`-accepted PR, independently re-verifies the accept (re-runs tests, skims the diff itself) before anyone merges; either confirms it or overrides to needs-more-work via a PR comment. Never merges, never runs a formal approve/request-changes review either. Used by `orchestrate-tasks`.
- `pr-merger` — given a PR `pr-decision` has independently confirmed with `decision: merge`, actually runs `gh pr merge`. The only agent authorized to merge; reports success or failure (never retries or routes around a failure) back to the orchestrator. Used by `orchestrate-tasks`.

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

Backend `pyproject.toml` pins `requires-python>=3.12` and `pandas>=2.2,<3` (pandas 3.x resolves by default if unpinned; `pandas-ta` is intentionally not a dependency — see `docs/architecture/Backend.md` §1).

`backend/.venv/` is gitignored either way, but its lifecycle depends on context: **inside the dev container**, it's created once by `.devcontainer/post-create.sh` and is meant to persist for the container's lifetime — don't delete it. **Outside the dev container** (e.g. an ad hoc host-side verification pass, or a sandboxed agent session with no persistent filesystem across turns), treat it as ephemeral — create one to install/test, remove it when done rather than leaving it in the tree.
