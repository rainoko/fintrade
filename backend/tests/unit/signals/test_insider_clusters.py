"""Tests for app.signals.insider_clusters (Elder ch. 37 p. 147,
docs/tasks/backend-insider-transaction-clusters.json).

Every cluster case below is hand-verified: transaction dates/insiders are chosen so the
expected window/distinct-insider-count/cluster boundaries can be worked out by hand, not just
asserted against whatever the algorithm happens to produce.
"""

from datetime import date

import pytest

from app.data.base import InsiderTransaction
from app.signals.insider_clusters import (
    InsiderCluster,
    classify_transaction,
    detect_insider_clusters,
)


def _txn(
    *,
    insider: str | None,
    text: str,
    start_date: date | None,
    shares: float | None = None,
    value: float | None = None,
) -> InsiderTransaction:
    return InsiderTransaction(
        insider=insider,
        position="Director",
        transaction_text=text,
        shares=shares,
        value=value,
        start_date=start_date,
        ownership="D",
    )


# --- classify_transaction ------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Purchase at price 45.00 per share.", "buy"),
        ("Sale at price 220.00 - 225.00 per share.", "sell"),
        ("  purchase at price 1.00 per share.  ", "buy"),  # case/whitespace-insensitive
        ("SALE AT PRICE 10.00 PER SHARE.", "sell"),
        ("", "other"),  # empty/unparseable
        ("   ", "other"),  # whitespace-only
        ("Conversion of Exercise of derivative security at price 0.00 per share.", "other"),
        ("Option Exercise at price 5.00 per share.", "other"),
        ("Sale+Gift at price 12.00 per share.", "other"),  # "sale" prefix, but a gift -- excluded
        ("Payment of exercise price or tax liability by delivering shares.", "other"),
        ("Stock Award", "other"),
        ("Grant of restricted stock units.", "other"),
        ("Some unrecognized brand-new filing description.", "other"),  # neither leading word
    ],
)
def test_classify_transaction(text: str, expected: str) -> None:
    assert classify_transaction(text) == expected


# --- detect_insider_clusters ----------------------------------------------


def test_unambiguous_buy_cluster() -> None:
    """3 distinct insiders each buying within a 30-day window -> one buy cluster."""
    transactions = [
        _txn(insider="Alice A", text="Purchase at price 10.00 per share.", start_date=date(2026, 1, 1), shares=100),
        _txn(insider="Bob B", text="Purchase at price 11.00 per share.", start_date=date(2026, 1, 10), shares=200),
        _txn(insider="Carol C", text="Purchase at price 12.00 per share.", start_date=date(2026, 1, 20), shares=300),
    ]

    clusters = detect_insider_clusters(transactions)

    assert clusters == [
        InsiderCluster(
            direction="buy",
            window_start_date=date(2026, 1, 1),
            window_end_date=date(2026, 1, 20),
            insiders=["Alice A", "Bob B", "Carol C"],
            transaction_count=3,
            total_shares=600.0,
            total_value=None,
        )
    ]


def test_unambiguous_sell_cluster() -> None:
    """3 distinct insiders each selling within a 30-day window -> one sell cluster."""
    transactions = [
        _txn(
            insider="Alice A",
            text="Sale at price 100.00 - 101.00 per share.",
            start_date=date(2026, 3, 1),
            value=10_000.0,
        ),
        _txn(
            insider="Bob B",
            text="Sale at price 102.00 - 103.00 per share.",
            start_date=date(2026, 3, 15),
            value=20_000.0,
        ),
        _txn(
            insider="Carol C",
            text="Sale at price 104.00 - 105.00 per share.",
            start_date=date(2026, 3, 29),
            value=30_000.0,
        ),
    ]

    clusters = detect_insider_clusters(transactions)

    assert clusters == [
        InsiderCluster(
            direction="sell",
            window_start_date=date(2026, 3, 1),
            window_end_date=date(2026, 3, 29),
            insiders=["Alice A", "Bob B", "Carol C"],
            transaction_count=3,
            total_shares=None,
            total_value=60_000.0,
        )
    ]


def test_mixed_direction_does_not_cluster() -> None:
    """2 buys + 1 sell, all distinct insiders, within the same window -- neither direction
    reaches the 3-distinct-insider threshold on its own, so no cluster either way."""
    transactions = [
        _txn(insider="Alice A", text="Purchase at price 10.00 per share.", start_date=date(2026, 5, 1)),
        _txn(insider="Bob B", text="Purchase at price 11.00 per share.", start_date=date(2026, 5, 5)),
        _txn(insider="Carol C", text="Sale at price 12.00 per share.", start_date=date(2026, 5, 10)),
    ]

    assert detect_insider_clusters(transactions) == []


def test_fewer_than_threshold_within_window_no_cluster() -> None:
    """Only 2 distinct insiders buying within the window -- below the 3-insider threshold."""
    transactions = [
        _txn(insider="Alice A", text="Purchase at price 10.00 per share.", start_date=date(2026, 2, 1)),
        _txn(insider="Bob B", text="Purchase at price 11.00 per share.", start_date=date(2026, 2, 15)),
    ]

    assert detect_insider_clusters(transactions) == []


def test_unparseable_and_excluded_text_excluded_from_clustering() -> None:
    """A 4th, option-exercise transaction wouldn't be needed for the cluster to qualify (3
    genuine buys already do), but it must not be miscounted as a 4th distinct buyer, and an
    otherwise-would-be 3rd buyer whose own text is an option exercise must NOT complete a
    cluster that would otherwise be one short."""
    # Only 2 genuine buys -- the 3rd candidate's text is an option exercise, so the buy
    # cluster does NOT form even though 3 InsiderTransaction rows exist in the window.
    transactions = [
        _txn(insider="Alice A", text="Purchase at price 10.00 per share.", start_date=date(2026, 4, 1)),
        _txn(insider="Bob B", text="Purchase at price 11.00 per share.", start_date=date(2026, 4, 10)),
        _txn(
            insider="Carol C",
            text="Option Exercise at price 1.00 per share.",
            start_date=date(2026, 4, 15),
        ),
    ]

    assert detect_insider_clusters(transactions) == []


def test_transactions_outside_window_do_not_merge() -> None:
    """3 distinct insiders buying, but the 3rd is more than 30 days after the 1st -- the
    window never reaches 3 distinct insiders at once."""
    transactions = [
        _txn(insider="Alice A", text="Purchase at price 10.00 per share.", start_date=date(2026, 1, 1)),
        _txn(insider="Bob B", text="Purchase at price 11.00 per share.", start_date=date(2026, 1, 20)),
        _txn(insider="Carol C", text="Purchase at price 12.00 per share.", start_date=date(2026, 2, 5)),
    ]

    # Alice(Jan 1) .. Bob(Jan 20) is a 19-day span (within 30 days, but only 2 distinct
    # insiders); Alice(Jan 1) .. Carol(Feb 5) is 35 days (exceeds the 30-day window), so the
    # window anchored at Alice never includes Carol. Re-anchoring at Bob (Jan 20 .. Feb 5,
    # 16 days) only ever has 2 distinct insiders (Bob, Carol) too.
    assert detect_insider_clusters(transactions) == []


def test_same_insider_repeat_filing_does_not_count_twice() -> None:
    """Alice filing twice plus only one other distinct insider is still just 2 distinct
    insiders -- repeat filings by the same insider never substitute for a genuinely different
    insider."""
    transactions = [
        _txn(insider="Alice A", text="Purchase at price 10.00 per share.", start_date=date(2026, 6, 1)),
        _txn(insider="Alice A", text="Purchase at price 10.50 per share.", start_date=date(2026, 6, 5)),
        _txn(insider="Bob B", text="Purchase at price 11.00 per share.", start_date=date(2026, 6, 10)),
    ]

    assert detect_insider_clusters(transactions) == []


def test_transaction_count_can_exceed_distinct_insider_count() -> None:
    """3 distinct insiders, one of whom (Alice) files twice within the window -- the cluster
    still qualifies (3 distinct insiders), and transaction_count reflects all 4 qualifying
    filings, not just 3."""
    transactions = [
        _txn(insider="Alice A", text="Purchase at price 10.00 per share.", start_date=date(2026, 7, 1), shares=50),
        _txn(insider="Bob B", text="Purchase at price 11.00 per share.", start_date=date(2026, 7, 5), shares=60),
        _txn(insider="Carol C", text="Purchase at price 12.00 per share.", start_date=date(2026, 7, 10), shares=70),
        _txn(insider="Alice A", text="Purchase at price 10.20 per share.", start_date=date(2026, 7, 15), shares=80),
    ]

    clusters = detect_insider_clusters(transactions)

    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.direction == "buy"
    assert cluster.insiders == ["Alice A", "Bob B", "Carol C"]
    assert cluster.transaction_count == 4
    assert cluster.total_shares == 260.0
    assert cluster.window_start_date == date(2026, 7, 1)
    assert cluster.window_end_date == date(2026, 7, 15)


def test_missing_insider_name_excluded_from_clustering() -> None:
    """A transaction with no insider name can never confirm distinctness -- it's excluded
    from clustering entirely, even though it's a genuine, classifiable buy."""
    transactions = [
        _txn(insider="Alice A", text="Purchase at price 10.00 per share.", start_date=date(2026, 8, 1)),
        _txn(insider="Bob B", text="Purchase at price 11.00 per share.", start_date=date(2026, 8, 5)),
        _txn(insider=None, text="Purchase at price 12.00 per share.", start_date=date(2026, 8, 10)),
    ]

    assert detect_insider_clusters(transactions) == []


def test_missing_start_date_excluded_from_clustering() -> None:
    """A transaction with no start_date can't be placed in any time window -- excluded."""
    transactions = [
        _txn(insider="Alice A", text="Purchase at price 10.00 per share.", start_date=date(2026, 9, 1)),
        _txn(insider="Bob B", text="Purchase at price 11.00 per share.", start_date=date(2026, 9, 5)),
        _txn(insider="Carol C", text="Purchase at price 12.00 per share.", start_date=None),
    ]

    assert detect_insider_clusters(transactions) == []


def test_two_non_overlapping_clusters_for_the_same_direction() -> None:
    """Two separate qualifying windows for the same direction, far enough apart in time that
    they don't merge -- both are reported, most-recent-window_end_date-first."""
    transactions = [
        _txn(insider="Alice A", text="Purchase at price 10.00 per share.", start_date=date(2026, 1, 1)),
        _txn(insider="Bob B", text="Purchase at price 11.00 per share.", start_date=date(2026, 1, 5)),
        _txn(insider="Carol C", text="Purchase at price 12.00 per share.", start_date=date(2026, 1, 10)),
        _txn(insider="Dave D", text="Purchase at price 13.00 per share.", start_date=date(2026, 6, 1)),
        _txn(insider="Erin E", text="Purchase at price 14.00 per share.", start_date=date(2026, 6, 5)),
        _txn(insider="Frank F", text="Purchase at price 15.00 per share.", start_date=date(2026, 6, 10)),
    ]

    clusters = detect_insider_clusters(transactions)

    assert len(clusters) == 2
    assert clusters[0].window_start_date == date(2026, 6, 1)
    assert clusters[0].insiders == ["Dave D", "Erin E", "Frank F"]
    assert clusters[1].window_start_date == date(2026, 1, 1)
    assert clusters[1].insiders == ["Alice A", "Bob B", "Carol C"]


def test_empty_transactions_returns_empty_list() -> None:
    assert detect_insider_clusters([]) == []


def test_custom_thresholds_are_respected() -> None:
    """A caller-supplied window_days/min_distinct_insiders (not just the defaults) is honored
    -- 2 distinct insiders qualifies with min_distinct_insiders=2."""
    transactions = [
        _txn(insider="Alice A", text="Purchase at price 10.00 per share.", start_date=date(2026, 10, 1)),
        _txn(insider="Bob B", text="Purchase at price 11.00 per share.", start_date=date(2026, 10, 5)),
    ]

    clusters = detect_insider_clusters(transactions, min_distinct_insiders=2)

    assert len(clusters) == 1
    assert clusters[0].insiders == ["Alice A", "Bob B"]
