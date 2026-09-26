"""Unit tests for `app.api.routers.ibkr._ibkr_login_page_url`
(docs/tasks/backend-ibkr-login-url.json).

Exercises the URL-derivation helper directly rather than only through the
`GET /api/ibkr/status` endpoint (see tests/integration/test_ibkr_status.py for that) --
covering the defensive "doesn't end with the expected suffix" branch that no real
`Settings.ibkr_base_url` value (its own default or `DEFAULT_BASE_URL`) ever actually
takes, but which the helper handles by returning the origin's path untouched rather than
raising or mangling it.
"""

from app.api.routers.ibkr import _ibkr_login_page_url


def test_strips_v1_api_suffix_from_default_base_url() -> None:
    assert _ibkr_login_page_url("https://localhost:5000/v1/api") == "https://localhost:5000"


def test_strips_v1_api_suffix_with_non_default_port() -> None:
    assert _ibkr_login_page_url("https://ibkr.home.arpa/v1/api") == "https://ibkr.home.arpa"


def test_preserves_a_path_prefix_before_the_v1_api_suffix() -> None:
    assert (
        _ibkr_login_page_url("https://gateway.example.com:5001/proxy/v1/api")
        == "https://gateway.example.com:5001/proxy"
    )


def test_tolerates_a_trailing_slash() -> None:
    assert _ibkr_login_page_url("https://localhost:5000/v1/api/") == "https://localhost:5000"


def test_leaves_the_path_untouched_when_it_does_not_end_with_v1_api() -> None:
    """Defensive fallback: no real `Settings.ibkr_base_url` value takes this path today
    (both its field default and `DEFAULT_BASE_URL` always end with `/v1/api`), but a
    manually-misconfigured value shouldn't be silently mangled -- the origin/path are
    passed through as-is rather than the function raising or guessing."""
    assert _ibkr_login_page_url("https://localhost:5000/some/other/path") == "https://localhost:5000/some/other/path"
