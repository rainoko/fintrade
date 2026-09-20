"""Tests for app.signals.kangaroo_tail (Elder ch. 20, docs/tasks/backend-kangaroo-tail-pattern.json).

Fixtures use a flat, constant-range "filler" baseline (open=100/high=101/low=99/close=100 for
every filler bar) so the recent-average-range baseline is a fully predictable, hand-computable
constant (2.0) and no filler bar accidentally makes a new high/low of its own -- only the
explicitly-overridden tail/flank bars can ever qualify or disqualify a pattern. This keeps
every assertion below hand-verifiable by direct arithmetic, per the add-indicator skill's
reference-value-test bar.
"""

import pandas as pd
import pytest

from app.signals.kangaroo_tail import (
    DEFAULT_LOOKBACK,
    DEFAULT_RANGE_MULTIPLIER,
    KangarooTail,
    build_kangaroo_tail_cache,
    detect_kangaroo_tails,
    kangaroo_tail_confirmed_as_of,
    latest_kangaroo_tail,
)

_FILLER = {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}


def _filler_bar() -> dict:
    return dict(_FILLER)


def _build_ohlcv(n: int, overrides: dict[int, dict]) -> pd.DataFrame:
    rows = [_filler_bar() for _ in range(n)]
    for i, bar in overrides.items():
        rows[i] = bar
    index = pd.bdate_range(start="2024-01-02", periods=n)
    return pd.DataFrame(rows, index=index)


# An upward-pointing tail at position 10 (10 filler bars 0-9, tail at 10, confirming bar at
# 11): high=110 is a new high well beyond the filler window's own max high (101); low=99.0
# matches the filler low exactly (not a new low, so only the "up" direction qualifies);
# range = 110 - 99 = 11.0, baseline = 2.0 (every filler bar's own constant range), so
# range_multiple = 5.5 (>= the 2.5x threshold). Body (open=100.0, close=100.5) retraces
# (110-100)/11=0.909 and (110-100.5)/11=0.864 of the range back from the tip -- both well past
# the 0.5 minimum. The confirming bar (11) has a normal 3.0 range and closes at 99.0, below the
# tail's own 100.5 close -- confirming the bearish reversal.
def _up_tail_overrides() -> dict[int, dict]:
    return {
        10: {"open": 100.0, "high": 110.0, "low": 99.0, "close": 100.5},
        11: {"open": 100.5, "high": 101.5, "low": 98.5, "close": 99.0},
    }


# The mirror-image downward tail: low=90.0 is a new low well beyond the filler window's own
# min low (99); high=101.0 matches the filler high exactly (only "down" qualifies);
# range = 101 - 90 = 11.0, same baseline/multiple as above. Body (open=100.0, close=99.5)
# retraces (100-90)/11=0.909 and (99.5-90)/11=0.864. The confirming bar closes at 101.0, above
# the tail's own 99.5 close -- confirming the bullish reversal.
def _down_tail_overrides() -> dict[int, dict]:
    return {
        10: {"open": 100.0, "high": 101.0, "low": 90.0, "close": 99.5},
        11: {"open": 99.5, "high": 101.0, "low": 98.5, "close": 101.0},
    }


class TestUpwardTailDetection:
    def test_detects_confirmed_up_tail_with_expected_fields(self) -> None:
        daily_ohlcv = _build_ohlcv(12, _up_tail_overrides())

        tails = detect_kangaroo_tails(daily_ohlcv)

        assert len(tails) == 1
        tail = tails[0]
        assert tail.direction == "up"
        assert tail.date == daily_ohlcv.index[10]
        assert tail.confirmed_date == daily_ohlcv.index[11]
        assert tail.high == pytest.approx(110.0)
        assert tail.low == pytest.approx(99.0)
        assert tail.range_multiple == pytest.approx(5.5)
        assert tail.suggested_stop == pytest.approx((110.0 + 99.0) / 2)


class TestDownwardTailDetection:
    def test_detects_confirmed_down_tail_with_expected_fields(self) -> None:
        daily_ohlcv = _build_ohlcv(12, _down_tail_overrides())

        tails = detect_kangaroo_tails(daily_ohlcv)

        assert len(tails) == 1
        tail = tails[0]
        assert tail.direction == "down"
        assert tail.date == daily_ohlcv.index[10]
        assert tail.confirmed_date == daily_ohlcv.index[11]
        assert tail.high == pytest.approx(101.0)
        assert tail.low == pytest.approx(90.0)
        assert tail.range_multiple == pytest.approx(5.5)
        assert tail.suggested_stop == pytest.approx((101.0 + 90.0) / 2)


class TestGatingConditions:
    """Each test disturbs exactly one required condition of the base up-tail fixture and
    confirms detection correctly fails -- proving every checklist requirement (shape, both
    directions, flanking normality, and the confirming-next-bar check) is independently
    enforced, not accidentally satisfied by some other passing condition."""

    def test_range_below_multiplier_threshold_does_not_qualify(self) -> None:
        overrides = _up_tail_overrides()
        # range = 102 - 99 = 3.0; baseline 2.0 -> multiple 1.5, below the 2.5x threshold.
        overrides[10] = {"open": 100.0, "high": 102.0, "low": 99.0, "close": 100.5}

        assert detect_kangaroo_tails(_build_ohlcv(12, overrides)) == []

    def test_meeting_the_range_multiple_alone_is_not_enough_without_a_new_extreme(self) -> None:
        """Isolates the "protruding from a tight recent range" requirement from the plain
        range-multiplier one: uses a drifting (not flat) window, where the window's own
        high/low span is wider than any single bar's own range, so a candidate can meet the
        2.5x-average-range bar while still not exceeding the window's actual high/low bounds."""
        drifting_closes = [100.0 + 0.2 * i for i in range(10)]
        rows = [
            {"open": c, "high": c + 0.5, "low": c - 0.5, "close": c} for c in drifting_closes
        ]
        # Window high max = 101.8 + 0.5 = 102.3, window low min = 100.0 - 0.5 = 99.5, baseline
        # range = 1.0 (every filler bar's own constant range). A candidate with range 2.5
        # (exactly the 2.5x threshold) whose high/low both stay inside [99.5, 102.3] meets the
        # multiplier but makes no new extreme at all.
        rows.append({"open": 100.5, "high": 102.0, "low": 99.5, "close": 100.7})
        rows.append({"open": 100.7, "high": 101.2, "low": 100.2, "close": 100.9})  # confirming
        daily_ohlcv = pd.DataFrame(rows, index=pd.bdate_range(start="2024-01-02", periods=12))

        assert detect_kangaroo_tails(daily_ohlcv) == []

    def test_body_not_retraced_from_tip_does_not_qualify(self) -> None:
        overrides = _up_tail_overrides()
        # close=109.0 sits only (110-109)/11 == 0.09 of the range back from the tip -- far
        # short of the 0.5 minimum retracement ("close ends up back near the open, not at the
        # extreme").
        overrides[10] = {"open": 100.0, "high": 110.0, "low": 99.0, "close": 109.0}

        assert detect_kangaroo_tails(_build_ohlcv(12, overrides)) == []

    def test_before_flank_bar_itself_tail_sized_does_not_qualify(self) -> None:
        overrides = _up_tail_overrides()
        overrides[9] = {"open": 100.0, "high": 108.0, "low": 99.0, "close": 100.0}

        assert detect_kangaroo_tails(_build_ohlcv(12, overrides)) == []

    def test_after_flank_bar_itself_tail_sized_does_not_qualify(self) -> None:
        overrides = _up_tail_overrides()
        # Even though it still closes below the tail's own close (confirming direction), a
        # tail-sized range on the confirming bar itself fails the "normal height" flanking
        # requirement.
        overrides[11] = {"open": 100.5, "high": 101.0, "low": 70.0, "close": 90.0}

        assert detect_kangaroo_tails(_build_ohlcv(12, overrides)) == []

    def test_confirming_bar_wrong_direction_does_not_qualify(self) -> None:
        overrides = _up_tail_overrides()
        # Normal range (2.0, well under the 5.0 tail-sized threshold -- passes the flanking
        # "normal height" check) but closes ABOVE the tail's own close (100.5) instead of
        # continuing down -- shape matches, flanking is normal, but the reversal isn't
        # confirmed.
        overrides[11] = {"open": 100.5, "high": 102.0, "low": 100.0, "close": 101.0}

        assert detect_kangaroo_tails(_build_ohlcv(12, overrides)) == []

    def test_no_bar_after_the_candidate_does_not_qualify(self) -> None:
        # The tail is the very last bar in the series -- no confirming bar exists yet.
        daily_ohlcv = _build_ohlcv(11, {10: _up_tail_overrides()[10]})

        assert detect_kangaroo_tails(daily_ohlcv) == []

    def test_outside_bar_new_high_and_new_low_defaults_to_up_direction(self) -> None:
        """A degenerate "outside bar" -- simultaneously a new high AND a new low beyond the
        full lookback window -- exercises the `makes_new_high and makes_new_low` tie-break in
        `_evaluate_candidate`, which defaults to `direction="up"` (docs/tasks/backend-kangaroo-
        tail-pattern-followups.json's `decisions` entry). high=110.0 is a new high (beyond the
        filler window's own 101.0 max) and low=90.0 is a new low (beyond the filler window's
        own 99.0 min) at the same bar; range = 20.0, baseline = 2.0, multiple = 10.0 (well past
        the 2.5x threshold). Body (open=95.0, close=95.5) sits in the bottom half, retracing
        (110-95)/20=0.75 and (110-95.5)/20=0.725 from the top -- satisfying the "up" body-
        position check (retracement measured from the high, since direction resolved to "up"),
        which a "down" resolution's retracement-from-the-low check would NOT have satisfied
        ((95-90)/20=0.25, (95.5-90)/20=0.275 -- both well under the 0.5 minimum), so this test
        also incidentally proves the tie-break actually took effect rather than either
        direction happening to pass by coincidence."""
        overrides = {
            10: {"open": 95.0, "high": 110.0, "low": 90.0, "close": 95.5},
            11: {"open": 95.5, "high": 96.5, "low": 93.5, "close": 94.0},
        }
        daily_ohlcv = _build_ohlcv(12, overrides)

        tails = detect_kangaroo_tails(daily_ohlcv)

        assert len(tails) == 1
        tail = tails[0]
        assert tail.direction == "up"
        assert tail.high == pytest.approx(110.0)
        assert tail.low == pytest.approx(90.0)
        assert tail.range_multiple == pytest.approx(10.0)


class TestLatestKangarooTail:
    def test_returns_none_when_no_tail_detected(self) -> None:
        daily_ohlcv = _build_ohlcv(12, {})

        assert latest_kangaroo_tail(daily_ohlcv) is None

    def test_returns_the_most_recent_of_several_tails(self) -> None:
        overrides = _up_tail_overrides()
        # A second, later up-tail pattern, starting far enough after the first one's
        # confirming bar (11) that its own lookback window (positions 15-24) is pure filler
        # again.
        overrides[25] = {"open": 100.0, "high": 112.0, "low": 99.0, "close": 100.5}
        overrides[26] = {"open": 100.5, "high": 101.5, "low": 98.5, "close": 99.0}
        daily_ohlcv = _build_ohlcv(30, overrides)

        result = latest_kangaroo_tail(daily_ohlcv)

        assert result is not None
        assert result.date == daily_ohlcv.index[25]
        assert result.confirmed_date == daily_ohlcv.index[26]


class TestKangarooTailCacheAsOf:
    def test_as_of_before_confirmation_returns_none(self) -> None:
        daily_ohlcv = _build_ohlcv(12, _up_tail_overrides())
        cache = build_kangaroo_tail_cache(daily_ohlcv)

        assert kangaroo_tail_confirmed_as_of(cache, 10) is None

    def test_as_of_on_and_after_confirmation_returns_the_tail(self) -> None:
        daily_ohlcv = _build_ohlcv(12, _up_tail_overrides())
        cache = build_kangaroo_tail_cache(daily_ohlcv)

        confirmed = kangaroo_tail_confirmed_as_of(cache, 11)
        assert confirmed is not None
        assert confirmed.date == daily_ohlcv.index[10]

    def test_as_of_reflects_the_most_recent_tail_confirmed_by_then(self) -> None:
        overrides = _up_tail_overrides()
        overrides[25] = {"open": 100.0, "high": 112.0, "low": 99.0, "close": 100.5}
        overrides[26] = {"open": 100.5, "high": 101.5, "low": 98.5, "close": 99.0}
        daily_ohlcv = _build_ohlcv(30, overrides)
        cache = build_kangaroo_tail_cache(daily_ohlcv)

        # Right after the first tail confirms, but before the second one exists yet.
        first_only = kangaroo_tail_confirmed_as_of(cache, 15)
        assert first_only is not None
        assert first_only.date == daily_ohlcv.index[10]

        # Once the second tail's own confirming bar has arrived, it supersedes the first.
        second = kangaroo_tail_confirmed_as_of(cache, 26)
        assert second is not None
        assert second.date == daily_ohlcv.index[25]


class TestValidationAndDegenerateInputs:
    def test_empty_daily_ohlcv_returns_no_tails(self) -> None:
        daily_ohlcv = pd.DataFrame(columns=["open", "high", "low", "close"])

        assert detect_kangaroo_tails(daily_ohlcv) == []

    def test_too_short_daily_ohlcv_returns_no_tails(self) -> None:
        daily_ohlcv = _build_ohlcv(DEFAULT_LOOKBACK, {})  # needs lookback + 2 bars minimum

        assert detect_kangaroo_tails(daily_ohlcv) == []

    def test_missing_required_column_raises_value_error(self) -> None:
        daily_ohlcv = _build_ohlcv(12, {}).drop(columns=["open"])

        with pytest.raises(ValueError, match="open"):
            detect_kangaroo_tails(daily_ohlcv)

    def test_lookback_below_one_raises_value_error(self) -> None:
        daily_ohlcv = _build_ohlcv(12, {})

        with pytest.raises(ValueError, match="lookback"):
            detect_kangaroo_tails(daily_ohlcv, lookback=0)

    def test_custom_range_multiplier_of_zero_is_handled_without_dividing_by_zero(self) -> None:
        # A degenerate custom multiplier (0.0) makes ANY bar range "tail-sized" against a
        # positive baseline, including a flat (zero-range) one -- combined with a flat bar
        # priced at a genuine new high (105.0, above the filler window's own 101.0 max), this
        # exercises `_body_retraced_from_tip`'s own `bar_range <= 0` guard, which the default
        # 2.5x multiplier can never reach (it always requires a strictly positive bar_range
        # once qualified).
        overrides = {10: {"open": 105.0, "high": 105.0, "low": 105.0, "close": 105.0}}
        daily_ohlcv = _build_ohlcv(12, overrides)

        assert detect_kangaroo_tails(daily_ohlcv, range_multiplier=0.0) == []

    def test_flat_lookback_window_baseline_never_qualifies_any_candidate(self) -> None:
        # Every bar (filler and candidate alike) is perfectly flat -- baseline_range is 0,
        # which `_is_tail_sized` treats as "never tail-sized" (no meaningful multiple of a
        # zero baseline), rather than dividing by zero.
        flat = {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}
        daily_ohlcv = pd.DataFrame([dict(flat) for _ in range(12)], index=pd.bdate_range(start="2024-01-02", periods=12))

        assert detect_kangaroo_tails(daily_ohlcv) == []


class TestKangarooTailDataclass:
    def test_is_a_plain_frozen_dataclass_with_expected_fields(self) -> None:
        tail = KangarooTail(
            direction="up",
            date=pd.Timestamp("2024-01-01"),
            confirmed_date=pd.Timestamp("2024-01-02"),
            high=110.0,
            low=99.0,
            range_multiple=5.5,
            suggested_stop=104.5,
        )

        assert tail.direction == "up"
        assert tail.suggested_stop == pytest.approx(104.5)


class TestBIIBAndFDOWorkedExamples:
    """docs/tasks/backend-kangaroo-tail-pattern.json's checklist asks for tests reproducing
    the book's own worked examples (BIIB upward tail, FDO downward tail) "as closely as
    fixture data allows". Grepping docs/ideas.md and docs/Analyse.md for 'BIIB'/'FDO' finds no
    transcribed numeric OHLC data for either chart (same situation the backend-divergence-
    detection task found for its own claimed 'DJIA 2007-2009' example, which also turned out
    not to be present in the docs) -- these are synthetic fixtures reproducing each example's
    *qualitative* shape as described in the task itself (an upward/downward tail flanked by
    normal bars, confirmed by the next bar), not a numeric transcription of the real charts.
    See this task's `decisions` entry."""

    def test_biib_style_upward_tail_is_a_bearish_reversal_signal(self) -> None:
        # BIIB (Biogen): a sharp upward tail spiking to a new high on heavy volatility after a
        # tight consolidation, closing back down near the open -- flagged as an upward
        # (bearish) tail, confirmed by the next bar continuing lower.
        daily_ohlcv = _build_ohlcv(12, _up_tail_overrides())

        tail = latest_kangaroo_tail(daily_ohlcv)

        assert tail is not None
        assert tail.direction == "up"

    def test_fdo_style_downward_tail_is_a_bullish_reversal_signal(self) -> None:
        # FDO (Family Dollar): a sharp downward tail spiking to a new low after a tight
        # consolidation, closing back up near the open -- flagged as a downward (bullish) tail,
        # confirmed by the next bar continuing higher.
        daily_ohlcv = _build_ohlcv(12, _down_tail_overrides())

        tail = latest_kangaroo_tail(daily_ohlcv)

        assert tail is not None
        assert tail.direction == "down"


def test_default_constants_match_documented_values() -> None:
    assert DEFAULT_LOOKBACK == 10
    assert DEFAULT_RANGE_MULTIPLIER == 2.5
