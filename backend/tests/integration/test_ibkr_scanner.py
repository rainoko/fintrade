"""Integration tests for GET /api/ibkr/scanner/params and POST /api/ibkr/scanner/run
(docs/tasks/backend-market-scanner.json).

Same approach as `test_ibkr_status.py`: overrides `app.api.dependencies.get_ibkr_provider`
directly with a small stub, never touching `IBKRProvider`'s real HTTP boundary (per
docs/architecture/Testing.md's "no live network calls" rule and this module's own
"no sandboxed/CI environment has a live authenticated gateway" constraint).
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_ibkr_provider
from app.data.ibkr_provider import (
    GatewayStatus,
    IBKRRateLimitedError,
    IBKRUnavailableError,
    ScannerResult,
)
from app.main import app

_AVAILABLE = GatewayStatus(state="available")


class _StubIBKRProvider:
    """Stands in for `IBKRProvider`, exposing only the methods these two routes call.

    `scanner_params_result`/`run_scanner_result` may each be either a return value or an
    `Exception` instance to raise -- covering both the happy path and the
    `IBKRUnavailableError`/`IBKRRateLimitedError` cases the handlers catch.
    """

    def __init__(
        self,
        *,
        status: GatewayStatus = _AVAILABLE,
        scanner_params_result: dict | Exception | None = None,
        run_scanner_result: list[ScannerResult] | Exception | None = None,
    ) -> None:
        self._status = status
        self._scanner_params_result = scanner_params_result
        self._run_scanner_result = run_scanner_result

    def get_gateway_status(self) -> GatewayStatus:
        return self._status

    def get_scanner_params(self) -> dict:
        if isinstance(self._scanner_params_result, Exception):
            raise self._scanner_params_result
        assert self._scanner_params_result is not None
        return self._scanner_params_result

    def run_scanner(self, scan_config: dict) -> list[ScannerResult]:
        if isinstance(self._run_scanner_result, Exception):
            raise self._run_scanner_result
        assert self._run_scanner_result is not None
        return self._run_scanner_result


@pytest.fixture(autouse=True)
def _clear_ibkr_override() -> Iterator[None]:
    yield
    app.dependency_overrides.pop(get_ibkr_provider, None)


def _override(provider: _StubIBKRProvider | None) -> None:
    def _dep() -> Iterator[_StubIBKRProvider | None]:
        yield provider

    app.dependency_overrides[get_ibkr_provider] = _dep


class TestGetScannerParams:
    def test_disabled(self, client: TestClient) -> None:
        _override(None)

        response = client.get("/api/ibkr/scanner/params")

        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "disabled"
        assert body["detail"] is not None
        assert body["categories"] is None

    def test_gateway_unreachable(self, client: TestClient) -> None:
        _override(
            _StubIBKRProvider(
                status=GatewayStatus(state="gateway_unreachable", detail="down"),
                scanner_params_result=IBKRUnavailableError("IBKR gateway not available (gateway_unreachable): down"),
            )
        )

        response = client.get("/api/ibkr/scanner/params")

        assert response.status_code == 200
        assert response.json() == {"state": "gateway_unreachable", "detail": "down", "categories": None}

    def test_not_authenticated(self, client: TestClient) -> None:
        _override(
            _StubIBKRProvider(
                status=GatewayStatus(state="not_authenticated", detail="please log in"),
                scanner_params_result=IBKRUnavailableError(
                    "IBKR gateway not available (not_authenticated): please log in"
                ),
            )
        )

        response = client.get("/api/ibkr/scanner/params")

        assert response.status_code == 200
        assert response.json() == {"state": "not_authenticated", "detail": "please log in", "categories": None}

    def test_available_returns_scan_type_list(self, client: TestClient) -> None:
        payload = {
            "scan_type_list": [
                {"code": "TOP_PERC_GAIN", "display_name": "Top % Gainers"},
                {"code": "HIGH_52WEEK", "display_name": "52 Week High"},
            ],
            "instrument_list": [{"type": "STK", "display_name": "Stocks"}],
        }
        _override(_StubIBKRProvider(scanner_params_result=payload))

        response = client.get("/api/ibkr/scanner/params")

        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "available"
        assert body["detail"] is None
        assert body["categories"] == payload["scan_type_list"]

    def test_available_but_no_scan_type_list_returns_empty_categories(self, client: TestClient) -> None:
        _override(_StubIBKRProvider(scanner_params_result={"instrument_list": []}))

        response = client.get("/api/ibkr/scanner/params")

        assert response.status_code == 200
        assert response.json()["categories"] == []


class TestRunScanner:
    _SCAN_CONFIG = {"instrument": "STK", "type": "TOP_PERC_GAIN", "location": "STK.US.MAJOR"}

    def test_disabled(self, client: TestClient) -> None:
        _override(None)

        response = client.post("/api/ibkr/scanner/run", json={"scan_config": self._SCAN_CONFIG})

        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "disabled"
        assert body["detail"] is not None
        assert body["results"] is None

    def test_gateway_unavailable(self, client: TestClient) -> None:
        _override(
            _StubIBKRProvider(
                status=GatewayStatus(state="gateway_unreachable", detail="down"),
                run_scanner_result=IBKRUnavailableError("IBKR gateway not available (gateway_unreachable): down"),
            )
        )

        response = client.post("/api/ibkr/scanner/run", json={"scan_config": self._SCAN_CONFIG})

        assert response.status_code == 200
        assert response.json() == {"state": "gateway_unreachable", "detail": "down", "results": None}

    def test_rate_limited_returns_429(self, client: TestClient) -> None:
        _override(_StubIBKRProvider(run_scanner_result=IBKRRateLimitedError(retry_after=0.42)))

        response = client.post("/api/ibkr/scanner/run", json={"scan_config": self._SCAN_CONFIG})

        assert response.status_code == 429
        assert "retry" in response.json()["detail"].lower()

    def test_successful_scan_returns_results(self, client: TestClient) -> None:
        results = [
            ScannerResult(conid=265598, symbol="AAPL", company_name="Apple Inc", rank=1),
            ScannerResult(conid=272093, symbol="MSFT", company_name="Microsoft Corp", rank=2),
        ]
        _override(_StubIBKRProvider(run_scanner_result=results))

        response = client.post("/api/ibkr/scanner/run", json={"scan_config": self._SCAN_CONFIG})

        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "available"
        assert body["detail"] is None
        assert body["results"] == [
            {"conid": 265598, "symbol": "AAPL", "company_name": "Apple Inc", "rank": 1},
            {"conid": 272093, "symbol": "MSFT", "company_name": "Microsoft Corp", "rank": 2},
        ]

    def test_zero_match_scan_returns_empty_list_not_null(self, client: TestClient) -> None:
        _override(_StubIBKRProvider(run_scanner_result=[]))

        response = client.post("/api/ibkr/scanner/run", json={"scan_config": self._SCAN_CONFIG})

        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "available"
        assert body["results"] == []
