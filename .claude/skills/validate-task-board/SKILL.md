---
name: validate-task-board
description: Run scripts/validate_tasks.py to check every docs/tasks/*.json and docs/tasks/done/*.json against the structural invariants CLAUDE.md's "Task board" section documents (required fields/types, valid state values, checklist/decisions/questions entry shape, depends_on resolution, index.json mirror consistency, the done<=>docs/tasks/done/ path invariant), and report every violation found. Use when asked to validate the task board, check docs/tasks/ JSON structure, or before/after a change that edits multiple task files (e.g. a revalidate-done-tasks run, an orchestrate-tasks board edit).
---

# Validate Task Board

`docs/tasks/` is hand- and agent-edited JSON with no schema enforcement of its own —
every invariant CLAUDE.md's "Task board" section documents (required top-level shape,
valid `state` values, `checklist`/`decisions`/`questions` entry shape, `depends_on`
resolution, the `index.json` mirror rule, the `done` <=> `docs/tasks/done/` path
invariant) is otherwise only checked by whichever agent happens to be looking at a
given task at the time. This skill runs a single stdlib-only script
(`scripts/validate_tasks.py`) that checks the whole board at once. It does not fix
anything itself — like `static-verify`/`check-coverage`, it only reports.

## Steps

1. **Run the validator** from the repo root:
   ```
   python3 scripts/validate_tasks.py
   ```
   No venv, install step, or `backend/`/`frontend/` environment is needed — the script
   is pure standard library (`json`, `pathlib`, `sys`) and reads directly from
   `docs/tasks/*.json` and `docs/tasks/done/*.json`.

2. **Exit code is the pass/fail signal**: `0` with a brief one-line summary
   ("validated N task file(s) ... no violations found") means every checked invariant
   holds; non-zero means at least one violation was found, printed as a `[task-id]
   message` line per violation, grouped and sorted by task id, with a trailing count.

3. **Report every violation found**, grouped by task id as the script already
   presents them — don't summarize away individual findings. Distinguish (as the
   messages themselves do) between:
   - a structural/type problem (missing/wrong-typed required field, invalid `state`
     value, malformed `checklist`/`decisions`/`questions` entry),
   - a cross-reference problem (`depends_on` pointing at a nonexistent id,
     `index.json` state/path drift against the task's own file, a task file with no
     corresponding `index.json` entry or vice versa), and
   - the `done` <=> `docs/tasks/done/` location invariant specifically, since
     CLAUDE.md calls that one out by name.

4. **This skill only reports** — same as `static-verify`. A real finding gets fixed by
   editing the offending task JSON (or `docs/tasks/index.json`) directly, following the
   same mirror-consistency rule the validator itself checks, not by loosening the
   script's checks to make a genuine board defect stop being reported.

## Notes

- No live network calls, no test fixtures, no coverage gate — this is a pure
  structural lint over checked-in JSON, closer in spirit to `static-verify` than to
  `check-coverage`.
- The validator does not judge board *content* (whether a `decisions` entry's
  reasoning is actually good, whether a task's checklist is the right one) — only its
  *shape*, and one content-adjacent rule CLAUDE.md states explicitly: a `decisions`
  entry whose `rationale` is empty or just restates `decision` verbatim (the "bare
  'changed X'" case CLAUDE.md calls out by name) is flagged as invalid.
- `review.comments[].file`/`review.comments[].line` may legitimately be an explicit
  `null` (a comment not tied to one specific file/line, e.g. a suite-wide coverage
  note) — the validator accepts `null` there without complaint, only flagging a
  wrong-typed non-null value.
- Unrecognized extra top-level or nested fields (e.g. an indicator task's
  `consumed_by`) are not flagged — the validator checks that the documented fields are
  present and correctly typed, not that no other field exists.
- Source: `scripts/validate_tasks.py`, plain `python3`, no `pip install` required.
