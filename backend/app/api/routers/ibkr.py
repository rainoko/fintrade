"""GET /api/ibkr/status (docs/tasks/backend-ibkr-status-endpoint.json).

The only route in the app that currently consumes `app.api.dependencies.get_ibkr_provider`
at all -- until this task, that dependency existed but nothing called it, leaving the
optional IBKR integration's connection state completely invisible (docs/ideas.md's
"IBKR Client Portal Gateway is now live and authenticated" entry). This is deliberately a
read-only status check, not a data-fetching endpoint: it exists so the app (and, later, a
frontend indicator) can surface "IBKR: connected / not authenticated / gateway down /
disabled" without any route needing to know how `IBKRProvider.get_gateway_status()` itself
works.
"""

from fastapi import APIRouter, Depends

from app.api.dependencies import get_ibkr_provider
from app.api.schemas import IBKRStatusResponse
from app.data.ibkr_provider import IBKRProvider

router = APIRouter(prefix="/api/ibkr", tags=["ibkr"])


@router.get(
    "/status",
    response_model=IBKRStatusResponse,
    operation_id="get_ibkr_status",
    summary="Whether the optional IBKR Client Portal Gateway integration is usable right now",
)
def get_ibkr_status(provider: IBKRProvider | None = Depends(get_ibkr_provider)) -> IBKRStatusResponse:
    """Reports the IBKR gateway's connection state -- 'disabled' when
    `Settings.ibkr_enabled` is `False` (this app's default; `get_ibkr_provider` yields
    `None` in exactly that case, so no attempt to reach a gateway is made at all), otherwise
    whatever `IBKRProvider.get_gateway_status()` reports ('available' / 'gateway_unreachable'
    / 'not_authenticated').

    Never raises for any gateway state: `get_gateway_status()` itself never raises (its own
    docstring's contract -- every failure mode it can observe is represented as a
    `GatewayStatus` value instead of an exception), and this handler adds no failure mode of
    its own on top of that.
    """
    if provider is None:
        return IBKRStatusResponse(
            state="disabled",
            detail="IBKR integration is disabled (FINTRADE_IBKR_ENABLED is not set).",
        )

    status = provider.get_gateway_status()
    return IBKRStatusResponse(state=status.state, detail=status.detail)
