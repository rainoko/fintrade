#!/usr/bin/env python3
"""Validate docs/tasks/ against the invariants CLAUDE.md's "Task board" section
documents.

Checks every docs/tasks/*.json and docs/tasks/done/*.json for:

- the required top-level shape (id, title, area, skill, state, depends_on,
  references, description, checklist) and each field's type, plus the type of
  every optional field when present (decisions, questions, git, test, review,
  pr_decision);
- `state` is one of the five documented values;
- each `checklist` item has `step` (string) and `done` (boolean);
- each `decisions` entry has `decision` + `rationale` (a bare restatement of
  `decision` as its own `rationale` is exactly what CLAUDE.md calls out as NOT
  a valid decision record) and each `questions` entry has `question` +
  `context`;
- every `depends_on` id actually exists somewhere on the board;
- docs/tasks/index.json's per-task `state`/`path` exactly mirrors that task's
  own file, with no drift;
- a task's file lives under docs/tasks/done/ if and only if its `state` is
  "done".

Stdlib-only (json, pathlib, sys) so it needs no venv/install step — see this
task's `decisions` entry for why. Exits 0 with a brief summary on success,
non-zero with a per-task list of every violation found on failure.

Usage: python3 scripts/validate_tasks.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, TypeGuard

REPO_ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = REPO_ROOT / "docs" / "tasks"
DONE_DIR = TASKS_DIR / "done"
INDEX_PATH = TASKS_DIR / "index.json"

VALID_STATES = {"planned", "implementing", "testing", "waiting_input", "done"}
VALID_TEST_VERDICTS = {"pass", "gaps_found"}
VALID_SEVERITIES = {"blocker", "major", "minor"}
VALID_REVIEW_VERDICTS = {"accepted", "needs_work"}

REQUIRED_TOP_LEVEL_TYPES: dict[str, type] = {
    "id": str,
    "title": str,
    "area": str,
    "state": str,
    "depends_on": list,
    "references": list,
    "description": str,
    "checklist": list,
}


class Violation:
    __slots__ = ("message", "task_id")

    def __init__(self, task_id: str, message: str) -> None:
        self.task_id = task_id
        self.message = message

    def __str__(self) -> str:
        return f"[{self.task_id}] {self.message}"


def is_nonempty_str(value: Any) -> TypeGuard[str]:
    return isinstance(value, str) and value.strip() != ""


def is_invalid_str_choice(value: Any, valid_values: set[str]) -> bool:
    """True if `value` isn't a string member of `valid_values`.

    Shared by every "must be one of these string values" check in this module
    (test.verdict, review.verdict, gap_analysis[].severity, index.json entry
    state) so the isinstance-and-membership condition itself -- which is what
    made those four checks crash on a non-scalar value before that bug was
    fixed -- isn't repeated at each call site. Each call site still owns its
    own violation message wording, since those differ enough (field path,
    whether the valid-values list is echoed back) that unifying the message
    too would cost more than it saves.
    """
    return not (isinstance(value, str) and value in valid_values)


def load_json(path: Path) -> tuple[Any, str | None]:
    try:
        return json.loads(path.read_text()), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, str(exc)


def check_task_shape(task_id: str, data: dict[str, Any], filename_stem: str) -> list[Violation]:
    violations: list[Violation] = []

    def fail(message: str) -> None:
        violations.append(Violation(task_id, message))

    for field, expected_type in REQUIRED_TOP_LEVEL_TYPES.items():
        if field not in data:
            fail(f"missing required field '{field}'")
            continue
        if not isinstance(data[field], expected_type):
            fail(
                f"field '{field}' must be a {expected_type.__name__}, "
                f"got {type(data[field]).__name__}"
            )

    if "skill" not in data:
        fail("missing required field 'skill'")
    elif data["skill"] is not None and not isinstance(data["skill"], str):
        fail("field 'skill' must be a string or null")

    if is_nonempty_str(data.get("id")) and data["id"] != filename_stem:
        fail(f"'id' field ({data['id']!r}) does not match its filename ({filename_stem!r})")

    state = data.get("state")
    if isinstance(state, str) and state not in VALID_STATES:
        fail(f"'state' value {state!r} is not one of {sorted(VALID_STATES)}")

    if isinstance(data.get("depends_on"), list):
        for i, dep in enumerate(data["depends_on"]):
            if not isinstance(dep, str):
                fail(f"depends_on[{i}] must be a string, got {type(dep).__name__}")

    if isinstance(data.get("references"), list):
        for i, ref in enumerate(data["references"]):
            if not isinstance(ref, str):
                fail(f"references[{i}] must be a string, got {type(ref).__name__}")

    if isinstance(data.get("checklist"), list):
        for i, item in enumerate(data["checklist"]):
            if not isinstance(item, dict):
                fail(f"checklist[{i}] must be an object, got {type(item).__name__}")
                continue
            if not is_nonempty_str(item.get("step")):
                fail(f"checklist[{i}].step must be a non-empty string")
            if not isinstance(item.get("done"), bool):
                fail(f"checklist[{i}].done must be a boolean")

    if "decisions" in data:
        if not isinstance(data["decisions"], list):
            fail("field 'decisions' must be a list")
        else:
            for i, entry in enumerate(data["decisions"]):
                if not isinstance(entry, dict):
                    fail(f"decisions[{i}] must be an object")
                    continue
                decision = entry.get("decision")
                rationale = entry.get("rationale")
                if not is_nonempty_str(decision):
                    fail(f"decisions[{i}].decision must be a non-empty string")
                if not is_nonempty_str(rationale):
                    fail(
                        f"decisions[{i}].rationale must be a non-empty string "
                        "(a bare 'changed X' with no rationale is not a valid "
                        "decision record per CLAUDE.md)"
                    )
                elif (
                    is_nonempty_str(decision)
                    and rationale.strip().lower() == decision.strip().lower()
                ):
                    fail(
                        f"decisions[{i}].rationale must not just restate "
                        "'decision' verbatim -- a bare 'changed X' is not a "
                        "valid decision record per CLAUDE.md"
                    )
                if "timestamp" in entry and not is_nonempty_str(entry["timestamp"]):
                    fail(f"decisions[{i}].timestamp must be a non-empty string when present")
                if "recorded_by" in entry and not is_nonempty_str(entry["recorded_by"]):
                    fail(f"decisions[{i}].recorded_by must be a non-empty string when present")

    if "questions" in data:
        if not isinstance(data["questions"], list):
            fail("field 'questions' must be a list")
        else:
            for i, entry in enumerate(data["questions"]):
                if not isinstance(entry, dict):
                    fail(f"questions[{i}] must be an object")
                    continue
                if not is_nonempty_str(entry.get("question")):
                    fail(f"questions[{i}].question must be a non-empty string")
                if not is_nonempty_str(entry.get("context")):
                    fail(f"questions[{i}].context must be a non-empty string")
                if "timestamp" in entry and not is_nonempty_str(entry["timestamp"]):
                    fail(f"questions[{i}].timestamp must be a non-empty string when present")
                if "raised_by" in entry and not is_nonempty_str(entry["raised_by"]):
                    fail(f"questions[{i}].raised_by must be a non-empty string when present")

    if "git" in data:
        git = data["git"]
        if not isinstance(git, dict):
            fail("field 'git' must be an object")
        else:
            if "branch" in git and not is_nonempty_str(git["branch"]):
                fail("git.branch must be a non-empty string when present")
            if "pr_number" in git and not isinstance(git["pr_number"], int):
                fail("git.pr_number must be an integer when present")
            if "pr_url" in git and not is_nonempty_str(git["pr_url"]):
                fail("git.pr_url must be a non-empty string when present")
            if "pushed_at" in git and not is_nonempty_str(git["pushed_at"]):
                fail("git.pushed_at must be a non-empty string when present")

    if "test" in data:
        test = data["test"]
        if not isinstance(test, dict):
            fail("field 'test' must be an object")
        else:
            if "reviewed_at" in test and not is_nonempty_str(test["reviewed_at"]):
                fail("test.reviewed_at must be a non-empty string when present")
            if "method" in test and (
                not isinstance(test["method"], list)
                or not all(isinstance(m, str) for m in test["method"])
            ):
                fail("test.method must be a list of strings when present")
            if "verdict" in test and is_invalid_str_choice(test["verdict"], VALID_TEST_VERDICTS):
                fail(f"test.verdict must be one of {sorted(VALID_TEST_VERDICTS)}, got {test['verdict']!r}")
            if "gap_analysis" in test:
                if not isinstance(test["gap_analysis"], list):
                    fail("test.gap_analysis must be a list when present")
                else:
                    for i, gap in enumerate(test["gap_analysis"]):
                        if not isinstance(gap, dict):
                            fail(f"test.gap_analysis[{i}] must be an object")
                            continue
                        if not is_nonempty_str(gap.get("summary")):
                            fail(f"test.gap_analysis[{i}].summary must be a non-empty string")
                        severity = gap.get("severity")
                        if is_invalid_str_choice(severity, VALID_SEVERITIES):
                            fail(
                                f"test.gap_analysis[{i}].severity must be one of "
                                f"{sorted(VALID_SEVERITIES)}, got {severity!r}"
                            )
                        if not is_nonempty_str(gap.get("evidence")):
                            fail(f"test.gap_analysis[{i}].evidence must be a non-empty string")

    if "review" in data:
        review = data["review"]
        if not isinstance(review, dict):
            fail("field 'review' must be an object")
        else:
            if "reviewed_at" in review and not is_nonempty_str(review["reviewed_at"]):
                fail("review.reviewed_at must be a non-empty string when present")
            if "pr_url" in review and not is_nonempty_str(review["pr_url"]):
                fail("review.pr_url must be a non-empty string when present")
            if "verdict" in review and is_invalid_str_choice(
                review["verdict"], VALID_REVIEW_VERDICTS
            ):
                fail(
                    f"review.verdict must be one of {sorted(VALID_REVIEW_VERDICTS)}, "
                    f"got {review['verdict']!r}"
                )
            if "comments" in review:
                if not isinstance(review["comments"], list):
                    fail("review.comments must be a list when present")
                else:
                    for i, comment in enumerate(review["comments"]):
                        if not isinstance(comment, dict):
                            fail(f"review.comments[{i}] must be an object")
                            continue
                        if not is_nonempty_str(comment.get("summary")):
                            fail(f"review.comments[{i}].summary must be a non-empty string")
                        # `file`/`line` pin a comment to a specific spot; a comment with
                        # no single file/line to point at (e.g. a suite-wide coverage
                        # note) legitimately carries an explicit null for either, seen
                        # throughout the existing board -- only flag a wrong-typed,
                        # non-null value.
                        if "file" in comment and comment["file"] is not None and not isinstance(
                            comment["file"], str
                        ):
                            fail(f"review.comments[{i}].file must be a string or null when present")
                        if "line" in comment and comment["line"] is not None and not isinstance(
                            comment["line"], int
                        ):
                            fail(f"review.comments[{i}].line must be an integer or null when present")

    if "pr_decision" in data:
        pr_decision = data["pr_decision"]
        if not isinstance(pr_decision, dict):
            fail("field 'pr_decision' must be an object")
        else:
            if "confirmed_at" in pr_decision and not is_nonempty_str(pr_decision["confirmed_at"]):
                fail("pr_decision.confirmed_at must be a non-empty string when present")
            if "verdict" in pr_decision and pr_decision["verdict"] != "merge":
                fail(
                    "pr_decision.verdict must be 'merge' (per CLAUDE.md, this field "
                    f"is written only on a merge decision), got {pr_decision['verdict']!r}"
                )

    return violations


def collect_task_files() -> list[Path]:
    active = sorted(p for p in TASKS_DIR.glob("*.json") if p.name != "index.json")
    done = sorted(DONE_DIR.glob("*.json")) if DONE_DIR.exists() else []
    return active + done


def run() -> list[Violation]:
    violations: list[Violation] = []

    index_data, err = load_json(INDEX_PATH)
    if err is not None:
        return [Violation("index.json", f"could not parse {INDEX_PATH}: {err}")]
    if not isinstance(index_data, dict) or not isinstance(index_data.get("tasks"), list):
        return [Violation("index.json", "top-level 'tasks' field is missing or not a list")]

    # Keyed by id -> list of entries, not a single entry: two rows in index.json
    # can share an id (mirrors the tasks_by_id fix below for duplicate task
    # files). Keeping every copy here, rather than letting a later row silently
    # overwrite an earlier one, means the state/path mirror cross-check further
    # down still runs against *each* duplicate independently instead of only
    # whichever row happened to be processed last.
    index_by_id: dict[str, list[dict[str, Any]]] = {}
    for i, entry in enumerate(index_data["tasks"]):
        if not isinstance(entry, dict) or not is_nonempty_str(entry.get("id")):
            violations.append(Violation("index.json", f"tasks[{i}] is missing a valid 'id'"))
            continue
        task_id = entry["id"]
        if task_id in index_by_id:
            violations.append(Violation("index.json", f"duplicate id {task_id!r} in tasks list"))
        index_by_id.setdefault(task_id, []).append(entry)
        for field in ("area", "skill", "state", "path"):
            if field not in entry:
                violations.append(Violation(task_id, f"index.json entry is missing '{field}'"))
        index_state = entry.get("state")
        if is_invalid_str_choice(index_state, VALID_STATES):
            violations.append(
                Violation(task_id, f"index.json entry has invalid state {index_state!r}")
            )

    # Keyed by id -> list of (data, path), not a single tuple: two files can share
    # an id (e.g. a stale copy left behind after an incomplete `git mv` to
    # docs/tasks/done/). Keeping every copy here, rather than letting a later one
    # silently overwrite an earlier one, means the depends_on/index-mirror
    # cross-checks below still run against *each* duplicate independently instead
    # of only whichever file happened to be processed last.
    tasks_by_id: dict[str, list[tuple[dict[str, Any], Path]]] = {}
    all_ids: set[str] = set()
    for path in collect_task_files():
        rel = str(path.relative_to(REPO_ROOT))
        data, err = load_json(path)
        if err is not None:
            violations.append(Violation(rel, f"invalid JSON: {err}"))
            continue
        if not isinstance(data, dict):
            violations.append(Violation(rel, "top-level JSON value must be an object"))
            continue

        task_id = data["id"] if is_nonempty_str(data.get("id")) else path.stem
        if task_id in all_ids:
            violations.append(
                Violation(task_id, f"duplicate task id also found at {rel} elsewhere on the board")
            )
        all_ids.add(task_id)
        tasks_by_id.setdefault(task_id, []).append((data, path))

        violations.extend(check_task_shape(task_id, data, path.stem))

        is_done_dir = DONE_DIR in path.parents
        state = data.get("state")
        if state == "done" and not is_done_dir:
            violations.append(
                Violation(task_id, f"state is 'done' but file is not under docs/tasks/done/ ({rel})")
            )
        if state != "done" and is_done_dir:
            violations.append(
                Violation(
                    task_id,
                    f"file is under docs/tasks/done/ but state is {state!r}, not 'done' ({rel})",
                )
            )

    for task_id, entries in tasks_by_id.items():
        for data, _path in entries:
            depends_on = data.get("depends_on")
            if not isinstance(depends_on, list):
                continue
            for dep in depends_on:
                if isinstance(dep, str) and dep not in all_ids:
                    violations.append(
                        Violation(task_id, f"depends_on references unknown task id {dep!r}")
                    )

    for task_id, entries in tasks_by_id.items():
        for data, path in entries:
            rel_path = str(path.relative_to(REPO_ROOT))
            index_entries = index_by_id.get(task_id)
            if not index_entries:
                violations.append(
                    Violation(
                        task_id, f"file exists at {rel_path} but has no entry in docs/tasks/index.json"
                    )
                )
                continue
            # Cross-check against every index.json row sharing this id, not just
            # one -- otherwise a genuine drift on an earlier duplicate row is
            # silently skipped whenever a later, non-drifted duplicate happens to
            # be the one a single-entry lookup would have returned.
            for entry in index_entries:
                if entry.get("state") != data.get("state"):
                    violations.append(
                        Violation(
                            task_id,
                            f"index.json state ({entry.get('state')!r}) does not match the task "
                            f"file's own state ({data.get('state')!r}) at {rel_path}",
                        )
                    )
                if entry.get("path") != rel_path:
                    violations.append(
                        Violation(
                            task_id,
                            f"index.json path ({entry.get('path')!r}) does not match the task's "
                            f"actual file location ({rel_path!r})",
                        )
                    )

    for task_id in index_by_id:
        if task_id not in tasks_by_id:
            violations.append(
                Violation(task_id, "listed in docs/tasks/index.json but no task file found on the board")
            )

    return violations


def main() -> int:
    violations = run()
    if violations:
        print(f"FAIL: {len(violations)} task board violation(s) found:\n")
        for violation in sorted(violations, key=lambda v: v.task_id):
            print(f"  {violation}")
        print(
            f"\n{len(violations)} violation(s) across "
            f"{len({v.task_id for v in violations})} task(s)/file(s)."
        )
        return 1

    task_count = len(collect_task_files())
    print(f"OK: validated {task_count} task file(s) under docs/tasks/ against CLAUDE.md's invariants -- no violations found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
