---
name: orchestrate-tasks
description: Run the fintrade task board autonomously end to end — pick the next ready task, dispatch the task-worker agent to implement it on a branch and open a PR, dispatch the pr-reviewer agent to review that PR, dispatch pr-decision to independently confirm an accept, then dispatch pr-merger to actually merge it — looping to the next task — without stopping for user input except a genuine infrastructure blocker (no GitHub push/PR access) or a merge failure. A task-level question that only the user can answer is recorded on the task and marked waiting_input instead of interrupting the run. Use when asked to work the task board autonomously, "run the pipeline", or similar.
---

# Orchestrate Tasks

Drives `docs/tasks/` to completion by repeatedly dispatching the `task-worker` and `pr-reviewer` agents. You (the session running this skill) are the orchestrator — you never write application code or push commits yourself, only dispatch agents and read task state between rounds.

## Working-tree safety: one agent at a time

`task-worker`, `pr-reviewer`, `pr-decision`, and `pr-merger` all operate against the same shared git working directory — there is no per-agent isolation (no separate worktree or clone). Never have more than one of them running at once, even for unrelated tasks: two agents switching branches or committing concurrently on the same checkout race each other (a checkout mid-flight under another agent's feet, uncommitted work silently stashed and forgotten, a commit landing on the wrong branch). Always dispatch one, wait for it to finish and report back, and only then dispatch the next — exactly as the loop below is written; don't parallelize it to go faster.

This applies to your own edits too: only modify `.claude/` (agent or skill instructions) or run your own git commands (checkout, merge, etc.) between dispatches, never while a `task-worker`/`pr-reviewer`/`pr-decision`/`pr-merger` call is still in flight. The same shared-checkout race applies to you as to a second agent.

## Preflight (once, before the loop)

Confirm GitHub push/PR access actually works before dispatching any worker — a broken credential blocks every task, not just one, so it's worth failing fast and asking the user rather than letting every `task-worker` discover it independently:

- `gh auth status`
- a real push-path check, e.g. `git ls-remote origin` (confirms the configured remote auth actually works, not just that a key file exists)

If either fails, **stop and ask the user** how they want to authenticate (generate an SSH key and register it on GitHub, or `gh auth login`) — this is the one kind of question this skill is allowed to interrupt for, since no task can complete without it.

Also run `python3 scripts/validate_tasks.py` (the `validate-task-board` skill) once before dispatching anything — a malformed task JSON or an `index.json` mirror drift can send `next-task`/`task-worker` down the wrong path for whichever task it touches. Unlike the auth check above, a non-zero result here doesn't block the whole run: fix anything trivially wrong on the current branch (`main`, since nothing has been dispatched yet) and re-run the validator, or if a finding needs a real judgment call about board content, note it and proceed anyway — a validator finding on one task shouldn't stall every other ready task.

## The loop

Repeat until no more progress is possible:

0. **Check for human review feedback before picking anything new.** Scan every open task PR's comments and reviews (`gh pr view <n> --json comments,reviews`) for entries whose author is a real human account, not the shared `raino-agent` account any `task-worker`/`pr-reviewer`/`pr-decision` run posts as. A human comment asking for something to be fixed — on any PR, regardless of what `review.verdict`/task `state` currently say — overrides the automated verdict: treat that task as needing rework (see step 1a below) even if it's currently `"done"`/accepted. This is the one place a human can inject into the loop without going through `questions`/`waiting_input`, precisely because it's faster than that path for feedback on something already reviewed.
1. **Find the next unit of work**, in this priority order:
   a. Any task with unaddressed human PR feedback found in step 0, or already `"implementing"` with `review.verdict == "needs_work"` — a worker needs to address review feedback.
   b. Any other task already `"implementing"` or `"testing"` — resume it (matches `next-task`'s priority rule).
   c. Otherwise, the top-ranked `"planned"` task whose `depends_on` are all `"done"` (same ranking `next-task` uses: unblocks count, then area continuity, then checklist size). Either dispatch the `next-task` agent to pick this, or compute it yourself the same way.
2. If nothing matches any of the above, the loop ends — go to **Stopping**.
3. **Dispatch `task-worker`** for the chosen task id. Git identity and commit signing are already configured globally (`raino-agent`, SSH-signed), so no attribution lines need passing through. Wait for it to finish.
4. Re-read the task's JSON. If `state == "waiting_input"`, log the `questions` entry and go back to step 1 — do not stop the loop for a waiting-input task, and do not try to answer the question yourself.
5. If `state == "testing"` (a PR was opened), **dispatch `pr-reviewer`** for that task id + PR number. Wait for it to finish.
6. Re-read the task's JSON:
   - `state == "implementing"` with `review.verdict == "needs_work"` → this is a retry. Track a per-task retry count yourself (not written to the task file). Under 3 rounds: go back to step 1 (priority rule `a` picks this task up again). At 3 rounds of `needs_work` without resolution: don't keep spinning — append a `questions` entry summarizing the unresolved review feedback, set `state` to `"waiting_input"`, mirror `index.json`, and move on.
   - `state == "done"` (`pr-reviewer` accepted it) → **dispatch `pr-decision`** for that task id + PR number to independently double-check the accept before anyone merges. Wait for it to finish, then re-read the task's JSON again:
     - It reported `decision: merge` (task JSON unchanged, still `state: "done"`) → **dispatch `pr-merger`** for that task id + PR number to actually merge it (see **Merging** below). Wait for it to finish, then check its outcome:
       - Merged cleanly → report it to the user as merged (with the PR link and merge commit) and move on to step 1.
       - It reported the specific discrepancy of a missing/stale `pr_decision` (its `confirmed_at` predates, or is absent relative to, `review.reviewed_at`) → this is a pipeline bookkeeping defect, not a code or git problem. Don't stop the loop, and don't just re-dispatch `pr-decision` to overwrite the timestamp (that papers over a bad `reviewed_at` instead of fixing it). **Dispatch `pr-reviewer` for a fresh re-review** of the same PR — it will write a new, correct `reviewed_at` and clear the stale `pr_decision` as part of that (see its own instructions) — then let `pr-decision` and `pr-merger` follow again in the normal order (step 6 onward). This doesn't count against the 3-round `needs_work` retry cap below; it isn't review feedback on the code.
       - Any other failure to merge (conflicts, failing required check, branch-protection block, anything else) → **stop the whole loop**, exactly like a preflight failure: report the task id, PR number, and the failure reason to the user, and wait for them before dispatching anything else. A merge failure is exactly the kind of thing that can silently corrupt `main` if papered over automatically, so this is not a "log and continue" situation like a `needs_work` retry.
     - It reported `decision: more_work` (task JSON now back to `state: "implementing"`, `review.verdict: "needs_work"`) → treat this exactly like a `needs_work` retry above (same 3-round cap, counting rounds across both `pr-reviewer` and `pr-decision` overrides). Go back to step 1.

## Merging

`pr-merger` is the only agent in this pipeline that runs `gh pr merge`, and only after `pr-decision` has independently confirmed a `merge` decision — never off a single review. `task-worker` and `pr-reviewer` never merge anything, under any verdict. `main`'s branch ruleset needs 0 approving reviews and GitHub blocks self-approval anyway (the worker/reviewer/decision/merger agents all share the `raino-agent` account), so the real review gate in this pipeline is `pr-reviewer` + `pr-decision`'s independent double-check, not a GitHub-native approval — `pr-merger` runs only once both of those have already passed. Any merge failure stops the loop entirely (see above) rather than being retried or silently skipped.

## Stopping

End the loop when every task is `"done"` (merged, or merge-ready awaiting a paused-loop resolution) or `"waiting_input"` (or `"planned"` with dependencies that can never become ready because an upstream task is `"waiting_input"`). Report a summary: tasks merged this run (with PR/commit links), tasks waiting on input (with their open questions, so the user can answer them and resume with a fresh run), and anything left `"planned"` and why.

## What this skill never does

- Never runs `gh pr merge` itself, and never dispatches `pr-merger` off anything less than an independently-confirmed `pr-decision` accept — see **Merging** above.
- Never merges off a single review — always requires `pr-decision`'s independent confirmation first, before `pr-merger` is even dispatched.
- Never keeps looping past a merge failure — a failed merge pauses the whole run for the user, it is not treated like a retriable review finding.
- Never answers a `questions` entry itself — that's the point of recording it instead of guessing.
- Never retries a `needs_work` task forever — the 3-round cap turns a stuck task into a `waiting_input` one instead.
- Never lets a non-blocking review finding live only in a PR comment — every one gets tracked as a checklist item on a JSON task (see `pr-reviewer`'s own instructions), so it isn't lost once the PR merges.
