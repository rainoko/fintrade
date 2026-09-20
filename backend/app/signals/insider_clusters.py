"""Insider-transaction buy/sell classification and time-windowed cluster detection -- Elder
ch. 37 p. 147 (docs/ideas.md's own citation; see docs/tasks/backend-insider-transaction-
clusters.json's `decisions` entry for every judgment call below).

**What a cluster is** (Elder, per docs/ideas.md's own transcription): "several insiders buying
(or selling) within a one-month period" is a real, if secondary, signal worth noting alongside
a stock's technical picture -- not a standalone BUY/SELL trigger. This module is detection +
exposure only: it is NOT wired into Screen 1/2/3, the Impulse gate, confidence scoring, or
portfolio risk, matching the non-scope-creep precedent already set by
``app.signals.support_resistance``/``divergence``/``kangaroo_tail`` (each its own task, each
staying purely informational).

**Classification is the hard part, not the clustering** (docs/ideas.md's own framing: "the
book's concept is precise, the parsing mechanism is not"): yfinance's own scraper provides no
structured buy/sell direction field on ``InsiderTransaction`` -- only ``transaction_text``'s
free-text description (e.g. "Sale at price 220.00 - 225.00 per share.", "Purchase at price
45.00 per share.", but also option-exercise/gift/tax-withholding/grant dispositions that reuse
the same "Sale"/"Purchase" vocabulary without being a genuine open-market conviction trade).
See ``classify_transaction``'s own docstring for the exact rule.

**Clustering** groups same-direction, classified ("buy"/"sell" only -- "other" is always
excluded) transactions that also have a known ``insider`` name and ``start_date`` (both
required to verify "several *insiders*", i.e. distinct identities, per Elder's own wording --
a transaction missing either can never confirm or deny distinctness, so it's excluded from
clustering entirely rather than guessed at; it's unaffected everywhere else, e.g. still present
in ``ExtendedDataOut.insider_transactions``'s raw list). Qualifying same-direction transactions
are scanned in date order into non-overlapping windows of ``_CLUSTER_WINDOW_DAYS`` calendar
days, each window anchored at its own earliest member (not a continuously-sliding window --
see this task's `decisions` entry for why), reporting a cluster once a window's distinct
insider-name count reaches ``_MIN_DISTINCT_INSIDERS``.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from app.data.base import InsiderTransaction

Direction = Literal["buy", "sell"]
Classification = Literal["buy", "sell", "other"]

# Elder's own wording is "several insiders ... within a one-month period" (docs/ideas.md) --
# "several" is read as 3, the smallest count "several" can reasonably mean, and the exact
# number this task's own checklist/description asks this module to implement against.
_MIN_DISTINCT_INSIDERS = 3

# "a one-month period" read as 30 calendar days, not a strict calendar-month boundary (which
# would make a cluster's qualification depend on which day of the month the window happens to
# start on) -- see this task's `decisions` entry.
_CLUSTER_WINDOW_DAYS = 30

# Keywords that, found anywhere in a transaction's own text (case-insensitive), mean it is NOT
# a genuine open-market conviction buy/sell even if it also contains "purchase"/"sale" --
# option exercises, gifts, grants/awards, tax-withholding dispositions, and derivative-security
# conversions are all excluded from clustering (see this task's `decisions` entry for the
# rationale behind this exact list).
_EXCLUSION_KEYWORDS = (
    "option",
    "exercise",
    "gift",
    "award",
    "grant",
    "tax",
    "conversion",
    "withholding",
)


def classify_transaction(transaction_text: str) -> Classification:
    """Classifies one raw ``InsiderTransaction.transaction_text`` value into "buy" / "sell" /
    "other" ("not a genuine open-market conviction transaction, exclude from clustering").

    Rule (see this task's `decisions` entry for the full rationale):

    1. Empty/whitespace-only text -> "other" (nothing to classify).
    2. Text containing any of ``_EXCLUSION_KEYWORDS`` (case-insensitive, anywhere in the
       string) -> "other", checked BEFORE the purchase/sale check below, so e.g.
       "Sale+Gift at price ..." or "Payment of exercise price by delivering shares" (which
       both contain "sale"-ish or "purchase"-ish vocabulary despite being a
       gift/tax/option-exercise disposition, not an open-market trade) are excluded rather
       than misclassified.
    3. Otherwise, text starting with "purchase" -> "buy"; text starting with "sale" -> "sell"
       (yfinance's own observed phrasing always leads with one of these two words for a
       genuine open-market transaction, e.g. "Purchase at price 45.00 per share.",
       "Sale at price 220.00 - 225.00 per share.").
    4. Any other text (an unrecognized/unparseable description that doesn't start with either
       leading word) -> "other" -- excluded from clustering, but the raw
       ``InsiderTransaction`` this text came from is otherwise untouched (still present, and
       reported as-is, wherever the raw transaction list itself is exposed).
    """
    normalized = transaction_text.strip().lower()
    if not normalized:
        return "other"
    if any(keyword in normalized for keyword in _EXCLUSION_KEYWORDS):
        return "other"
    if normalized.startswith("purchase"):
        return "buy"
    if normalized.startswith("sale"):
        return "sell"
    return "other"


@dataclass(frozen=True)
class InsiderCluster:
    """One qualifying cluster of same-direction insider activity (see this module's own
    docstring for the exact window/threshold definition).

    ``insiders`` is always alphabetically sorted (a deterministic presentation order -- the
    underlying detection is a set of distinct names, which has no inherent order of its own)
    and always has at least ``_MIN_DISTINCT_INSIDERS`` entries. ``transaction_count`` can
    exceed ``len(insiders)`` when one of the window's insiders filed more than once within the
    window -- every qualifying (classified buy/sell, named insider, dated) filing in the window
    counts, not just one per insider.
    """

    direction: Direction
    window_start_date: date
    window_end_date: date
    insiders: list[str]
    transaction_count: int
    total_shares: float | None
    total_value: float | None


def _sum_or_none(values: list[float | None]) -> float | None:
    """Sums whatever values are present (not `None`); `None` if none of them are -- mirrors
    the rest of `ExtendedData`'s own null-safety convention (a genuinely missing figure is
    `None`, never a fabricated 0)."""
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def _find_clusters(
    transactions: list[InsiderTransaction],
    direction: Direction,
    window_days: int,
    min_distinct_insiders: int,
) -> list[InsiderCluster]:
    """Greedy, anchored, non-overlapping scan over `transactions` (already filtered to one
    direction, sorted by `start_date` ascending, every member has a non-null `insider`/
    `start_date`): for each not-yet-consumed transaction `i`, extends a window forward while
    the next transaction's `start_date` is still within `window_days` of transaction `i`'s own
    date (the window's anchor). If the resulting window's distinct-insider count reaches
    `min_distinct_insiders`, it's reported as a cluster and the scan resumes strictly after the
    window (clusters never overlap); otherwise the scan advances by one transaction and
    re-anchors there. See this module's own docstring for why an anchored, non-overlapping scan
    was chosen over a continuously-sliding window.
    """
    clusters: list[InsiderCluster] = []
    n = len(transactions)
    i = 0
    while i < n:
        anchor_date = transactions[i].start_date
        assert anchor_date is not None
        j = i
        while j + 1 < n:
            next_date = transactions[j + 1].start_date
            assert next_date is not None
            if next_date - anchor_date > timedelta(days=window_days):
                break
            j += 1
        window = transactions[i : j + 1]
        distinct_insiders = sorted({t.insider for t in window if t.insider is not None})
        if len(distinct_insiders) >= min_distinct_insiders:
            window_start = window[0].start_date
            window_end = window[-1].start_date
            assert window_start is not None and window_end is not None
            clusters.append(
                InsiderCluster(
                    direction=direction,
                    window_start_date=window_start,
                    window_end_date=window_end,
                    insiders=distinct_insiders,
                    transaction_count=len(window),
                    total_shares=_sum_or_none([t.shares for t in window]),
                    total_value=_sum_or_none([t.value for t in window]),
                )
            )
            i = j + 1
        else:
            i += 1
    return clusters


def detect_insider_clusters(
    transactions: list[InsiderTransaction],
    *,
    window_days: int = _CLUSTER_WINDOW_DAYS,
    min_distinct_insiders: int = _MIN_DISTINCT_INSIDERS,
) -> list[InsiderCluster]:
    """Classifies every transaction (`classify_transaction`) and detects qualifying same-
    direction clusters (see this module's own docstring for the classification rule and the
    window/threshold definition) over `transactions` -- typically
    `ExtendedData.insider_transactions`'s full available filing history for one ticker,
    already yfinance's own most-recent-first order (this function doesn't depend on the input
    order; it re-sorts by `start_date` internally per direction).

    Buy and sell clusters are detected entirely independently (a transaction can only ever
    belong to one direction's clustering pass, per its own classification). Returns every
    qualifying cluster from both directions combined, most-recent-`window_end_date`-first --
    an empty list if none qualify (including when `transactions` itself is empty, e.g.
    `ExtendedData.unavailable_reason` is set).
    """
    by_direction: dict[Direction, list[InsiderTransaction]] = {"buy": [], "sell": []}
    for transaction in transactions:
        if transaction.start_date is None or transaction.insider is None:
            continue
        classification = classify_transaction(transaction.transaction_text)
        if classification == "buy" or classification == "sell":
            by_direction[classification].append(transaction)

    clusters: list[InsiderCluster] = []
    for direction, direction_transactions in by_direction.items():
        direction_transactions.sort(key=lambda t: t.start_date)  # type: ignore[arg-type,return-value]
        clusters.extend(_find_clusters(direction_transactions, direction, window_days, min_distinct_insiders))

    clusters.sort(key=lambda c: c.window_end_date, reverse=True)
    return clusters
