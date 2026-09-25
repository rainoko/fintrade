"""Direct unit tests for `app.data.base.resample_ohlcv` (docs/tasks/
backend-day-trader-timeframe-mode-ibkr-intraday-followups-followups.json).

Before this module existed, `resample_ohlcv`'s aggregation-rule and incomplete-bin-dropped
contract was only exercised indirectly, via `StooqProvider._resample_weekly`'s (daily -> weekly)
and `app.data.day_trader_intraday._resample_to_target`'s (IBKR-native minutes -> requested
`TimeframeInterval` width) own tests -- both of which pin down behavior-preservation for their
own specific rule strings, but not `resample_ohlcv`'s contract independent of either caller.
These tests hand-compute the expected OHLCV aggregation directly against the helper itself, so a
future third caller (or an edit to either existing caller) can't silently break the shared
helper's contract without a test catching it at the source.
"""

from datetime import UTC, datetime

import pandas as pd

from app.data.base import resample_ohlcv


def _frame(rows: list[tuple[datetime, float, float, float, float, float]]) -> pd.DataFrame:
    """Builds an OHLCV-shaped frame (columns: open, high, low, close, volume; indexed by a
    UTC `DatetimeIndex`) from `(timestamp, open, high, low, close, volume)` rows."""
    index = pd.DatetimeIndex([row[0] for row in rows], name="date")
    return pd.DataFrame(
        {
            "open": [row[1] for row in rows],
            "high": [row[2] for row in rows],
            "low": [row[3] for row in rows],
            "close": [row[4] for row in rows],
            "volume": [row[5] for row in rows],
        },
        index=index,
    )


class TestResampleOhlcv:
    def test_aggregates_open_first_high_max_low_min_close_last_volume_sum(self) -> None:
        # Two whole 10-minute bins, each built from two 5-minute source bars, at
        # hand-computed values so every aggregation rule is independently checkable.
        frame = _frame(
            [
                (datetime(2026, 1, 5, 15, 0, tzinfo=UTC), 100.0, 102.0, 99.0, 101.0, 1_000.0),
                (datetime(2026, 1, 5, 15, 5, tzinfo=UTC), 101.0, 103.0, 100.5, 102.0, 1_500.0),
                (datetime(2026, 1, 5, 15, 10, tzinfo=UTC), 102.0, 104.0, 101.0, 103.5, 2_000.0),
                (datetime(2026, 1, 5, 15, 15, tzinfo=UTC), 103.5, 105.0, 103.0, 104.0, 2_500.0),
            ]
        )

        result = resample_ohlcv(frame, "10min")

        assert result.index.name == "date"
        assert len(result) == 2
        # First 10-minute bin: [15:00, 15:10) -- the first two source rows.
        assert result["open"].iloc[0] == 100.0  # first row's open
        assert result["high"].iloc[0] == 103.0  # max(102.0, 103.0)
        assert result["low"].iloc[0] == 99.0  # min(99.0, 100.5)
        assert result["close"].iloc[0] == 102.0  # last row's close
        assert result["volume"].iloc[0] == 2_500.0  # 1_000.0 + 1_500.0
        # Second 10-minute bin: [15:10, 15:20) -- the last two source rows.
        assert result["open"].iloc[1] == 102.0
        assert result["high"].iloc[1] == 105.0  # max(104.0, 105.0)
        assert result["low"].iloc[1] == 101.0  # min(101.0, 103.0)
        assert result["close"].iloc[1] == 104.0
        assert result["volume"].iloc[1] == 4_500.0  # 2_000.0 + 2_500.0

    def test_a_bin_with_only_one_source_bar_is_kept_not_treated_as_incomplete(self) -> None:
        # A bin containing exactly one source bar is a fully valid result (every OHLC column
        # comes from that single bar) -- "incomplete" (dropped) specifically means *no* bars
        # fell in the bin at all (every column NaN), not merely fewer than a full period's
        # worth; see test_a_completely_empty_bin_in_the_middle_of_the_range_is_also_dropped
        # for the actual drop case.
        frame = _frame(
            [
                (datetime(2026, 1, 5, 15, 0, tzinfo=UTC), 100.0, 101.0, 99.0, 100.5, 1_000.0),
                (datetime(2026, 1, 5, 15, 5, tzinfo=UTC), 100.5, 102.0, 100.0, 101.5, 1_200.0),
                (datetime(2026, 1, 5, 15, 10, tzinfo=UTC), 101.5, 102.5, 101.0, 102.0, 900.0),
            ]
        )

        result = resample_ohlcv(frame, "10min")

        assert len(result) == 2
        assert result["open"].iloc[1] == 101.5
        assert result["high"].iloc[1] == 102.5
        assert result["low"].iloc[1] == 101.0
        assert result["close"].iloc[1] == 102.0
        assert result["volume"].iloc[1] == 900.0

    def test_empty_frame_resamples_to_an_empty_frame(self) -> None:
        frame = pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"], index=pd.DatetimeIndex([], name="date")
        )

        result = resample_ohlcv(frame, "10min")

        assert result.empty
        assert list(result.columns) == ["open", "high", "low", "close", "volume"]

    def test_a_completely_empty_bin_in_the_middle_of_the_range_is_also_dropped(self) -> None:
        # A gap spanning an entire bin (no source rows fall in [15:10, 15:20)) must not
        # surface as a row of NaNs either -- only the two bins with real data should remain.
        frame = _frame(
            [
                (datetime(2026, 1, 5, 15, 0, tzinfo=UTC), 100.0, 101.0, 99.0, 100.5, 1_000.0),
                (datetime(2026, 1, 5, 15, 5, tzinfo=UTC), 100.5, 102.0, 100.0, 101.5, 1_200.0),
                (datetime(2026, 1, 5, 15, 20, tzinfo=UTC), 105.0, 106.0, 104.0, 105.5, 800.0),
                (datetime(2026, 1, 5, 15, 25, tzinfo=UTC), 105.5, 107.0, 105.0, 106.5, 900.0),
            ]
        )

        result = resample_ohlcv(frame, "10min")

        assert len(result) == 2
        assert result["open"].iloc[0] == 100.0
        assert result["close"].iloc[0] == 101.5
        assert result["open"].iloc[1] == 105.0
        assert result["close"].iloc[1] == 106.5
