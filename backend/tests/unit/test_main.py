"""Tests for app.main's IBKR /tickle keep-alive lifespan task
(docs/tasks/backend-ibkr-tickle-keepalive.json).

Every test here mocks `Base.metadata.create_all` (app.main's own DB bootstrap step,
already exercised elsewhere) so exercising `lifespan()` directly never touches the real
on-disk database, and mocks `app.main.get_ibkr_provider` (rather than flipping
`Settings.ibkr_enabled` via the real environment) so these tests control the gate
directly -- this app's constraint that `FINTRADE_IBKR_ENABLED` stays `false` throughout
(docs/architecture/Backend.md §8) is never touched here, and no test in this module ever
lets a real `IBKRProvider` make an HTTP call.
"""

import asyncio

import pytest

from app.data.ibkr_provider import IBKRUnavailableError
from app.main import app, lifespan


@pytest.fixture(autouse=True)
def _skip_db_bootstrap(mocker):
    """Every test below calls `lifespan()` directly (not through `TestClient`, which
    never triggers lifespan events unless used as a context manager -- see
    tests/conftest.py's plain `TestClient(app)` fixture), so without this, each test
    would run `Base.metadata.create_all(bind=engine)` against the real on-disk database
    `app.db.session.engine` points at."""
    mocker.patch("app.main.Base.metadata.create_all")


async def _wait_until(predicate, *, timeout: float = 5.0, interval: float = 0.01) -> None:
    """Poll `predicate()` on a real timer until it's true, instead of a fixed count of
    `asyncio.sleep(0)` cooperative yields.

    `_ibkr_tickle_loop` calls `IBKRProvider.tickle()` via `asyncio.to_thread` -- a real
    thread-pool round trip -- so a fixed iteration count of bare cooperative yields isn't
    guaranteed to let it complete even once (let alone twice) before the test gives up;
    under load (coverage instrumentation, a concurrent test run) that round trip can take
    longer than 200 `sleep(0)`s do. Sleeping a real, if tiny, `interval` between checks
    gives the worker thread actual wall-clock time to run, and `asyncio.wait_for` still
    bounds the wait so a genuine regression (the loop never calling `tickle()` at all)
    fails promptly instead of hanging.
    """

    async def _poll() -> None:
        while not predicate():
            await asyncio.sleep(interval)

    await asyncio.wait_for(_poll(), timeout=timeout)


class TestLifespanIbkrTickleGate:
    def test_disabled_never_starts_a_task_or_touches_the_gateway(self, mocker) -> None:
        """`get_ibkr_provider` yielding `None` (the default -- `Settings.ibkr_enabled`
        is `False`) must mean no background task is ever created, per this task's own
        constraint that the lifespan task is a genuine no-op while disabled."""
        mocker.patch("app.main.get_ibkr_provider", return_value=iter([None]))
        create_task = mocker.patch("app.main.asyncio.create_task")

        async def _run() -> None:
            async with lifespan(app):
                pass

        asyncio.run(_run())

        create_task.assert_not_called()

    def test_enabled_starts_a_task_that_calls_tickle(self, mocker) -> None:
        fake_provider = mocker.Mock()
        mocker.patch("app.main.get_ibkr_provider", return_value=iter([fake_provider]))
        # 0s so the loop's very first `asyncio.sleep` yields control without any real delay.
        mocker.patch("app.main._IBKR_TICKLE_INTERVAL_SECONDS", 0.0)

        async def _run() -> None:
            async with lifespan(app):
                await _wait_until(lambda: fake_provider.tickle.called)

        asyncio.run(_run())

        fake_provider.tickle.assert_called()

    def test_enabled_task_is_cancelled_cleanly_on_shutdown(self, mocker) -> None:
        fake_provider = mocker.Mock()
        mocker.patch("app.main.get_ibkr_provider", return_value=iter([fake_provider]))
        # Long enough that the loop is guaranteed to still be sleeping (not mid-tickle)
        # when the `async with` block below exits and triggers shutdown.
        mocker.patch("app.main._IBKR_TICKLE_INTERVAL_SECONDS", 100.0)
        create_task_spy = mocker.spy(asyncio, "create_task")

        async def _run() -> None:
            async with lifespan(app):
                await asyncio.sleep(0)

        asyncio.run(_run())

        task = create_task_spy.spy_return
        assert task is not None
        assert task.cancelled()
        fake_provider.tickle.assert_not_called()

    def test_enabled_logs_and_keeps_looping_when_tickle_fails(self, mocker, caplog) -> None:
        """A single failed `/tickle` call (gateway down, session actually expired) must
        not kill the loop -- `GET /api/ibkr/status` already exists for a caller to
        observe the resulting state, so this loop's job is only to keep pinging."""
        fake_provider = mocker.Mock()
        fake_provider.tickle.side_effect = IBKRUnavailableError("gateway unreachable")
        mocker.patch("app.main.get_ibkr_provider", return_value=iter([fake_provider]))
        mocker.patch("app.main._IBKR_TICKLE_INTERVAL_SECONDS", 0.0)

        async def _run() -> None:
            with caplog.at_level("WARNING", logger="app.main"):
                async with lifespan(app):
                    await _wait_until(lambda: fake_provider.tickle.call_count >= 2)

        asyncio.run(_run())

        assert fake_provider.tickle.call_count >= 2
        assert "IBKR /tickle keep-alive call failed" in caplog.text
