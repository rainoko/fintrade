"""Serialization tests for the portfolio domain models (app/portfolio/models.py).

Each expected payload below is copied verbatim from the `GET /api/portfolio` JSON
example in docs/architecture/API.md so a drift between the model and the documented
contract shows up as a failing test, not just a stale checklist checkbox.
"""

from datetime import date

from app.portfolio.models import Account, Equity, Position

# Exact JSON example from docs/architecture/API.md's `GET /api/portfolio` section.
API_MD_POSITION_EXAMPLE = {
    "id": "pos_123",
    "ticker": "AAPL",
    "quantity": 100,
    "avg_cost_basis": 195.30,
    "entry_date": "2026-05-14",
    "current_price": 228.9,
    "unrealized_pnl_pct": 17.2,
}

API_MD_EQUITY_EXAMPLE = {
    "cash": 5000.00,
    "positions_value": 42000.00,
    "total": 47000.00,
}

API_MD_ACCOUNT_EXAMPLE = {
    "equity": API_MD_EQUITY_EXAMPLE,
    "positions": [API_MD_POSITION_EXAMPLE],
}


class TestPosition:
    def test_serializes_to_api_md_example(self) -> None:
        position = Position(
            id="pos_123",
            ticker="AAPL",
            quantity=100,
            avg_cost_basis=195.30,
            entry_date=date(2026, 5, 14),
            current_price=228.9,
            unrealized_pnl_pct=17.2,
        )

        assert position.model_dump(mode="json") == API_MD_POSITION_EXAMPLE

    def test_deserializes_from_api_md_example(self) -> None:
        position = Position.model_validate(API_MD_POSITION_EXAMPLE)

        assert position.id == "pos_123"
        assert position.ticker == "AAPL"
        assert position.quantity == 100
        assert position.avg_cost_basis == 195.30
        assert position.entry_date == date(2026, 5, 14)
        assert position.current_price == 228.9
        assert position.unrealized_pnl_pct == 17.2
        # Round-tripping the parsed model back to JSON must reproduce the exact
        # documented example, not just equivalent-but-differently-shaped data.
        assert position.model_dump(mode="json") == API_MD_POSITION_EXAMPLE

    def test_current_price_and_pnl_default_to_none(self) -> None:
        """current_price/unrealized_pnl_pct are unknown until a price is fetched
        (e.g. right after POST /api/portfolio/positions), so they must be optional."""
        position = Position(
            id="pos_new",
            ticker="MSFT",
            quantity=10,
            avg_cost_basis=300.0,
            entry_date=date(2026, 1, 1),
        )

        assert position.current_price is None
        assert position.unrealized_pnl_pct is None


class TestEquity:
    def test_serializes_to_api_md_example(self) -> None:
        equity = Equity(cash=5000.00, positions_value=42000.00, total=47000.00)

        assert equity.model_dump(mode="json") == API_MD_EQUITY_EXAMPLE

    def test_deserializes_from_api_md_example(self) -> None:
        equity = Equity.model_validate(API_MD_EQUITY_EXAMPLE)

        assert equity.cash == 5000.00
        assert equity.positions_value == 42000.00
        assert equity.total == 47000.00
        assert equity.model_dump(mode="json") == API_MD_EQUITY_EXAMPLE


class TestAccount:
    def test_serializes_to_api_md_get_portfolio_example(self) -> None:
        account = Account(
            equity=Equity(cash=5000.00, positions_value=42000.00, total=47000.00),
            positions=[
                Position(
                    id="pos_123",
                    ticker="AAPL",
                    quantity=100,
                    avg_cost_basis=195.30,
                    entry_date=date(2026, 5, 14),
                    current_price=228.9,
                    unrealized_pnl_pct=17.2,
                )
            ],
        )

        assert account.model_dump(mode="json") == API_MD_ACCOUNT_EXAMPLE

    def test_deserializes_from_api_md_get_portfolio_example(self) -> None:
        account = Account.model_validate(API_MD_ACCOUNT_EXAMPLE)

        assert account.equity.total == 47000.00
        assert len(account.positions) == 1
        assert account.positions[0].ticker == "AAPL"
        assert account.model_dump(mode="json") == API_MD_ACCOUNT_EXAMPLE

    def test_positions_defaults_to_empty_list_shape(self) -> None:
        """An account with no positions should still round-trip to a valid,
        empty-but-well-shaped GET /api/portfolio response."""
        account = Account(
            equity=Equity(cash=1000.0, positions_value=0.0, total=1000.0),
            positions=[],
        )

        assert account.model_dump(mode="json") == {
            "equity": {"cash": 1000.0, "positions_value": 0.0, "total": 1000.0},
            "positions": [],
        }
