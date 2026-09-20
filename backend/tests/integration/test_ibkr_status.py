"""Integration tests for GET /api/ibkr/status (docs/tasks/backend-ibkr-status-endpoint.json).

Overrides `app.api.dependencies.get_ibkr_provider` directly (the same dependency-injection
seam `tests/unit/api/test_dependencies.py` exercises) rather than touching `IBKRProvider`'s
HTTP boundary -- this endpoint's own logic is just "map whatever `get_ibkr_provider` yields /
`get_gateway_status()` reports onto a response", not anything HTTP-shaped itself. A small stub
standing in for `IBKRProvider` exercises each of `get_gateway_status()`'s possible results
without ever calling the real class or its `_request` boundary -- matching this task's "no
sandboxed/CI environment has a live authenticated gateway" constraint
(`app/data/ibkr_provider.py`'s own module docstring; `tests/unit/data/test_ibkr_provider.py`
mocks at the same `_request` boundary for the provider's own tests).
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_ibkr_provider
from app.data.ibkr_provider import GatewayStatus
from app.main import app


class _StubIBKRProvider:
    """Stands in for `IBKRProvider`, exposing only the one method this endpoint calls."""

    def __init__(self, status: GatewayStatus) -> None:
        self._status = status

    def get_gateway_status(self) -> GatewayStatus:
        return self._status


@pytest.fixture(autouse=True)
def _clear_ibkr_override() -> Iterator[None]:
    """Ensures a dependency override set by one test never leaks into the next, same
    concern `test_dependencies.py`'s `_reset_ibkr_provider_singleton` fixture guards
    against for the singleton itself."""
    yield
    app.dependency_overrides.pop(get_ibkr_provider, None)


def test_status_disabled(client: TestClient) -> None:
    """`get_ibkr_provider` yields `None` exactly when `Settings.ibkr_enabled` is `False`
    (this app's default) -- the endpoint must surface that as an explicit 'disabled'
    state, never attempting to reach a gateway at all."""

    def override() -> Iterator[None]:
        yield None

    app.dependency_overrides[get_ibkr_provider] = override

    response = client.get("/api/ibkr/status")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "disabled"
    assert body["detail"] is not None


def test_status_available(client: TestClient) -> None:
    def override() -> Iterator[_StubIBKRProvider]:
        yield _StubIBKRProvider(GatewayStatus(state="available"))

    app.dependency_overrides[get_ibkr_provider] = override

    response = client.get("/api/ibkr/status")

    assert response.status_code == 200
    assert response.json() == {"state": "available", "detail": None}


def test_status_gateway_unreachable(client: TestClient) -> None:
    def override() -> Iterator[_StubIBKRProvider]:
        yield _StubIBKRProvider(
            GatewayStatus(state="gateway_unreachable", detail="IBKR gateway request to /iserver/auth/status failed")
        )

    app.dependency_overrides[get_ibkr_provider] = override

    response = client.get("/api/ibkr/status")

    assert response.status_code == 200
    assert response.json() == {
        "state": "gateway_unreachable",
        "detail": "IBKR gateway request to /iserver/auth/status failed",
    }


def test_status_not_authenticated(client: TestClient) -> None:
    def override() -> Iterator[_StubIBKRProvider]:
        yield _StubIBKRProvider(GatewayStatus(state="not_authenticated", detail="please log in"))

    app.dependency_overrides[get_ibkr_provider] = override

    response = client.get("/api/ibkr/status")

    assert response.status_code == 200
    assert response.json() == {"state": "not_authenticated", "detail": "please log in"}
