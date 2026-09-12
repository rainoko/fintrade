---
name: orchestrate-tasks
description: Run the fintrade task board autonomously end to end — pick the next ready task, dispatch the task-worker agent to implement it on a branch and open a PR, dispatch the pr-reviewer agent to review that PR, and loop to the next task — without stopping for user input except a genuine infrastructure blocker (no GitHub push/PR access). A task-level question that only the user can answer is recorded on the task and marked waiting_input instead of interrupting the run. Use when asked to work the task board autonomously, "run the pipeline", or similar.
---

# Orchestrate Tasks

Drives `docs/tasks/` to completion by repeatedly dispatching the `task-worker` and `pr-reviewer` agents. You (the session running this skill) are the orchestrator — you never write application code or push commits yourself, only dispatch agents and read task state between rounds.

## Preflight (once, before the loop)

Confirm GitHub push/PR access actually works before dispatching any worker — a broken credential blocks every task, not just one, so it's worth failing fast and asking the user rather than letting every `task-worker` discover it independently:

- `gh auth status`
- a real push-path check, e.g. `git ls-remote origin` (confirms the configured remote auth actually works, not just that a key file exists)

If either fails, **stop and ask the user** how they want to authenticate (generate an SSH key and register it on GitHub, or `gh auth login`) — this is the one kind of question this skill is allowed to interrupt for, since no task can complete without it.

## The loop

Repeat until no more progress is possible:

1. **Find the next unit of work**, in this priority order:
   a. Any task already `"implementing"` with `review.verdict == "needs_work"` — a worker needs to address review feedback.
   b. Any other task already `"implementing"` or `"testing"` — resume it (matches `next-task`'s priority rule).
   c. Otherwise, the top-ranked `"planned"` task whose `depends_on` are all `"done"` (same ranking `next-task` uses: unblocks count, then area continuity, then checklist size). Either dispatch the `next-task` agent to pick this, or compute it yourself the same way.
2. If nothing matches any of the above, the loop ends — go to **Stopping**.
3. **Dispatch `task-worker`** for the chosen task id. Give it the task id, and the exact commit-trailer and PR-footer attribution lines from your own session context — it must not invent its own. Wait for it to finish.
4. Re-read the task's JSON. If `state == "waiting_input"`, log the `questions` entry and go back to step 1 — do not stop the loop for a waiting-input task, and do not try to answer the question yourself.
5. If `state == "testing"` (a PR was opened), **dispatch `pr-reviewer`** for that task id + PR number. Wait for it to finish.
6. Re-read the task's JSON:
   - `state == "done"` → task complete, go back to step 1.
   - `state == "implementing"` with `review.verdict == "needs_work"` → this is a retry. Track a per-task retry count yourself (not written to the task file). Under 3 rounds: go back to step 1 (priority rule `a` picks this task up again). At 3 rounds of `needs_work` without resolution: don't keep spinning — append a `questions` entry summarizing the unresolved review feedback, set `state` to `"waiting_input"`, mirror `index.json`, and move on.

## Stopping

End the loop when every task is `"done"` or `"waiting_input"` (or `"planned"` with dependencies that can never become ready because an upstream task is `"waiting_input"`). Report a summary: tasks completed this run (with PR links), tasks waiting on input (with their open questions, so the user can answer them and resume with a fresh run), and anything left `"planned"` and why.

## What this skill never does

- Never pushes to `main` or merges a PR — `task-worker` opens PRs, `pr-reviewer` approves or requests changes, merging is left to the user.
- Never answers a `questions` entry itself — that's the point of recording it instead of guessing.
- Never retries a `needs_work` task forever — the 3-round cap turns a stuck task into a `waiting_input` one instead.
