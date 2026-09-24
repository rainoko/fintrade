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

import ast
import io
import os
import re
import sys
import tokenize
import unicodedata
from pathlib import Path
from typing import NamedTuple

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
    return any(path == excluded or excluded in path.parents for excluded in _EXCLUDED_PATHS)


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


# Two adjacent string literals separated only by whitespace/comments -- Python's own
# implicit string concatenation, a style already used throughout schemas.py's own
# long Field descriptions -- join into one logical string at parse time, but a naive
# per-line scan sees two separate, shorter lines and can miss a banned phrase split
# across the join (or, if the two literals sit on the very same physical line, miss
# it even without any per-line split at all -- the raw closing-quote/space/
# opening-quote characters between them already break the banned-pattern regexes'
# own `\s+`). Only genuine .py files can even contain this syntax, so runs are only
# ever looked for in those (see check_banned_patterns); within a .py file, a run is
# scoped to real implicit concatenation (not merely "any two quoted strings near each
# other") by using the stdlib `tokenize` module to find adjacent candidate members
# (STRING tokens, or a whole f-string -- see below) with nothing but
# whitespace/comments between them. This distinction matters because Python's own
# grammar only allows two string literals to be adjacent *tokens* (as opposed to two
# separate statements) across a physical line break when they're inside an open
# bracket or a backslash continuation -- outside of one, the tokenizer emits a
# logical-line-ending NEWLINE token between them instead of the non-logical NL token
# used inside brackets, and a NEWLINE always breaks a run below. That's precisely how
# this also rejects two unrelated, individually valid bare string-literal statements
# that merely happen to sit on adjacent lines.
#
# Because _NON_BREAKING_TOKEN_TYPES below are the *only* token types ever skipped
# without altering run state, reaching a candidate member with the previous one still
# on record is *itself* sufficient proof of genuine adjacency -- Python's grammar
# imposes no further requirement (in particular, nothing about the two literals
# sharing a physical line, or one's closing quote character matching the other's
# opening one -- `"a" 'b'` is ordinary, valid implicit concatenation, mismatched
# quote style and all).
#
# Crucially, a run is never flattened into a shared "joined" text buffer that the
# banned-pattern regexes then scan across an arbitrary physical line break: the
# ordinary per-line scan below never crosses a real newline at all (so it can't
# false-positive on prose that just happens to wrap mid-sentence), and a run's own
# *decoded string values* (via a custom, offset-tracking decoder --
# `_decode_string_token_with_offsets` -- cross-checked against `ast.literal_eval`,
# i.e. what Python's runtime would actually concatenate -- no injected whitespace, no
# leftover newline) are matched separately, scoped to just that run. This also means
# no other line's numbering is ever perturbed by a run found earlier in the file,
# since nothing here mutates or re-derives line numbers from a modified buffer.
#
# A reported match's line number is always computed by mapping the match's offset
# within a piece's *decoded* value back to a raw offset in that piece's own *raw
# source text* (`tok.string`), then counting real '\n' bytes in that untouched raw
# text up to the mapped position -- never by counting '\n' characters in the decoded
# value itself, which can diverge from a real physical line break whenever a piece
# contains an escape sequence that decodes to a newline character (e.g. a literal
# `\n` escape) that isn't itself a line break in the source. This keeps line
# attribution anchored in the tokenizer's own physical source coordinates end to end,
# never a heuristic character count on re-decoded text.
#
# A run-based match is only reported here when the ordinary per-line scan couldn't
# already see it directly in the untouched original text: when it crosses a piece
# boundary (spans two member literals), OR when it crosses a *real* embedded newline
# within a single multi-line piece (a triple-quoted string whose own line break
# splits the match, even though the whole match sits in one piece of the run). A
# match sitting entirely on one physical line within a single piece is left to the
# per-line scan (see `_find_run_violations`'s own docstring for why).
#
# Scope boundary, stated explicitly so it isn't mistaken for a bug: a banned phrase
# split by a real embedded newline *within a single* multi-line string literal that
# is NOT implicitly concatenated to anything else (e.g. one triple-quoted docstring
# whose own line wrap happens to split the phrase, with no adjacent second STRING
# token forming a run at all) is caught by NEITHER check here -- the per-line scan
# never crosses a real newline by design, and `_iter_implicit_concat_runs` only ever
# yields a run for 2+ genuinely-adjacent candidate members, so a single, unconcatenated
# literal never becomes part of one. This is a deliberate, accepted scope boundary
# (see `test_ordinary_line_break_in_a_py_docstring_is_not_flagged`), not a gap in the
# run-detection logic above -- the alternative (joining across any real newline
# regardless of whether real implicit concatenation is involved) is exactly what
# produced an earlier round's false-positive regression on ordinary prose that merely
# wraps mid-sentence. It narrows what this module's own "catches a literal regression
# anywhere in the repo" docstring claim actually covers.
#
# An f-string is its own case: on this project's required Python 3.12, PEP 701 means
# an f-string tokenizes into FSTRING_START/FSTRING_MIDDLE/.../FSTRING_END rather than
# a single STRING token, and its *value* generally isn't statically knowable at all
# (an interpolated `{expr}` can only be resolved at runtime). Rather than attempting
# to evaluate or partially reconstruct that value, `_iter_implicit_concat_runs` below
# treats the whole FSTRING_START..FSTRING_END span as one opaque candidate member
# (using the FSTRING_START token itself, whose raw `.string` always starts with an
# `f`-containing prefix, as its stand-in). This still participates correctly in
# adjacency -- a plain string immediately before or after a run-forming f-string is
# recognized as genuinely part of the same run -- but `_decode_string_token_with_offsets`
# already, unconditionally, declines to decode anything with an `f` in its prefix,
# which safely skips the *entire* run it's a member of (never a partial or incorrect
# decode) via `_find_run_violations`'s own existing
# any-member-undecodable-skips-the-whole-run contract, the same behavior already
# established for byte-strings. This is a deliberate scope choice, not an oversight --
# see this task's own `decisions` entry for the (a)-vs-(b) tradeoff considered.

# Token types that never end a logical line/expression on their own and so don't
# break a run of otherwise-adjacent candidate members: comments, non-logical newlines
# (only emitted inside an open bracket or continuation), and the synthetic
# indentation/encoding markers. Anything else -- crucially including a real
# `tokenize.NEWLINE` -- resets the adjacency below.
_NON_BREAKING_TOKEN_TYPES = {
    tokenize.COMMENT,
    tokenize.NL,
    tokenize.ENCODING,
    tokenize.INDENT,
    tokenize.DEDENT,
}


def _find_fstring_end_index(tokens: list[tokenize.TokenInfo], start_index: int) -> int:
    """Given the index of an FSTRING_START token, return the index of its own
    matching FSTRING_END, tracking nesting depth so a nested f-string (PEP 701
    allows the same quote character to nest inside a format expression on this
    project's Python 3.12) doesn't terminate the outer one early."""
    depth = 0
    for index in range(start_index, len(tokens)):
        tok_type = tokens[index].type
        if tok_type == tokenize.FSTRING_START:
            depth += 1
        elif tok_type == tokenize.FSTRING_END:
            depth -= 1
            if depth == 0:
                return index
    # Shouldn't happen for a token stream tokenize.generate_tokens itself produced
    # without raising -- defensive fallback treats the FSTRING_START alone as the
    # whole member, spanning no further.
    return start_index


def _iter_implicit_concat_runs(text: str) -> list[list[tokenize.TokenInfo]]:
    """Return every maximal run of 2+ genuinely-adjacent Python implicit-concatenation
    members -- real STRING tokens, or a whole f-string treated as one opaque member
    (see the module-level comment above). Returns an empty list if `text` doesn't
    parse as Python at all."""
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return []

    runs: list[list[tokenize.TokenInfo]] = []
    current_run: list[tokenize.TokenInfo] = []
    prev_member: tokenize.TokenInfo | None = None

    index = 0
    n = len(tokens)
    while index < n:
        tok = tokens[index]
        if tok.type in _NON_BREAKING_TOKEN_TYPES:
            index += 1
            continue

        member: tokenize.TokenInfo | None
        if tok.type == tokenize.STRING:
            member = tok
            index += 1
        elif tok.type == tokenize.FSTRING_START:
            end_index = _find_fstring_end_index(tokens, index)
            # An opaque stand-in for the whole f-string, however many internal
            # MIDDLE/expression tokens it contains: the FSTRING_START token itself
            # is used as-is (no position extension needed) since the adjacency
            # check below no longer compares member positions at all -- reaching a
            # candidate member with `prev_member` still on record is itself
            # sufficient proof of adjacency (see the comment on that check).
            # `_decode_string_token_with_offsets` also never reads this member's
            # `.end`: it unconditionally declines to decode an f-string, which
            # safely skips the whole run via `_find_run_violations`'s
            # any-member-undecodable-skips-the-whole-run contract before any
            # span/position math involving this member ever runs.
            member = tok
            index = end_index + 1
        else:
            member = None
            index += 1

        if member is None:
            # Any other real token (crucially tokenize.NEWLINE) between two
            # candidate members means they're not part of the same expression --
            # e.g. two unrelated bare string-literal statements on adjacent lines --
            # so the adjacency run resets.
            if current_run:
                runs.append(current_run)
                current_run = []
            prev_member = None
            continue

        # Reaching a candidate member with `prev_member` still on record is itself
        # sufficient proof of genuine adjacency (see _NON_BREAKING_TOKEN_TYPES's own
        # comment above) -- no same-physical-line or matching-quote-character
        # requirement, neither of which Python's grammar actually imposes on
        # implicit concatenation.
        if prev_member is not None:
            if not current_run:
                current_run.append(prev_member)
            current_run.append(member)
        prev_member = member

    if current_run:
        runs.append(current_run)
    return runs


def _parse_string_literal(raw: str) -> tuple[str, str, str] | None:
    """Split a STRING token's raw source text into `(prefix, quote, body)`, where
    `quote` is the exact opening/closing delimiter (`'`, `"`, `'''`, or `\"\"\"`) and
    `body` is the literal's own text between those delimiters. Returns `None` if
    `raw` doesn't look like a well-formed, quote-delimited literal (shouldn't happen
    for a real tokenize STRING token, but defensive)."""
    prefix_match = re.match(r"^[A-Za-z]*", raw)
    prefix = prefix_match.group(0) if prefix_match else ""
    rest = raw[len(prefix) :]
    # Triple-quote delimiters are checked first: a triple-quoted literal's `rest`
    # also starts and ends with the single-character quote, so checking single
    # quotes first would mis-split it.
    for quote in ('"""', "'''", '"', "'"):
        if rest.startswith(quote) and rest.endswith(quote) and len(rest) >= 2 * len(quote):
            return prefix, quote, rest[len(quote) : len(rest) - len(quote)]
    return None


# What `\c` decodes to for each single-character escape defined by the language
# reference (docs.python.org/3/reference/lexical_analysis.html#string-and-bytes-literals).
_SIMPLE_ESCAPES = {
    "\\": "\\",
    "'": "'",
    '"': '"',
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
}


def _decode_body_with_offsets(body: str, is_raw: bool) -> tuple[str, list[int]] | None:
    """Decode a string literal's body (the text between its quote delimiters) the
    same way Python's own parser would, while recording, for every decoded character
    produced, the raw offset within `body` it came from -- plus one trailing
    sentinel offset (`len(body)`) for a position exactly at the end of the decoded
    value. This lets a position in the decoded output be mapped back to real source
    coordinates without ever counting characters in the decoded text itself.

    Returns `None` on anything this decoder doesn't recognize (an escape sequence
    outside the documented table, or a malformed one) -- the caller cross-checks the
    result against `ast.literal_eval` and treats any mismatch the same way, so a gap
    in this decoder's own coverage can only ever cause a run to be safely skipped,
    never a wrong line number reported."""
    if is_raw:
        # A raw string's body is copied verbatim into its decoded value -- no escape
        # processing at all (backslashes remain literal even before a quote), so the
        # mapping back to raw offsets is simply the identity.
        return body, list(range(len(body) + 1))

    decoded: list[str] = []
    offsets: list[int] = []
    i = 0
    n = len(body)
    while i < n:
        char = body[i]
        if char != "\\":
            decoded.append(char)
            offsets.append(i)
            i += 1
            continue
        if i + 1 >= n:
            return None  # Malformed -- shouldn't happen for a token ast already accepted.
        nxt = body[i + 1]
        if nxt == "\n":
            # Backslash-newline line continuation: consumes both raw characters,
            # produces no decoded character at all.
            i += 2
            continue
        if nxt in _SIMPLE_ESCAPES:
            decoded.append(_SIMPLE_ESCAPES[nxt])
            offsets.append(i)
            i += 2
            continue
        if nxt in "01234567":
            end = i + 2
            digits = 1
            while end < n and body[end] in "01234567" and digits < 3:
                end += 1
                digits += 1
            decoded.append(chr(int(body[i + 1 : end], 8)))
            offsets.append(i)
            i = end
            continue
        if nxt in ("x", "u", "U"):
            width = {"x": 2, "u": 4, "U": 8}[nxt]
            end = i + 2 + width
            if end > n:
                return None
            try:
                decoded.append(chr(int(body[i + 2 : end], 16)))
            except ValueError:
                return None
            offsets.append(i)
            i = end
            continue
        if nxt == "N" and i + 2 < n and body[i + 2] == "{":
            close = body.find("}", i + 3)
            if close == -1:
                return None
            try:
                decoded.append(unicodedata.lookup(body[i + 3 : close]))
            except KeyError:
                return None
            offsets.append(i)
            i = close + 1
            continue
        # An unrecognized escape: Python's own parser keeps the backslash and the
        # following character literally (with a DeprecationWarning) rather than
        # raising -- mirror that instead of guessing.
        decoded.append("\\")
        offsets.append(i)
        decoded.append(nxt)
        offsets.append(i + 1)
        i += 2
    offsets.append(n)
    return "".join(decoded), offsets


def _decode_string_token_with_offsets(
    tok: tokenize.TokenInfo,
) -> tuple[str, list[int], int] | None:
    """Return `(decoded_value, offsets, body_start)` for a STRING token, where
    `offsets[i]` is the raw offset *within the literal's body* (its text between its
    quote delimiters) that decoded character `i` came from -- with one trailing
    sentinel entry for a position exactly at the end of the value -- and `body_start`
    is that body's own starting offset within `tok.string` (`len(prefix) +
    len(quote)`). Together, these are enough to map any position in the decoded
    value back to a raw offset within the token's own untouched source text.

    Returns `None` for anything not worth hand-decoding (an f-string, a
    byte-string), or whenever this decoder's own output doesn't exactly match
    `ast.literal_eval`'s -- i.e. real ground truth for what Python's own runtime
    would produce. That cross-check means a gap in this decoder's own escape-sequence
    coverage can only ever result in the run being skipped, never a wrong line
    number silently reported."""
    parsed = _parse_string_literal(tok.string)
    if parsed is None:
        return None
    prefix, quote, body = parsed
    prefix_lower = prefix.lower()
    if "f" in prefix_lower or "b" in prefix_lower:
        return None
    decoded = _decode_body_with_offsets(body, is_raw="r" in prefix_lower)
    if decoded is None:
        return None
    value, offsets = decoded
    try:
        ground_truth = ast.literal_eval(tok.string)
    except (ValueError, SyntaxError):
        return None
    if ground_truth != value:
        return None
    return value, offsets, len(prefix) + len(quote)


class _PieceSpan(NamedTuple):
    """One member literal of an implicit-concatenation run, located within the
    run's concatenated decoded value at `[start, end)`, together with everything
    needed to map a position in that range back to the literal's own real source
    coordinates (see `_physical_line_for_offset`)."""

    start: int
    end: int
    tok: tokenize.TokenInfo
    offsets: list[int]
    body_start: int


def _span_index_for_offset(offset: int, spans: list[_PieceSpan]) -> int:
    """Return the index into `spans` of the member-literal piece that contains
    `offset` (a character position within the run's concatenated decoded value)."""
    for index, span in enumerate(spans):
        if span.start <= offset < span.end:
            return index
    return len(spans) - 1


def _physical_line_for_offset(offset: int, span: _PieceSpan) -> int:
    """Return the real physical source line the decoded-value offset `offset`
    (already known to fall within `span`) actually appears on.

    Computed purely from the tokenizer's own coordinates: map `offset` back to a raw
    offset within `span.tok.string` (the token's own untouched source text) via
    `span.offsets`/`span.body_start`, then count real `\\n` bytes in that raw text up
    to the mapped position. Never derived from counting newlines in re-decoded text,
    so an escape-produced newline character (e.g. a literal `\\n` escape) can never
    be mistaken for a physical line break."""
    raw_offset_in_body = span.offsets[offset - span.start]
    raw_offset_in_token = span.body_start + raw_offset_in_body
    return span.tok.start[0] + span.tok.string[:raw_offset_in_token].count("\n")


def _find_run_violations(
    rel: Path, run: list[tokenize.TokenInfo], reported: set[tuple[int, int]]
) -> list[str]:
    """Scan one implicit-concatenation run's true, decoded, concatenated string
    value (no injected whitespace or leftover newlines -- exactly what Python's own
    runtime would produce) for banned patterns.

    A match is only reported here when the ordinary per-line scan in
    `check_banned_patterns` couldn't already see it directly in the untouched
    original text -- i.e. when it crosses a piece boundary (spans two member
    literals of the run), or when it crosses a *real* embedded newline within a
    single multi-line piece (a triple-quoted string whose own line break splits the
    match, even though the whole match sits within that one piece). A match that
    sits entirely on one physical source line within a single piece is left to the
    per-line scan; reporting it here too would duplicate-and-mislabel a finding as
    "split across an implicit string concatenation" when nothing was actually split.

    A reported match's line number is always the real physical source line the
    matched text itself starts on -- computed via `_physical_line_for_offset`, which
    is anchored in the tokenizer's own physical coordinates end to end. It is never
    derived from counting `\\n` characters in re-decoded text, which can diverge
    from a real physical line break whenever a piece contains an escape sequence
    (e.g. a literal `\\n` escape) that decodes to a newline character that isn't
    itself a line break in the source.

    `reported` is owned by the caller (`check_banned_patterns`) and shared across
    *every* run in the current file, not just this one -- two separate runs that
    happen to sit on the same physical line (e.g. two semicolon-separated
    statements, each its own run) and both match the same banned pattern must still
    dedupe against each other, not each get a fresh, run-local set that lets the
    same `(pattern_index, lineno)` be reported once per run."""
    pieces: list[str] = []
    spans: list[_PieceSpan] = []
    cursor = 0
    for tok in run:
        decoded = _decode_string_token_with_offsets(tok)
        if decoded is None:
            return []
        value, offsets, body_start = decoded
        pieces.append(value)
        spans.append(_PieceSpan(cursor, cursor + len(value), tok, offsets, body_start))
        cursor += len(value)
    concatenated = "".join(pieces)

    # The original source lines the run spans, in order, deduplicated -- used only
    # for the printed excerpt, so it shows real (quoted) source text rather than a
    # synthetic decoded buffer.
    display_lines: list[str] = []
    seen_linenos: set[int] = set()
    for tok in run:
        if tok.start[0] not in seen_linenos:
            seen_linenos.add(tok.start[0])
            display_lines.append(tok.line.strip())
    display_text = " ".join(display_lines)

    violations: list[str] = []
    # Keyed by (pattern_index, lineno), matching the per-line scan's own dedup
    # granularity in check_banned_patterns -- two different _BANNED_PATTERNS entries
    # both matching within this run and resolving to the same reported line are two
    # distinct violations, not one. `reported` itself is the caller's per-file set
    # (see this function's own docstring), not a fresh one per run.
    for pattern_index, pattern in enumerate(_BANNED_PATTERNS):
        for match in pattern.finditer(concatenated):
            start_index = _span_index_for_offset(match.start(), spans)
            end_index = _span_index_for_offset(match.end() - 1, spans)
            start_line = _physical_line_for_offset(match.start(), spans[start_index])
            end_line = _physical_line_for_offset(match.end() - 1, spans[end_index])
            if start_index == end_index and start_line == end_line:
                # Entirely on one physical source line within one member literal --
                # not actually split across anything the per-line scan can't already
                # see there directly, see the docstring above.
                continue
            key = (pattern_index, start_line)
            if key in reported:
                continue
            reported.add(key)
            violations.append(
                f"{rel}:{start_line}: stale daily-channel wording found "
                f"(split across an implicit string concatenation): {display_text!r}"
            )
    return violations


def check_banned_patterns(paths: list[Path]) -> list[str]:
    """Flag any exact recurrence of this bug's known stale wording, anywhere."""
    violations = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = path.relative_to(REPO_ROOT)

        # Ordinary per-line scan: never crosses a real physical line break, so an
        # unrelated sentence that merely wraps mid-thought (in any scanned file
        # type, .py included) can't be false-flagged just for spanning two lines.
        reported: set[tuple[int, int]] = set()
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern_index, pattern in enumerate(_BANNED_PATTERNS):
                if pattern.search(line):
                    key = (pattern_index, lineno)
                    if key in reported:
                        continue
                    reported.add(key)
                    violations.append(
                        f"{rel}:{lineno}: stale daily-channel wording found: {line.strip()!r}"
                    )

        # Implicit-string-concatenation runs only make sense for actual Python
        # source (see the module-level comment above _NON_BREAKING_TOKEN_TYPES) --
        # restricting this to .py files keeps it from ever being applied to
        # .ts/.tsx/.md prose, where "quote ... newline ... same quote" has no
        # relationship to Python's join semantics at all. Each run is scanned via
        # its own real, decoded, concatenated value -- entirely independent of the
        # per-line scan above and of any other run in the file -- so it can never
        # perturb another violation's reported line number.
        if path.suffix == ".py":
            # Shared across every run in this file (not recreated per run) so two
            # separate runs that happen to sit on the same physical line -- e.g. two
            # semicolon-separated statements, each its own run -- dedupe against
            # each other instead of each reporting the same (pattern_index, lineno)
            # violation once per run (see _find_run_violations's own docstring).
            run_reported: set[tuple[int, int]] = set()
            for run in _iter_implicit_concat_runs(text):
                violations.extend(_find_run_violations(rel, run, run_reported))
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
