"""Stdlib-only regression tests for scripts/validate_tasks.py.

Matches that script's own zero-setup philosophy (see its module docstring and
docs/tasks/done/scripts-validate-tasks.json's `decisions` entry): no pytest,
no venv, nothing beyond the standard library. Run directly:

    python3 scripts/tests/test_validate_tasks.py

or via unittest's discovery:

    python3 -m unittest discover -s scripts/tests -p 'test_*.py'
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "validate_tasks.py"


def _load_module() -> Any:
    # Loaded dynamically (rather than a normal package import) so this test
    # runs standalone via `python3 scripts/tests/test_validate_tasks.py` with
    # no __init__.py/sys.path setup needed -- consistent with the script under
    # test being stdlib-only and install-free. Typed `Any`: mypy can't see the
    # dynamically-loaded module's attributes (REPO_ROOT, TASKS_DIR, ...), and
    # this file isn't part of the enforced static-analysis gate anyway (same
    # precedent as backend/scripts/'s own tooling scripts).
    spec = importlib.util.spec_from_file_location("validate_tasks_under_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vt: Any = _load_module()


def _valid_task(**overrides: Any) -> dict[str, Any]:
    task: dict[str, Any] = {
        "id": "sample-task",
        "title": "Sample task",
        "area": "tooling",
        "skill": None,
        "state": "planned",
        "depends_on": [],
        "references": [],
        "description": "A sample task used only by validate_tasks.py's own tests.",
        "checklist": [{"step": "Do the thing", "done": False}],
    }
    task.update(overrides)
    return task


def _valid_index_entry(task: dict[str, Any], path: str) -> dict[str, Any]:
    return {
        "id": task["id"],
        "area": task["area"],
        "skill": task["skill"],
        "state": task["state"],
        "path": path,
    }


class BoardFixture:
    """Builds a scratch docs/tasks/ tree and points the module under test at it."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.tasks_dir = root / "docs" / "tasks"
        self.done_dir = self.tasks_dir / "done"
        self.tasks_dir.mkdir(parents=True)
        self.done_dir.mkdir()
        self.index_entries: list[dict[str, Any]] = []

    def add_task(self, task: dict[str, Any], done: bool = False) -> Path:
        directory = self.done_dir if done else self.tasks_dir
        path = directory / f"{task['id']}.json"
        path.write_text(json.dumps(task))
        rel = str(path.relative_to(self.root))
        self.index_entries.append(_valid_index_entry(task, rel))
        return path

    def write_index(self, entries: list[dict[str, Any]] | None = None) -> None:
        index_path = self.tasks_dir / "index.json"
        payload = entries if entries is not None else self.index_entries
        index_path.write_text(json.dumps({"tasks": payload}))

    def apply(self) -> None:
        # run()/check_task_shape() report file paths relative to REPO_ROOT, so
        # that must move along with TASKS_DIR/DONE_DIR/INDEX_PATH -- otherwise
        # Path.relative_to(REPO_ROOT) raises ValueError against the real repo
        # root for every path under this scratch tree.
        vt.REPO_ROOT = self.root
        vt.TASKS_DIR = self.tasks_dir
        vt.DONE_DIR = self.done_dir
        vt.INDEX_PATH = self.tasks_dir / "index.json"


class ValidateTasksTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.tmp_path = Path(tmpdir.name)

        original = (vt.REPO_ROOT, vt.TASKS_DIR, vt.DONE_DIR, vt.INDEX_PATH)

        def restore() -> None:
            vt.REPO_ROOT, vt.TASKS_DIR, vt.DONE_DIR, vt.INDEX_PATH = original

        self.addCleanup(restore)

    def board(self) -> BoardFixture:
        return BoardFixture(self.tmp_path)

    def violation_messages(self) -> list[str]:
        return [str(v) for v in vt.run()]

    # -- clean pass -----------------------------------------------------

    def test_clean_board_has_no_violations(self) -> None:
        b = self.board()
        b.add_task(_valid_task())
        b.write_index()
        b.apply()
        self.assertEqual(vt.run(), [])

    def test_clean_done_task_has_no_violations(self) -> None:
        b = self.board()
        task = _valid_task(id="done-task", state="done")
        b.add_task(task, done=True)
        b.write_index()
        b.apply()
        self.assertEqual(vt.run(), [])

    # -- required shape ---------------------------------------------------

    def test_missing_required_field_is_flagged(self) -> None:
        b = self.board()
        task = _valid_task()
        del task["description"]
        b.add_task(task)
        b.write_index()
        b.apply()
        messages = self.violation_messages()
        self.assertTrue(any("missing required field 'description'" in m for m in messages), messages)

    def test_wrong_type_field_is_flagged(self) -> None:
        b = self.board()
        task = _valid_task(title=123)
        b.add_task(task)
        b.write_index()
        b.apply()
        messages = self.violation_messages()
        self.assertTrue(any("field 'title' must be a str" in m for m in messages), messages)

    def test_invalid_state_value_is_flagged(self) -> None:
        b = self.board()
        task = _valid_task(state="bogus")
        b.add_task(task)
        b.write_index()
        b.apply()
        messages = self.violation_messages()
        self.assertTrue(any("'state' value 'bogus' is not one of" in m for m in messages), messages)

    def test_id_filename_mismatch_is_flagged(self) -> None:
        b = self.board()
        task = _valid_task(id="mismatched-id")
        path = b.tasks_dir / "sample-task.json"
        path.write_text(json.dumps(task))
        b.write_index([_valid_index_entry({**task, "id": "sample-task"}, "docs/tasks/sample-task.json")])
        b.apply()
        messages = self.violation_messages()
        self.assertTrue(any("does not match its filename" in m for m in messages), messages)

    # -- checklist/decisions/questions ------------------------------------

    def test_checklist_item_missing_step_is_flagged(self) -> None:
        b = self.board()
        task = _valid_task(checklist=[{"done": False}])
        b.add_task(task)
        b.write_index()
        b.apply()
        messages = self.violation_messages()
        self.assertTrue(
            any("checklist[0].step must be a non-empty string" in m for m in messages), messages
        )

    def test_decision_missing_rationale_is_flagged(self) -> None:
        b = self.board()
        task = _valid_task(decisions=[{"decision": "did the thing"}])
        b.add_task(task)
        b.write_index()
        b.apply()
        messages = self.violation_messages()
        self.assertTrue(
            any("decisions[0].rationale must be a non-empty string" in m for m in messages), messages
        )

    def test_decision_bare_restatement_is_flagged(self) -> None:
        b = self.board()
        task = _valid_task(decisions=[{"decision": "Changed X", "rationale": "changed x"}])
        b.add_task(task)
        b.write_index()
        b.apply()
        messages = self.violation_messages()
        self.assertTrue(any("must not just restate" in m for m in messages), messages)

    def test_question_missing_context_is_flagged(self) -> None:
        b = self.board()
        task = _valid_task(questions=[{"question": "what now?"}])
        b.add_task(task)
        b.write_index()
        b.apply()
        messages = self.violation_messages()
        self.assertTrue(
            any("questions[0].context must be a non-empty string" in m for m in messages), messages
        )

    # -- depends_on -----------------------------------------------------

    def test_depends_on_unknown_id_is_flagged(self) -> None:
        b = self.board()
        task = _valid_task(depends_on=["does-not-exist"])
        b.add_task(task)
        b.write_index()
        b.apply()
        messages = self.violation_messages()
        self.assertTrue(
            any("depends_on references unknown task id 'does-not-exist'" in m for m in messages),
            messages,
        )

    # -- index.json mirror / done-path invariant -------------------------

    def test_index_state_drift_is_flagged(self) -> None:
        b = self.board()
        task = _valid_task()
        b.add_task(task)
        b.write_index(
            [_valid_index_entry({**task, "state": "implementing"}, "docs/tasks/sample-task.json")]
        )
        b.apply()
        messages = self.violation_messages()
        self.assertTrue(
            any("index.json state" in m and "does not match" in m for m in messages), messages
        )

    def test_index_path_drift_is_flagged(self) -> None:
        b = self.board()
        task = _valid_task()
        b.add_task(task)
        b.write_index([_valid_index_entry(task, "docs/tasks/wrong-path.json")])
        b.apply()
        messages = self.violation_messages()
        self.assertTrue(
            any("index.json path" in m and "does not match" in m for m in messages), messages
        )

    def test_done_state_outside_done_dir_is_flagged(self) -> None:
        b = self.board()
        task = _valid_task(state="done")
        b.add_task(task, done=False)
        b.write_index()
        b.apply()
        messages = self.violation_messages()
        self.assertTrue(any("but file is not under docs/tasks/done/" in m for m in messages), messages)

    def test_non_done_state_inside_done_dir_is_flagged(self) -> None:
        b = self.board()
        task = _valid_task(state="planned")
        b.add_task(task, done=True)
        b.write_index()
        b.apply()
        messages = self.violation_messages()
        self.assertTrue(any("is under docs/tasks/done/ but state is" in m for m in messages), messages)

    def test_missing_index_entry_is_flagged(self) -> None:
        b = self.board()
        task = _valid_task()
        b.add_task(task)
        b.write_index([])
        b.apply()
        messages = self.violation_messages()
        self.assertTrue(any("has no entry in docs/tasks/index.json" in m for m in messages), messages)

    def test_index_entry_without_task_file_is_flagged(self) -> None:
        b = self.board()
        task = _valid_task()
        b.write_index([_valid_index_entry(task, "docs/tasks/sample-task.json")])
        b.apply()
        messages = self.violation_messages()
        self.assertTrue(any("no task file found on the board" in m for m in messages), messages)

    # -- non-scalar fields: regression coverage for the PR #113 crash fix --

    def test_non_scalar_test_verdict_does_not_crash(self) -> None:
        b = self.board()
        task = _valid_task(test={"verdict": ["pass"]})
        b.add_task(task)
        b.write_index()
        b.apply()
        messages = self.violation_messages()  # must not raise TypeError
        self.assertTrue(any("test.verdict must be one of" in m for m in messages), messages)

    def test_non_scalar_review_verdict_does_not_crash(self) -> None:
        b = self.board()
        task = _valid_task(review={"verdict": {"nested": "dict"}})
        b.add_task(task)
        b.write_index()
        b.apply()
        messages = self.violation_messages()
        self.assertTrue(any("review.verdict must be one of" in m for m in messages), messages)

    def test_non_scalar_gap_severity_does_not_crash(self) -> None:
        b = self.board()
        task = _valid_task(
            test={"gap_analysis": [{"summary": "x", "severity": ["blocker"], "evidence": "y"}]}
        )
        b.add_task(task)
        b.write_index()
        b.apply()
        messages = self.violation_messages()
        self.assertTrue(any("gap_analysis[0].severity must be one of" in m for m in messages), messages)

    def test_non_scalar_index_state_does_not_crash(self) -> None:
        b = self.board()
        task = _valid_task()
        b.add_task(task)
        b.write_index([_valid_index_entry({**task, "state": ["done"]}, "docs/tasks/sample-task.json")])
        b.apply()
        messages = self.violation_messages()
        self.assertTrue(any("index.json entry has invalid state" in m for m in messages), messages)

    # -- duplicate ids ----------------------------------------------------

    def test_duplicate_id_cross_checks_both_copies(self) -> None:
        b = self.board()
        task_a = _valid_task(depends_on=["missing-a"])
        (b.tasks_dir / "sample-task.json").write_text(json.dumps(task_a))
        task_b = {**_valid_task(depends_on=["missing-b"]), "state": "done"}
        (b.done_dir / "sample-task.json").write_text(json.dumps(task_b))
        b.write_index([_valid_index_entry(task_a, "docs/tasks/sample-task.json")])
        b.apply()
        messages = self.violation_messages()
        self.assertTrue(any("duplicate task id" in m for m in messages), messages)
        self.assertTrue(any("unknown task id 'missing-a'" in m for m in messages), messages)
        self.assertTrue(any("unknown task id 'missing-b'" in m for m in messages), messages)

    def test_duplicate_index_entry_cross_checks_both_rows(self) -> None:
        # Regression test for the index_by_id overwrite-on-duplicate bug: two
        # rows in index.json share an id, one matching the real task file's
        # state and one stale/drifted. Before the fix, index_by_id[task_id] =
        # entry (a single assignment, not append-to-list) meant only whichever
        # row was processed last survived, so the earlier row's own drift from
        # the task file was never independently reported -- only the generic
        # "duplicate id ... in tasks list" violation fired. After the fix, the
        # mirror cross-check loop runs against every row sharing that id, so
        # the drifted row's mismatch is reported too.
        b = self.board()
        task = _valid_task(state="implementing")
        b.add_task(task)
        stale_row = _valid_index_entry({**task, "state": "planned"}, "docs/tasks/sample-task.json")
        current_row = _valid_index_entry(task, "docs/tasks/sample-task.json")
        b.write_index([stale_row, current_row])
        b.apply()
        messages = self.violation_messages()
        self.assertTrue(
            any("duplicate id 'sample-task' in tasks list" in m for m in messages), messages
        )
        self.assertTrue(
            any(
                "index.json state ('planned') does not match the task file's own state "
                "('implementing')" in m
                for m in messages
            ),
            messages,
        )


class RealBoardSmokeTest(unittest.TestCase):
    """Runs the actual script (as a subprocess, so its own `if __name__ ==
    "__main__"` / sys.exit(main()) path is exercised too) against this repo's
    real docs/tasks/ board."""

    def test_current_board_validates_cleanly(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OK: validated", result.stdout)


if __name__ == "__main__":
    unittest.main()
