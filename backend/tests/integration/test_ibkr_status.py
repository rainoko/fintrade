"""Integration tests for GET /api/ibkr/status (docs/tasks/backend-ibkr-status-endpoint.json,
docs/tasks/backend-ibkr-login-url.json).

Overrides `app.api.dependencies.get_ibkr_provider` directly (the same dependency-injection
seam `tests/unit/api/test_dependencies.py` exercises) rather than touching `IBKRProvider`'s
HTTP boundary -- this endpoint's own logic is just "map whatever `get_ibkr_provider` yields /
`get_gateway_status()` reports onto a response", not anything HTTP-shaped itself. A small stub
standing in for `IBKRProvider` exercises each of `get_gateway_status()`'s possible results
without ever calling the real class or its `_request` boundary -- matching this task's "no
sandboxed/CI environment has a live authenticated gateway" constraint
(`app/data/ibkr_provider.py`'s own module docstring; `tests/unit/data/test_ibkr_provider.py`
mocks at the same `_request` boundary for the provider's own tests).

`login_url` derivation is exercised via `monkeypatch.setenv("FINTRADE_IBKR_BASE_URL", ...)` +
`get_settings.cache_clear()` (the same pattern `tests/unit/api/test_dependencies.py` already
uses for `Settings.ibkr_base_url`) rather than relying on this dev container's own real
`.env` value (`FINTRADE_IBKR_BASE_URL=https://ibkr.home.arpa/v1/api`, present only for manual
dev-server checking against a real reachable gateway per this task's own standing
constraints) -- the automated suite must stay deterministic and independent of whatever this
specific environment happens to have configured.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_ibkr_provider
from app.config import get_settings
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
    against for the singleton itself. Also clears `get_settings`'s cache on teardown so a
    test's `monkeypatch.setenv("FINTRADE_IBKR_BASE_URL", ...)` never leaks a stale
    `Settings` instance into a later test (monkeypatch itself reverts the env var, but not
    the already-`lru_cache`d `Settings` object built from it)."""
    yield
    app.dependency_overrides.pop(get_ibkr_provider, None)
    get_settings.cache_clear()


def test_status_disabled(client: TestClient) -> None:
    """`get_ibkr_provider` yields `None` exactly when `Settings.ibkr_enabled` is `False`
    (this app's default) -- the endpoint must surface that as an explicit 'disabled'
    state, never attempting to reach a gateway at all. `login_url` stays null even though
    `Settings.ibkr_base_url` is still configured -- there's no gateway to log into."""

    def override() -> Iterator[None]:
        yield None

    app.dependency_overrides[get_ibkr_provider] = override

    response = client.get("/api/ibkr/status")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "disabled"
    assert body["detail"] is not None
    assert body["login_url"] is None


def test_status_available(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINTRADE_IBKR_BASE_URL", "https://localhost:5000/v1/api")
    get_settings.cache_clear()

    def override() -> Iterator[_StubIBKRProvider]:
        yield _StubIBKRProvider(GatewayStatus(state="available"))

    app.dependency_overrides[get_ibkr_provider] = override

    response = client.get("/api/ibkr/status")

    assert response.status_code == 200
    assert response.json() == {
        "state": "available",
        "detail": None,
        "login_url": "https://localhost:5000",
    }


def test_status_gateway_unreachable(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """`login_url` stays null for `gateway_unreachable` even though `Settings.ibkr_base_url`
    is configured -- the derived URL wouldn't be reachable either, since no gateway process
    answered at all."""
    monkeypatch.setenv("FINTRADE_IBKR_BASE_URL", "https://localhost:5000/v1/api")
    get_settings.cache_clear()

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
        "login_url": None,
    }


def test_status_not_authenticated(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINTRADE_IBKR_BASE_URL", "https://ibkr.home.arpa/v1/api")
    get_settings.cache_clear()

    def override() -> Iterator[_StubIBKRProvider]:
        yield _StubIBKRProvider(GatewayStatus(state="not_authenticated", detail="please log in"))

    app.dependency_overrides[get_ibkr_provider] = override

    response = client.get("/api/ibkr/status")

    assert response.status_code == 200
    assert response.json() == {
        "state": "not_authenticated",
        "detail": "please log in",
        "login_url": "https://ibkr.home.arpa",
    }


def test_status_not_authenticated_login_url_with_non_default_port_and_path_prefix(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-trivial `ibkr_base_url`: a non-default port, plus a leading path segment (e.g.
    a reverse proxy in front of the gateway) that must be preserved -- only the trailing
    `/v1/api` REST-API-root suffix is stripped, not the whole path."""
    monkeypatch.setenv("FINTRADE_IBKR_BASE_URL", "https://gateway.example.com:5001/proxy/v1/api")
    get_settings.cache_clear()

    def override() -> Iterator[_StubIBKRProvider]:
        yield _StubIBKRProvider(GatewayStatus(state="not_authenticated", detail="please log in"))

    app.dependency_overrides[get_ibkr_provider] = override

    response = client.get("/api/ibkr/status")

    assert response.status_code == 200
    assert response.json()["login_url"] == "https://gateway.example.com:5001/proxy"


def test_status_available_login_url_with_trailing_slash_base_url(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`Settings.ibkr_base_url` never has a trailing slash in practice (neither the field's
    own default nor `DEFAULT_BASE_URL` do), but the derivation is defensive against a
    manually-configured value that does."""
    monkeypatch.setenv("FINTRADE_IBKR_BASE_URL", "https://localhost:5000/v1/api/")
    get_settings.cache_clear()

    def override() -> Iterator[_StubIBKRProvider]:
        yield _StubIBKRProvider(GatewayStatus(state="available"))

    app.dependency_overrides[get_ibkr_provider] = override

    response = client.get("/api/ibkr/status")

    assert response.status_code == 200
    assert response.json()["login_url"] == "https://localhost:5000"
