"""Stdlib-only regression tests for scripts/check_profit_target_wording.py.

Matches scripts/validate_tasks.py's own zero-setup testing philosophy (see
scripts/tests/test_validate_tasks.py): no pytest, no venv, nothing beyond the
standard library. Run directly:

    python3 scripts/tests/test_check_profit_target_wording.py

or via unittest's discovery:

    python3 -m unittest discover -s scripts/tests -p 'test_*.py'

These tests exist because the guard itself only earns its keep if it would actually
have caught the bug it's named after -- see
docs/tasks/backend-profit-target-weekly-channel-followups.json's checklist item 1.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, ClassVar

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "check_profit_target_wording.py"


def _load_module() -> Any:
    # Loaded dynamically, same reasoning as test_validate_tasks.py's own
    # `_load_module` -- runs standalone with no package/sys.path setup, consistent
    # with the script under test being stdlib-only and install-free. Typed `Any`:
    # mypy can't see the dynamically-loaded module's attributes, and this file isn't
    # part of the enforced static-analysis gate anyway (same precedent as
    # backend/scripts/'s own tooling scripts and test_validate_tasks.py itself).
    spec = importlib.util.spec_from_file_location("check_profit_target_wording_under_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cptw: Any = _load_module()


class FakeRepo:
    """A scratch directory standing in for REPO_ROOT, so tests never touch the
    real repository tree."""

    def __init__(self, root: Path) -> None:
        self.root = root
        (self.root / "docs" / "tasks").mkdir(parents=True)
        (self.root / "docs" / "ideas.md").write_text("scratch pad, not scanned")

    def write(self, rel_path: str, content: str) -> Path:
        path = self.root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path


class CheckProfitTargetWordingTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.tmp_path = Path(tmpdir.name)
        self.repo = FakeRepo(self.tmp_path)

        original = (cptw.REPO_ROOT, cptw._EXCLUDED_PATHS)

        def restore() -> None:
            cptw.REPO_ROOT, cptw._EXCLUDED_PATHS = original

        self.addCleanup(restore)

        cptw.REPO_ROOT = self.tmp_path
        cptw._EXCLUDED_PATHS = {
            self.tmp_path / "docs" / "tasks",
            self.tmp_path / "docs" / "ideas.md",
        }

    # -- check_banned_patterns: the negative, repo-wide check ------------------

    def test_clean_file_has_no_banned_pattern_violations(self) -> None:
        path = self.repo.write(
            "frontend/src/utils/example.ts",
            "The channel candidate comes from the weekly chart's Autoenvelope/channel height.",
        )
        self.assertEqual(cptw.check_banned_patterns([path]), [])

    def test_todays_autoenvelope_is_flagged(self) -> None:
        # The exact pre-fix wording backend/app/api/schemas.py and two frontend
        # copy locations regressed to in PR #222's review rounds.
        path = self.repo.write(
            "frontend/src/utils/example.ts",
            "Current price + 30% of today's Autoenvelope/channel height.",
        )
        violations = cptw.check_banned_patterns([path])
        self.assertEqual(len(violations), 1)
        self.assertIn("example.ts:1", violations[0])

    def test_that_days_autoenvelope_is_flagged(self) -> None:
        # methodologyContent.ts's own 6th-instance regression used this exact phrasing.
        path = self.repo.write(
            "frontend/src/features/methodology/data/example.ts",
            "current price + 30% of that day's Autoenvelope/channel height.",
        )
        violations = cptw.check_banned_patterns([path])
        self.assertEqual(len(violations), 1)

    def test_100_days_of_history_is_flagged(self) -> None:
        path = self.repo.write(
            "backend/app/api/example.py",
            "null for a young ticker with under ~100 days of history.",
        )
        violations = cptw.check_banned_patterns([path])
        self.assertEqual(len(violations), 1)

    def test_curly_apostrophe_variant_is_flagged(self) -> None:
        # Frontend/docs prose uses a typographic apostrophe (’); backend Python
        # docstrings use a straight one -- both must be caught.
        path = self.repo.write(
            "frontend/src/utils/example.ts",
            "today’s Autoenvelope/channel height",
        )
        violations = cptw.check_banned_patterns([path])
        self.assertEqual(len(violations), 1)

    def test_banned_pattern_split_across_lines_via_implicit_concatenation_is_flagged(self) -> None:
        # backend/app/api/schemas.py's own IndicatorsOut field descriptions (ATR, ADX,
        # +DI/-DI, channel_upper/channel_lower, RSI) all wrap a long Field
        # `description=(...)` across two adjacent string literals joined by Python's
        # implicit string concatenation. A banned phrase split across that same join
        # must still be caught, not silently missed by a naive per-line scan.
        path = self.repo.write(
            "backend/app/api/example.py",
            "description=(\n"
            "    \"Current price + 30% of today's \"\n"
            "    \"Autoenvelope/channel height.\"\n"
            ")\n",
        )
        violations = cptw.check_banned_patterns([path])
        self.assertEqual(len(violations), 1)

    def test_weekly_wording_is_not_flagged(self) -> None:
        path = self.repo.write(
            "frontend/src/utils/example.ts",
            "the channel candidate is computed from ~100 weeks of weekly history.",
        )
        self.assertEqual(cptw.check_banned_patterns([path]), [])

    def test_docs_tasks_directory_is_excluded_from_scanning(self) -> None:
        # Task JSON's own decisions/review text is an intentionally-preserved
        # historical record (see this task's own description) -- it legitimately
        # quotes the stale wording verbatim when describing the finding.
        self.repo.write(
            "docs/tasks/some-task.json",
            '{"decisions": [{"decision": "was today\'s Autoenvelope, fixed to weekly"}]}',
        )
        scanned = cptw._iter_scanned_files()
        self.assertFalse(any("docs/tasks" in str(p) for p in scanned))

    def test_docs_ideas_md_is_excluded_from_scanning(self) -> None:
        self.repo.write(
            "docs/ideas.md",
            "computed entirely off daily data -- today's Autoenvelope/channel height",
        )
        scanned = cptw._iter_scanned_files()
        self.assertFalse(any(str(p).endswith("docs/ideas.md") for p in scanned))

    def test_test_files_are_excluded_from_scanning(self) -> None:
        # profitTargetHelpText.test.ts and both metricHelpContent.test.ts files
        # intentionally reference the banned wording as a regex literal inside a
        # `not.toMatch(...)` negative assertion -- that's this bug class already
        # being guarded at the unit-test level, not a live regression.
        self.repo.write(
            "frontend/src/utils/profitTargetHelpText.test.ts",
            "expect(x).not.toMatch(/today's Autoenvelope/)",
        )
        self.repo.write(
            "backend/tests/unit/test_example.py",
            "# regression test for the old \"today's Autoenvelope\" wording",
        )
        scanned_names = {p.name for p in cptw._iter_scanned_files()}
        self.assertNotIn("profitTargetHelpText.test.ts", scanned_names)
        self.assertNotIn("test_example.py", scanned_names)

    def test_non_scanned_extension_is_ignored(self) -> None:
        self.repo.write("backend/app/data.json", "today's Autoenvelope/channel height")
        scanned = cptw._iter_scanned_files()
        self.assertEqual(scanned, [])

    def test_excluded_directory_is_pruned_during_traversal(self) -> None:
        # _iter_scanned_files walks via os.walk and prunes _EXCLUDED_DIR_NAMES as it
        # goes (rather than enumerating every file underneath first and filtering
        # afterwards) -- functionally this should still simply exclude any file under
        # one of those directories, same as before the traversal was changed.
        self.repo.write("node_modules/some-package/index.ts", "today's Autoenvelope/channel height")
        self.repo.write(".venv/lib/example.py", "today's Autoenvelope/channel height")
        scanned = cptw._iter_scanned_files()
        self.assertEqual(scanned, [])

    # -- check_known_files_mention_weekly: the positive, per-file check ---------

    # Trailing content satisfying each known entry's own end_anchor, so a "correctly
    # written" fixture file is bounded the same way a real file is -- otherwise
    # _extract_region's own end-anchor-missing fallback (see
    # test_anchor_end_not_found_is_flagged below) would trip on every fixture that
    # has an end_anchor at all, not just the one deliberately testing that case.
    _END_ANCHOR_TRAILING_CONTENT: ClassVar[dict[str, str]] = {
        r"\nexport const \w": "\nexport const nextThing = {}\n",
        r"\n\s*id: '": "\n  id: 'next-thing'\n",
    }

    def _write_all_known_files_correctly(self) -> None:
        correct_content = "profit target channel: weekly chart's Autoenvelope/channel height (Tradebill)"
        for rel_path, start_anchor, end_anchor in cptw._KNOWN_PROFIT_TARGET_CHANNEL_FILES:
            content = f"{start_anchor}\n{correct_content}" if start_anchor else correct_content
            if end_anchor:
                content += self._END_ANCHOR_TRAILING_CONTENT[end_anchor]
            self.repo.write(rel_path, content)

    def test_all_known_files_present_and_correct_has_no_violations(self) -> None:
        self._write_all_known_files_correctly()
        self.assertEqual(cptw.check_known_files_mention_weekly(self.tmp_path), [])

    def test_missing_known_file_is_flagged(self) -> None:
        self.assertTrue(cptw.check_known_files_mention_weekly(self.tmp_path))

    def test_known_file_missing_weekly_wording_is_flagged(self) -> None:
        self._write_all_known_files_correctly()
        # Regress exactly one known file back to daily-only wording (no anchors on
        # this one, so the whole file is scanned).
        self.repo.write(
            "backend/app/portfolio/profit_target.py",
            "profit target channel: today's Autoenvelope/channel height (Tradebill)",
        )
        violations = cptw.check_known_files_mention_weekly(self.tmp_path)
        self.assertTrue(any("profit_target.py" in v for v in violations))

    def test_plural_weeks_alone_satisfies_the_weekly_check(self) -> None:
        # _WEEKLY_RE must recognize the plural noun "weeks" on its own, not just the
        # adjective "weekly" -- e.g. a warm-up window phrased as "~100 weeks of price
        # history" with no separate "weekly" nearby.
        self._write_all_known_files_correctly()
        self.repo.write(
            "backend/app/portfolio/profit_target.py",
            "profit target channel: Autoenvelope/channel height over ~100 weeks of price "
            "history (Tradebill)",
        )
        violations = cptw.check_known_files_mention_weekly(self.tmp_path)
        self.assertEqual([v for v in violations if "profit_target.py" in v], [])

    def test_hyphenated_profit_target_satisfies_context(self) -> None:
        # _PROFIT_TARGET_CONTEXT_RE must match the hyphenated "profit-target" form --
        # the literal text of methodologyContent.ts's own `id: 'profit-target'`
        # start_anchor -- not just the space/underscore forms.
        self._write_all_known_files_correctly()
        self.repo.write(
            "backend/app/portfolio/profit_target.py",
            "profit-target channel: weekly chart's Autoenvelope/channel height",
        )
        violations = cptw.check_known_files_mention_weekly(self.tmp_path)
        self.assertEqual([v for v in violations if "profit_target.py" in v], [])

    def test_known_file_with_no_channel_mention_at_all_is_flagged(self) -> None:
        self._write_all_known_files_correctly()
        self.repo.write("backend/app/portfolio/profit_target.py", "nothing relevant here")
        violations = cptw.check_known_files_mention_weekly(self.tmp_path)
        self.assertTrue(
            any("profit_target.py" in v and "no Autoenvelope/channel-height" in v for v in violations)
        )

    def test_anchor_scoping_ignores_unrelated_daily_metric_elsewhere_in_file(self) -> None:
        # Regression test for the false-positive this guard's own anchor scoping
        # exists to avoid: a file (like the real
        # features/portfolio/components/metricHelpContent.ts) that correctly
        # describes profit_target's WEEKLY channel, but ALSO separately, correctly,
        # describes a completely different DAILY channel metric (trade grading)
        # nearby -- that second, unrelated description must not trip this check
        # just for lacking "weekly" itself.
        self._write_all_known_files_correctly()
        self.repo.write(
            "frontend/src/features/portfolio/components/metricHelpContent.ts",
            "export const profitTargetHelp = {\n"
            "  definition: 'profit target: weekly chart Autoenvelope/channel height (Tradebill)',\n"
            "}\n"
            "export const tradeGradeHelp = {\n"
            "  definition: 'entry day Autoenvelope/channel height, ~100-bar warm-up window',\n"
            "}\n",
        )
        violations = cptw.check_known_files_mention_weekly(self.tmp_path)
        self.assertEqual(
            [v for v in violations if "features/portfolio/components/metricHelpContent.ts" in v], []
        )

    def test_anchor_end_not_found_is_flagged(self) -> None:
        # Regression test for the asymmetry this guard used to have: a failed
        # start_anchor raised an explicit violation, but a failed end_anchor silently
        # fell back to scanning to end of file with no signal at all.
        self._write_all_known_files_correctly()
        self.repo.write(
            "frontend/src/features/portfolio/components/metricHelpContent.ts",
            "export const profitTargetHelp = {\n"
            "  definition: 'profit target: weekly chart Autoenvelope/channel height (Tradebill)',\n"
            "}\n",
        )
        violations = cptw.check_known_files_mention_weekly(self.tmp_path)
        self.assertTrue(
            any(
                "features/portfolio/components/metricHelpContent.ts" in v and "end anchor" in v
                for v in violations
            )
        )

    def test_anchor_start_not_found_is_flagged(self) -> None:
        self._write_all_known_files_correctly()
        self.repo.write(
            "frontend/src/features/portfolio/components/metricHelpContent.ts",
            "no profitTargetHelp export in this file anymore",
        )
        violations = cptw.check_known_files_mention_weekly(self.tmp_path)
        self.assertTrue(
            any(
                "features/portfolio/components/metricHelpContent.ts" in v and "start anchor" in v
                for v in violations
            )
        )


class RealRepoSmokeTest(unittest.TestCase):
    """Runs the actual script (as a subprocess, so its own `if __name__ ==
    "__main__"` / sys.exit(main()) path is exercised too) against this repo's real
    tree -- confirms the guard is currently clean, not just that its logic works
    against synthetic fixtures."""

    def test_real_repo_is_currently_clean(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no stale daily-channel wording found", result.stdout)


if __name__ == "__main__":
    unittest.main()
