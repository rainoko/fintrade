#!/usr/bin/env python3
"""Guard against the "stale daily-channel copy" bug regressing a 7th time.

`suggest_profit_target`'s channel/Tradebill target candidate is computed from the
**weekly** chart (ch. 39 p.161's stops-on-intermediate/targets-on-long-term rule --
`backend-profit-target-weekly-channel`'s `decisions` entry), not the daily
`indicators.channel_upper`/`channel_lower` this app also exposes for an unrelated
purpose (the price-chart overlay, trade grading). During PR #222's 2 review rounds,
prose describing that channel source drifted back to the pre-fix DAILY wording ("today's
Autoenvelope", "~100 days of history") independently, across 6 separate
files/locations, over and over -- each fix pass caught the previously-named locations
but missed at least one more (see
`docs/tasks/backend-profit-target-weekly-channel-followups.json`).

This script is a cheap, repo-wide, stdlib-only guard against a 7th recurrence:

1. **Negative check**: no file outside a small, deliberately-excluded set (see
   `_EXCLUDED_...` below) may contain any of the exact wording patterns this bug has
   actually used (`_BANNED_PATTERNS`) -- this catches a literal regression anywhere in
   the repo, including a brand-new file this script has never heard of.
2. **Positive check**: every file in `_KNOWN_PROFIT_TARGET_CHANNEL_FILES` -- every
   location this exact bug class has actually recurred in, plus the module that IS the
   source of truth -- must still say "weekly"/"week" wherever it describes the
   channel/Autoenvelope candidate in a profit-target context. This catches a future
   *paraphrase* that avoids the specific banned wording above but still silently drops
   back to describing the channel as computed from "today"/daily data without saying so
   in those exact words.

Excluded from BOTH checks: `docs/tasks/` (a task's `decisions`/`review`/description text
is an intentionally-preserved historical record of what was true or wrong at the time,
not currently-read living documentation -- seeing "today's Autoenvelope" quoted inside a
past review's own finding is expected, not a regression) and `docs/ideas.md` (an
explicit scratch pad per its own header, not one of CLAUDE.md's source-of-truth docs --
its own stale-wording fix is tracked as a one-off content edit by this same followups
task, not by this automated guard). Test files (`*.test.ts`/`*.test.tsx`,
`test_*.py`/`*_test.py`, anything under a `tests/` directory) are also excluded from the
negative check, since several of them intentionally reference the banned wording as a
regex literal *inside a `not.toMatch`/similar negative assertion* -- that's the guard
working as intended at the unit-test level, not a regression.

Stdlib-only (os, re, sys, pathlib), matching `scripts/validate_tasks.py`'s own
zero-setup philosophy -- no venv/install step needed either.

Usage: python3 scripts/check_profit_target_wording.py
Exit code: 0 with a one-line summary if clean, non-zero with every violation listed
otherwise.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_EXCLUDED_DIR_NAMES = {
    ".git",
    "node_modules",
    ".venv",
    "coverage",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

# docs/tasks/ (both docs/tasks/*.json and docs/tasks/done/*.json) and
# docs/ideas.md -- see the module docstring for why both are out of scope for this
# guard specifically.
_EXCLUDED_PATHS = {
    REPO_ROOT / "docs" / "tasks",
    REPO_ROOT / "docs" / "ideas.md",
}

_SCANNED_SUFFIXES = {".py", ".ts", ".tsx", ".md"}

# Literal wording that has recurred, verbatim or near-verbatim, across 5 separate
# locations over 2 review rounds of PR #222 (backend-profit-target-weekly-channel).
_BANNED_PATTERNS = [
    re.compile(r"today['’]s\s+Autoenvelope", re.IGNORECASE),
    re.compile(r"that\s+day['’]s\s+Autoenvelope", re.IGNORECASE),
    re.compile(r"~?\s?100\s+days\s+of\s+history", re.IGNORECASE),
]

# Every location this exact bug class has actually recurred in across PR #222's 2
# review rounds, plus profit_target.py itself (the source of truth its own docstring
# is derived from). If a 7th location is ever found, add it here too.
#
# Each entry is `(relative_path, start_anchor, end_anchor)`. `start_anchor`/
# `end_anchor` (regex strings, or `None`) narrow the check to just the
# profit-target-relevant region of a file that also describes OTHER, genuinely
# different and still-daily metrics nearby (e.g. `metricHelpContent.ts`'s own
# `tradeGradeHelp`/entry-day-channel description, a few dozen lines from
# `profitTargetHelp` in the same file) -- without this, a wide context window over
# the whole file would false-positive on that unrelated, correctly-daily prose just
# for happening to mention "channel"/"Autoenvelope" without "weekly" nearby. `None`
# for both anchors means "scan the whole file" (safe for a file that only ever
# describes this one metric, or large enough/sparse enough that the windowed check
# below already doesn't bleed into another metric's own description).
_KNOWN_PROFIT_TARGET_CHANNEL_FILES: list[tuple[str, str | None, str | None]] = [
    ("backend/app/portfolio/profit_target.py", None, None),
    ("backend/app/api/schemas.py", None, None),
    ("docs/Analyse.md", None, None),
    ("docs/architecture/API.md", None, None),
    ("frontend/src/utils/profitTargetHelpText.ts", None, None),
    ("frontend/src/features/stocks/components/metricHelpContent.ts", None, None),
    (
        "frontend/src/features/portfolio/components/metricHelpContent.ts",
        r"export const profitTargetHelp",
        r"\nexport const \w",
    ),
    (
        "frontend/src/features/methodology/data/methodologyContent.ts",
        r"id: 'profit-target'",
        r"\n\s*id: '",
    ),
]

_CHANNEL_CONTEXT_RE = re.compile(r"autoenvelope|channel height", re.IGNORECASE)
_PROFIT_TARGET_CONTEXT_RE = re.compile(
    # `[\s_-]` also matches the hyphenated "profit-target" -- the literal text of
    # methodologyContent.ts's own `id: 'profit-target'` start_anchor -- not just the
    # space/underscore forms used elsewhere.
    r"profit[\s_-]target|suggest_profit_target|tradebill|profittargetout",
    re.IGNORECASE,
)
# `s?` also matches the plural noun "weeks" on its own (not just "week"/"weekly") --
# `\bweek(ly)?\b` alone left "100 weeks" unmatched since `s` broke the trailing `\b`.
_WEEKLY_RE = re.compile(r"\bweek(s|ly)?\b", re.IGNORECASE)

# Character window (before/after a channel-context match) searched for the paired
# profit-target-context and "weekly" wording -- a character count rather than a fixed
# line count so it scales with each language's own prose density (a hand-wrapped Python
# docstring bullet point spans many more lines for the same amount of text than a single
# long TS template-literal string). Calibrated against this repo's own longest real
# gap -- profit_target.py's docstring, where the closest "weekly" mention to its
# `app.indicators.autoenvelope` code reference is ~470 characters away -- while staying
# well short of drifting into an unrelated paragraph a few thousand characters over
# (e.g. this same file's own, genuinely different and still-daily, trade-grading
# channel description).
_CONTEXT_WINDOW_CHARS = 700


def _is_test_file(path: Path) -> bool:
    name = path.name
    if ".test." in name:
        return True
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    return "tests" in path.parts


def _is_excluded_path(path: Path) -> bool:
    for excluded in _EXCLUDED_PATHS:
        if path == excluded or excluded in path.parents:
            return True
    return False


def _should_scan_for_banned_patterns(path: Path) -> bool:
    if path.suffix not in _SCANNED_SUFFIXES:
        return False
    # _iter_scanned_files already prunes _EXCLUDED_DIR_NAMES during its own os.walk
    # traversal below, so this is a redundant (but cheap) safety net for any other
    # caller of this predicate.
    if any(part in _EXCLUDED_DIR_NAMES for part in path.parts):
        return False
    if _is_excluded_path(path):
        return False
    if path.resolve() == Path(__file__).resolve():
        return False
    return not _is_test_file(path)


def _iter_scanned_files() -> list[Path]:
    # Prune excluded directories (node_modules/.venv/.git/dist/build/coverage/etc.)
    # during traversal via os.walk's own `dirnames[:] = ...` idiom, rather than
    # enumerating every file under them with rglob("*") first and filtering
    # afterwards -- this script runs unconditionally as static-verify's own step 5 on
    # every PR review and QA pass, so an unpruned walk's cost only grows as those
    # directories grow.
    matched: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDED_DIR_NAMES]
        for filename in filenames:
            path = Path(dirpath) / filename
            if _should_scan_for_banned_patterns(path):
                matched.append(path)
    return sorted(matched)


# Two adjacent string literals separated only by whitespace across a line break --
# Python's own implicit string concatenation, a style already used throughout
# schemas.py's own long Field descriptions -- join into one logical string at parse
# time, but a naive line-by-line scan sees two separate, shorter lines and can miss a
# banned phrase split across the join. Recognize the join (a quote, whitespace
# spanning a newline, then the same quote character) and drop just the quote pair,
# preserving every newline exactly, so a match found in the joined text still maps
# back to the right physical line via a plain newline count.
_STRING_CONCAT_JOIN_RE = re.compile(r"([\"'])(\s*\n\s*)\1")


def _join_implicit_string_concatenation(text: str) -> str:
    return _STRING_CONCAT_JOIN_RE.sub(r"\2", text)


def check_banned_patterns(paths: list[Path]) -> list[str]:
    """Flag any exact recurrence of this bug's known stale wording, anywhere."""
    violations = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="ignore")
        joined = _join_implicit_string_concatenation(text)
        joined_lines = joined.splitlines()
        rel = path.relative_to(REPO_ROOT)
        reported: set[tuple[int, int]] = set()
        for pattern_index, pattern in enumerate(_BANNED_PATTERNS):
            for match in pattern.finditer(joined):
                lineno = joined.count("\n", 0, match.start()) + 1
                key = (pattern_index, lineno)
                if key in reported:
                    continue
                reported.add(key)
                line_text = joined_lines[lineno - 1].strip()
                violations.append(
                    f"{rel}:{lineno}: stale daily-channel wording found: {line_text!r}"
                )
    return violations


def _extract_region(
    text: str, start_anchor: str | None, end_anchor: str | None
) -> tuple[str, int, bool] | None:
    """Return `(region_text, offset_of_region_start_in_text, end_anchor_missing)`, or
    `None` if `start_anchor` doesn't match anywhere (a signal the caller's file
    structure has changed enough that this guard's anchors need updating too).

    `end_anchor_missing` is True precisely when a (non-`None`) `end_anchor` was given
    but didn't match anywhere after the start anchor -- the caller should flag this
    the same way as a failed start anchor (this guard's own scoping no longer matches
    the file's real structure), even though, unlike a failed start anchor, there's
    still a region to fall back to scanning (from the start anchor to end of file)."""
    if start_anchor is None:
        return text, 0, False
    start_match = re.search(start_anchor, text)
    if start_match is None:
        return None
    region_start = start_match.start()
    if end_anchor is None:
        return text[region_start:], region_start, False
    end_match = re.search(end_anchor, text[start_match.end() :])
    if end_match is None:
        return text[region_start:], region_start, True
    region_end = start_match.end() + end_match.start()
    return text[region_start:region_end], region_start, False


def check_known_files_mention_weekly(repo_root: Path = REPO_ROOT) -> list[str]:
    """Flag a known profit-target-channel location that no longer says "weekly"
    wherever it describes the channel/Autoenvelope candidate."""
    violations = []
    for rel_str, start_anchor, end_anchor in _KNOWN_PROFIT_TARGET_CHANNEL_FILES:
        path = repo_root / rel_str
        if not path.exists():
            violations.append(
                f"{rel_str}: known profit-target-channel file no longer exists "
                "(update this guard's _KNOWN_PROFIT_TARGET_CHANNEL_FILES list)"
            )
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        extracted = _extract_region(text, start_anchor, end_anchor)
        if extracted is None:
            violations.append(
                f"{rel_str}: this guard's start anchor ({start_anchor!r}) no longer "
                "matches -- update _KNOWN_PROFIT_TARGET_CHANNEL_FILES if the file's "
                "structure legitimately changed"
            )
            continue
        region, region_offset, end_anchor_missing = extracted
        if end_anchor_missing:
            violations.append(
                f"{rel_str}: this guard's end anchor ({end_anchor!r}) no longer "
                "matches -- update _KNOWN_PROFIT_TARGET_CHANNEL_FILES if the file's "
                "structure legitimately changed (falling back to scanning from the "
                "start anchor to end of file in the meantime, which risks bleeding "
                "into unrelated later content)"
            )

        found_channel_context = False
        for match in _CHANNEL_CONTEXT_RE.finditer(region):
            start, end = match.span()
            window = region[max(0, start - _CONTEXT_WINDOW_CHARS) : end + _CONTEXT_WINDOW_CHARS]
            if not _PROFIT_TARGET_CONTEXT_RE.search(window):
                continue
            found_channel_context = True
            if not _WEEKLY_RE.search(window):
                absolute_start = region_offset + start
                lineno = text.count("\n", 0, absolute_start) + 1
                line_text = text.splitlines()[lineno - 1].strip()
                violations.append(
                    f"{rel_str}:{lineno}: describes the profit-target channel/Autoenvelope "
                    f"candidate without mentioning 'weekly' nearby -- possible stale "
                    f"daily-channel regression: {line_text!r}"
                )
        if not found_channel_context:
            violations.append(
                f"{rel_str}: expected to describe suggest_profit_target's channel source, "
                "but no Autoenvelope/channel-height + profit-target context was found at "
                "all (update this guard if the file's wording legitimately changed, e.g. "
                "the description moved elsewhere)"
            )
    return violations


def main() -> int:
    scanned = _iter_scanned_files()
    violations = check_banned_patterns(scanned)
    violations += check_known_files_mention_weekly()

    if violations:
        print(f"Found {len(violations)} stale profit-target daily-channel wording violation(s):\n")
        for violation in violations:
            print(f"  - {violation}")
        return 1

    print(
        f"Scanned {len(scanned)} file(s) plus {len(_KNOWN_PROFIT_TARGET_CHANNEL_FILES)} "
        "known profit-target-channel location(s); no stale daily-channel wording found."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
