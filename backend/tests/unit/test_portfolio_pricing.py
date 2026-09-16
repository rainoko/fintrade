"""Tests for app.portfolio.pricing (the mark-to-market enrichment loop shared by
GET /api/portfolio and GET /api/portfolio/risk -- see the api-portfolio-risk task's
`decisions` entry for why this was extracted out of the GET /api/portfolio handler).

Mirrors the fixtures/behavior originally covered inline by
tests/integration/test_portfolio_get.py (kept there too, now exercising this module
indirectly through the router), plus unit coverage for `daily_ohlcv` passthrough, which
GET /api/portfolio's own tests never needed to check.
"""

from datetime import date

import pandas as pd
import pytest

from app.data.exceptions import TickerNotFoundError
from app.db.models import PositionORM
from app.portfolio.pricing import enrich_positions_with_price, positions_value


def _frame(closes: list[float]) -> pd.DataFrame:
    idx = pd.DatetimeIndex([f"2026-01-{i + 1:02d}" for i in range(len(closes))], name="date")
    return pd.DataFrame(
        {
            "open": [c - 0.5 for c in closes],
            "high": [c + 1.0 for c in closes],
            "low": [c - 1.0 for c in closes],
            "close": closes,
            "volume": [1_000.0 for _ in closes],
        },
        index=idx,
    )


class _StubProvider:
    def __init__(self, *, prices: dict[str, list[float]] | None = None, failing: set[str] | None = None) -> None:
        self._prices = prices or {}
        self._failing = failing or set()

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        if ticker in self._failing:
            raise TickerNotFoundError(ticker)
        return _frame(self._prices[ticker])

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:  # pragma: no cover - unused here
        raise NotImplementedError


def _row(id: str = "pos_1", ticker: str = "AAPL", quantity: float = 10.0, avg_cost_basis: float = 100.0) -> PositionORM:
    return PositionORM(
        id=id, ticker=ticker, quantity=quantity, avg_cost_basis=avg_cost_basis, entry_date=date(2026, 1, 1)
    )


class TestEnrichPositionsWithPrice:
    def test_successful_fetch_populates_price_pnl_and_frame(self) -> None:
        row = _row(avg_cost_basis=100.0)
        provider = _StubProvider(prices={"AAPL": [100.0, 110.0]})

        [enriched] = enrich_positions_with_price([row], provider)

        assert enriched.position.current_price == pytest.approx(110.0)
        assert enriched.position.unrealized_pnl_pct == pytest.approx(10.0)
        assert enriched.daily_ohlcv is not None
        assert len(enriched.daily_ohlcv) == 2

    def test_failed_fetch_yields_null_price_pnl_and_no_frame(self) -> None:
        row = _row(ticker="ZZZZ")
        provider = _StubProvider(failing={"ZZZZ"})

        [enriched] = enrich_positions_with_price([row], provider)

        assert enriched.position.current_price is None
        assert enriched.position.unrealized_pnl_pct is None
        assert enriched.daily_ohlcv is None

    def test_empty_history_yields_null_price_and_no_frame(self) -> None:
        row = _row()
        provider = _StubProvider(prices={"AAPL": []})

        [enriched] = enrich_positions_with_price([row], provider)

        assert enriched.position.current_price is None
        assert enriched.daily_ohlcv is None

    def test_nan_latest_close_yields_null_price_and_no_frame(self) -> None:
        row = _row()
        provider = _StubProvider(prices={"AAPL": [float("nan")]})

        [enriched] = enrich_positions_with_price([row], provider)

        assert enriched.position.current_price is None
        assert enriched.daily_ohlcv is None

    def test_multiple_positions_enriched_independently(self) -> None:
        rows = [_row(id="pos_1", ticker="AAPL"), _row(id="pos_2", ticker="MSFT")]
        provider = _StubProvider(prices={"AAPL": [110.0], "MSFT": [330.0]})

        enriched = enrich_positions_with_price(rows, provider)

        by_ticker = {e.position.ticker: e for e in enriched}
        assert by_ticker["AAPL"].position.current_price == pytest.approx(110.0)
        assert by_ticker["MSFT"].position.current_price == pytest.approx(330.0)

    def test_empty_rows_yields_empty_list(self) -> None:
        assert enrich_positions_with_price([], _StubProvider()) == []


class TestPositionsValue:
    def test_sums_quantity_times_price_across_priced_positions(self) -> None:
        rows = [
            _row(id="pos_1", ticker="AAPL", quantity=10.0),
            _row(id="pos_2", ticker="MSFT", quantity=5.0),
        ]
        provider = _StubProvider(prices={"AAPL": [110.0], "MSFT": [330.0]})

        enriched = enrich_positions_with_price(rows, provider)

        assert positions_value(enriched) == pytest.approx(10 * 110.0 + 5 * 330.0)

    def test_excludes_positions_with_no_price_rather_than_treating_as_zero(self) -> None:
        rows = [_row(id="pos_1", ticker="AAPL", quantity=10.0), _row(id="pos_2", ticker="ZZZZ", quantity=5.0)]
        provider = _StubProvider(prices={"AAPL": [110.0]}, failing={"ZZZZ"})

        enriched = enrich_positions_with_price(rows, provider)

        assert positions_value(enriched) == pytest.approx(10 * 110.0)

    def test_no_positions_is_zero(self) -> None:
        assert positions_value([]) == pytest.approx(0.0)
