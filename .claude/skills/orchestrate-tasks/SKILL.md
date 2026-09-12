---
name: orchestrate-tasks
description: Run the fintrade task board autonomously end to end — pick the next ready task, dispatch the task-worker agent to implement it on a branch and open a PR, dispatch the pr-reviewer agent to review that PR, and loop to the next task — without stopping for user input except a genuine infrastructure blocker (no GitHub push/PR access). A task-level question that only the user can answer is recorded on the task and marked waiting_input instead of interrupting the run. Use when asked to work the task board autonomously, "run the pipeline", or similar.
---

# Orchestrate Tasks

Drives `docs/tasks/` to completion by repeatedly dispatching the `task-worker` and `pr-reviewer` agents. You (the session running this skill) are the orchestrator — you never write application code or push commits yourself, only dispatch agents and read task state between rounds.

## Working-tree safety: one agent at a time

`task-worker`, `pr-reviewer`, and `pr-decision` all operate against the same shared git working directory — there is no per-agent isolation (no separate worktree or clone). Never have more than one of them running at once, even for unrelated tasks: two agents switching branches or committing concurrently on the same checkout race each other (a checkout mid-flight under another agent's feet, uncommitted work silently stashed and forgotten, a commit landing on the wrong branch). Always dispatch one, wait for it to finish and report back, and only then dispatch the next — exactly as the loop below is written; don't parallelize it to go faster.

This applies to your own edits too: only modify `.claude/` (agent or skill instructions) or run your own git commands (checkout, merge, etc.) between dispatches, never while a `task-worker`/`pr-reviewer`/`pr-decision` call is still in flight. The same shared-checkout race applies to you as to a second agent.

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
3. **Dispatch `task-worker`** for the chosen task id. Git identity and commit signing are already configured globally (`raino-agent`, SSH-signed), so no attribution lines need passing through. Wait for it to finish.
4. Re-read the task's JSON. If `state == "waiting_input"`, log the `questions` entry and go back to step 1 — do not stop the loop for a waiting-input task, and do not try to answer the question yourself.
5. If `state == "testing"` (a PR was opened), **dispatch `pr-reviewer`** for that task id + PR number. Wait for it to finish.
6. Re-read the task's JSON:
   - `state == "implementing"` with `review.verdict == "needs_work"` → this is a retry. Track a per-task retry count yourself (not written to the task file). Under 3 rounds: go back to step 1 (priority rule `a` picks this task up again). At 3 rounds of `needs_work` without resolution: don't keep spinning — append a `questions` entry summarizing the unresolved review feedback, set `state` to `"waiting_input"`, mirror `index.json`, and move on.
   - `state == "done"` (`pr-reviewer` accepted it) → **dispatch `pr-decision`** for that task id + PR number to independently double-check the accept before anyone merges. Wait for it to finish, then re-read the task's JSON again:
     - It reported `decision: merge` (task JSON unchanged, still `state: "done"`) → this PR is genuinely ready. Report it to the user as ready-to-merge and move on to step 1 — merging itself is a decision this skill does not make, see below.
     - It reported `decision: more_work` (task JSON now back to `state: "implementing"`, `review.verdict: "needs_work"`) → treat this exactly like a `needs_work` retry above (same 3-round cap, counting rounds across both `pr-reviewer` and `pr-decision` overrides). Go back to step 1.

## Merging is always the user's call

Neither `task-worker`, `pr-reviewer`, `pr-decision`, nor this skill ever runs `gh pr merge`. `main`'s branch ruleset needs 0 approving reviews to merge and GitHub blocks self-approval (the worker/reviewer/decision agents all share the `raino-agent` account) — so no chain of automated agents here can constitute genuine independent review; the only real check possible is a human one. `pr-decision` exists to make that human check fast (it's already double-verified, not just single-reviewed) — not to replace it.

## Stopping

End the loop when every task is `"done"` (merge-ready, awaiting the user) or `"waiting_input"` (or `"planned"` with dependencies that can never become ready because an upstream task is `"waiting_input"`). Report a summary: tasks completed and merge-ready this run (with PR links), tasks waiting on input (with their open questions, so the user can answer them and resume with a fresh run), and anything left `"planned"` and why.

## What this skill never does

- Never pushes to `main` or merges a PR, under any agent, including this skill's own orchestrator role — see **Merging is always the user's call** above.
- Never merges off a single review — always requires `pr-decision`'s independent confirmation first, even though the actual merge command still isn't run by anyone in this pipeline.
- Never answers a `questions` entry itself — that's the point of recording it instead of guessing.
- Never retries a `needs_work` task forever — the 3-round cap turns a stuck task into a `waiting_input` one instead.
