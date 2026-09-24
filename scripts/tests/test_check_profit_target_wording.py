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

    def test_unrelated_quoted_sentences_across_a_line_break_in_md_are_not_flagged(self) -> None:
        # PR #226 review finding: the implicit-concatenation join must not be
        # applied to non-Python files at all -- two entirely unrelated,
        # individually-clean sentences in a .md file that merely happen to have a
        # quote character just before and just after a line break must not be
        # merged into one string and false-flagged.
        path = self.repo.write(
            "docs/example.md",
            "Some analyst said \"today's\"\n\"Autoenvelope reading\" is unrelated.\n",
        )
        self.assertEqual(cptw.check_banned_patterns([path]), [])

    def test_unrelated_bare_string_statements_in_py_are_not_flagged(self) -> None:
        # PR #226 review finding: two unrelated, syntactically-separate
        # string-literal statements in a .py file (not real implicit
        # concatenation of one expression -- there's no open bracket joining
        # them) must not be merged just because one ends and the next begins with
        # the same quote character across a line break.
        path = self.repo.write(
            "backend/app/api/example_unrelated.py",
            "x = \"foo today's \"\n\"Autoenvelope/channel height.\"\n",
        )
        self.assertEqual(cptw.check_banned_patterns([path]), [])

    def test_ordinary_line_break_without_string_concatenation_is_not_flagged_in_md(self) -> None:
        # PR #226 review finding (round 3): the negative check must never bridge an
        # ORDINARY physical line break -- no quotes, no implicit string
        # concatenation involved at all, just a sentence that happens to wrap --
        # regardless of file type. Verified as a genuine regression on the round-3
        # branch (whole-text `\s+` matching over `pattern.finditer(joined)`), not
        # present on main.
        path = self.repo.write(
            "docs/example_wrap.md",
            "It happened that day's\nAutoenvelope reading looked odd.\n",
        )
        self.assertEqual(cptw.check_banned_patterns([path]), [])

    def test_ordinary_line_break_without_string_concatenation_is_not_flagged_in_ts(self) -> None:
        # Same finding as above, for a .ts file.
        path = self.repo.write(
            "frontend/src/utils/example_wrap.ts",
            "// The analyst said today's\n// Autoenvelope feature shipped fine.\n",
        )
        self.assertEqual(cptw.check_banned_patterns([path]), [])

    def test_ordinary_line_break_in_a_py_docstring_is_not_flagged(self) -> None:
        # A single triple-quoted docstring that merely wraps across two lines is
        # not implicit string concatenation (only one STRING token exists, so no
        # run is ever formed) -- must not be flagged just because the words split
        # at an ordinary line break within it. This must still hold in .py files
        # specifically, since that's the file type the join logic runs against.
        path = self.repo.write(
            "backend/app/api/example_docstring.py",
            '"""\n'
            "The analyst said today's\n"
            "Autoenvelope feature shipped fine.\n"
            '"""\n',
        )
        self.assertEqual(cptw.check_banned_patterns([path]), [])

    def test_line_numbers_after_an_earlier_join_stay_accurate_for_a_later_violation(self) -> None:
        # PR #226 review finding (round 3): a real implicit-concatenation join
        # earlier in the file must not shift the reported line number of an
        # unrelated, later real violation -- the join must never collapse a
        # physical line or otherwise desync line-number reporting.
        path = self.repo.write(
            "backend/app/api/example_multiline.py",
            "import os\n"
            "\n"
            "value = (\n"
            '    "prefix "\n'
            '    "suffix"\n'
            ")\n"
            'STALE = "~100 days of history"\n',
        )
        violations = cptw.check_banned_patterns([path])
        self.assertEqual(len(violations), 1)
        self.assertIn("example_multiline.py:7", violations[0])

    def test_run_line_number_accounts_for_a_multiline_member_literal(self) -> None:
        # PR #226 review finding (round 4): a run containing a multi-line token (a
        # triple-quoted string implicitly concatenated to another literal) must
        # report the real source line the matched text falls on, not the token's
        # opening line. Here the triple-quoted string opens on line 2 but the
        # banned phrase's "today's" half only appears on line 3, joined to
        # "Autoenvelope" on line 4 -- the violation must be reported at line 3
        # (where the flagged text actually starts), not line 2.
        path = self.repo.write(
            "backend/app/api/example_multiline_token.py",
            "x = (\n"
            '    """line one\n'
            "    mentions today's \"\"\"\n"
            '    "Autoenvelope"\n'
            ")\n",
        )
        violations = cptw.check_banned_patterns([path])
        self.assertEqual(len(violations), 1)
        self.assertIn("example_multiline_token.py:3", violations[0])

    def test_phrase_entirely_within_one_run_member_is_not_double_reported(self) -> None:
        # PR #226 review finding (round 4): a banned phrase sitting entirely within
        # ONE member literal of an implicit-concatenation run (never actually
        # split across the join) must be reported once -- by the ordinary per-line
        # scan -- not a second time by the run-based scan mislabeled "split across
        # an implicit string concatenation".
        path = self.repo.write(
            "backend/app/api/example_not_split.py",
            "description=(\n"
            "    \"Current price + 30% of today's Autoenvelope, using data \"\n"
            '    "for computation."\n'
            ")\n",
        )
        violations = cptw.check_banned_patterns([path])
        self.assertEqual(len(violations), 1)
        self.assertIn("example_not_split.py:2", violations[0])
        self.assertNotIn("split across an implicit string concatenation", violations[0])

    def test_escaped_newline_within_a_run_piece_reports_the_real_physical_line(self) -> None:
        # PR #226 review finding (round 5): a member literal's line-number
        # computation must count real physical source line breaks, not '\n'
        # characters in its *decoded* value -- those diverge when the literal
        # contains an escape sequence (here a literal `\n` escape) that decodes to
        # a newline character that isn't itself a line break in the source. This
        # piece is entirely on physical line 2 (confirmed via tokenize in the
        # review finding this reproduces); the violation must be reported there,
        # not on line 3 (where the escape-produced newline would wrongly place it
        # if decoded newlines were counted instead of real ones).
        path = self.repo.write(
            "backend/app/api/example_escaped_newline.py",
            "x = (\n"
            "    \"line with escape\\nsequence today's \"\n"
            "    \"Autoenvelope\"\n"
            ")\n",
        )
        violations = cptw.check_banned_patterns([path])
        self.assertEqual(len(violations), 1)
        self.assertIn("example_escaped_newline.py:2", violations[0])

    def test_multiline_piece_within_a_run_is_still_caught_not_missed(self) -> None:
        # PR #226 review finding (round 5 addendum, found via a `code-review` pass):
        # round 4's boundary-crossing guard silently dropped a match entirely when
        # the *matching* piece was itself multi-line (split by its own real
        # embedded newline) AND still participated in a run via concatenation to
        # another piece -- a true false negative, since the per-line scan can't
        # catch a match spanning two physical lines either. The whole banned phrase
        # here sits inside one triple-quoted piece, split only by that piece's own
        # real newline, then concatenated to "trailing" (forming a 2-token run) --
        # this must still be caught (at line 2, where "today's" -- the matched
        # text's start -- physically appears), not silently missed.
        path = self.repo.write(
            "backend/app/api/example_multiline_piece_in_run.py",
            "x = (\n"
            "    \"\"\"today's\n"
            "    Autoenvelope\"\"\"\n"
            "    \"trailing\"\n"
            ")\n",
        )
        violations = cptw.check_banned_patterns([path])
        self.assertEqual(len(violations), 1)
        self.assertIn("example_multiline_piece_in_run.py:2", violations[0])

    def test_tab_escape_before_the_match_does_not_perturb_its_reported_line(self) -> None:
        # Escape-sequence edge case (round 5 follow-through): a non-newline escape
        # (here `\t`) earlier in the same piece changes the raw-to-decoded offset
        # mapping (2 raw characters producing 1 decoded character) but must never
        # be mistaken for a physical line break.
        path = self.repo.write(
            "backend/app/api/example_tab_escape.py",
            "x = (\n"
            "    \"prefix\\ttoday's \"\n"
            "    \"Autoenvelope\"\n"
            ")\n",
        )
        violations = cptw.check_banned_patterns([path])
        self.assertEqual(len(violations), 1)
        self.assertIn("example_tab_escape.py:2", violations[0])

    def test_raw_string_escaped_newline_is_not_miscounted(self) -> None:
        # Escape-sequence edge case (round 5 follow-through): in a raw string
        # literal, `\n` is two literal characters (backslash + n), never a decoded
        # newline -- confirms the offset-tracking decoder's raw-string identity
        # mapping doesn't misattribute a line break here either.
        path = self.repo.write(
            "backend/app/api/example_raw_string.py",
            "x = (\n"
            "    r\"blah\\nmore today's \"\n"
            "    \"Autoenvelope\"\n"
            ")\n",
        )
        violations = cptw.check_banned_patterns([path])
        self.assertEqual(len(violations), 1)
        self.assertIn("example_raw_string.py:2", violations[0])

    def test_multiple_escape_sequences_in_one_piece_report_correct_line(self) -> None:
        # Escape-sequence edge case (round 5 follow-through): several escape
        # sequences of different raw/decoded lengths (a `\t` and a `\n`) before the
        # match, all within one otherwise single-physical-line piece -- the
        # cumulative raw-offset mapping must still land on the piece's own real
        # starting line, not be thrown off by the decoded `\n`'s own extra
        # (non-physical) newline character.
        path = self.repo.write(
            "backend/app/api/example_multiple_escapes.py",
            "x = (\n"
            "    \"a\\tb\\ntoday's \"\n"
            "    \"Autoenvelope\"\n"
            ")\n",
        )
        violations = cptw.check_banned_patterns([path])
        self.assertEqual(len(violations), 1)
        self.assertIn("example_multiple_escapes.py:2", violations[0])

    def test_same_line_implicit_concatenation_is_flagged(self) -> None:
        # PR #226 review finding (round 6): the run-adjacency check used to require
        # the two STRING tokens to be on *different* physical lines, silently
        # assuming a same-line split was already caught by the per-line scan -- but
        # it isn't, since the raw closing-quote/space/opening-quote characters
        # between the two literals break the banned-pattern regexes' own `\s+`.
        # This whole example sits on one physical line.
        path = self.repo.write(
            "backend/app/api/example_same_line.py",
            "description = \"Current price + 30% of today's \" \"Autoenvelope/channel height.\"\n",
        )
        violations = cptw.check_banned_patterns([path])
        self.assertEqual(len(violations), 1)
        self.assertIn("example_same_line.py:1", violations[0])
        self.assertIn("split across an implicit string concatenation", violations[0])

    def test_mismatched_quote_style_concatenation_is_flagged(self) -> None:
        # PR #226 review finding (round 6): the run-adjacency check used to also
        # require the first token's closing quote character to equal the second
        # token's opening quote character -- a carryover from the original
        # regex-based join that Python's own grammar never actually requires.
        # `"a" 'b'` is ordinary, valid implicit concatenation.
        path = self.repo.write(
            "backend/app/api/example_mixed_quotes.py",
            "description = (\n"
            "    \"Current price + 30% of today's \"\n"
            "    'Autoenvelope/channel height.'\n"
            ")\n",
        )
        violations = cptw.check_banned_patterns([path])
        self.assertEqual(len(violations), 1)
        self.assertIn("example_mixed_quotes.py:2", violations[0])

    def test_fstring_run_member_is_safely_skipped_not_falsely_invisible(self) -> None:
        # PR #226 review finding (round 6): on this project's required Python 3.12,
        # an f-string tokenizes via PEP 701 into FSTRING_START/MIDDLE/END rather than
        # a single STRING token, so it used to reset the whole run-adjacency chain,
        # silently missing a genuine implicit-concatenation run involving it. This
        # guard now recognizes the f-string as a real (opaque) run member rather than
        # invisibly resetting the chain, but -- since an f-string's value generally
        # isn't statically knowable -- deliberately never decodes it, which safely
        # skips the whole run rather than reporting anything for it (a documented
        # scope choice, not a crash or a false positive; see this task's own
        # `decisions` entry). This differs from a plain per-line scan miss: the run
        # is genuinely recognized and evaluated, just skipped once undecodable.
        path = self.repo.write(
            "backend/app/api/example_fstring_run.py",
            "description = (\n"
            "    f\"Current price + 30% of today's \"\n"
            "    \"Autoenvelope/channel height.\"\n"
            ")\n",
        )
        # Doesn't crash, and (documented limitation) doesn't report a violation --
        # confirms the run was recognized-and-skipped, not silently perturbed into a
        # wrong result.
        self.assertEqual(cptw.check_banned_patterns([path]), [])

    def test_fstring_between_two_real_strings_does_not_bridge_across_it(self) -> None:
        # PR #226 review finding (round 6) follow-through: an f-string sitting
        # between two real string literals must not be incorrectly bridged over as
        # if it weren't there -- that would falsely concatenate the string *before*
        # it directly to the string *after* it (a false-positive risk, since real
        # content -- the f-string's own value -- sits between them in the actual
        # source). Here "today's " and "Autoenvelope" would form the exact banned
        # phrase if wrongly bridged across the f-string in between; the run
        # (correctly recognized as spanning all three pieces) must instead be
        # entirely skipped, not falsely flagged.
        path = self.repo.write(
            "backend/app/api/example_fstring_between.py",
            "description = (\n"
            "    \"today's \"\n"
            "    f\"middle {1}\"\n"
            "    \"Autoenvelope\"\n"
            ")\n",
        )
        self.assertEqual(cptw.check_banned_patterns([path]), [])

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
