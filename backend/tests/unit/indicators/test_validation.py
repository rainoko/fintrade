"""Tests for the shared period-validation helper (app.indicators._validation).

Extracted from the previously-duplicated inline guard in
app.indicators.ema.ema and app.indicators.stochastic.stochastic_oscillator
(see docs/tasks/indicator-stochastic-followups.json) -- exact validation
behavior/error messages are covered end-to-end via each indicator's own
existing tests (test_ema.py, test_stochastic.py); this file exercises the
helper directly, including the parametrized error-message wording that a
call site's own tests can't see in isolation.
"""

import pytest

from app.indicators._validation import validate_period


class TestValidatePeriod:
    def test_accepts_positive_int(self) -> None:
        validate_period("period", 1)
        validate_period("k_period", 13)

    def test_rejects_zero_or_negative(self) -> None:
        with pytest.raises(ValueError, match="period must be >= 1"):
            validate_period("period", 0)
        with pytest.raises(ValueError, match="k_period must be >= 1"):
            validate_period("k_period", -5)

    def test_rejects_non_int(self) -> None:
        with pytest.raises(
            TypeError, match=r"period must be an int, got float"
        ):
            validate_period("period", 13.5)

    def test_rejects_bool(self) -> None:
        """bool is a subclass of int in Python; True/False must not be
        silently accepted as 1/0."""
        with pytest.raises(TypeError, match=r"smooth must be an int, got bool"):
            validate_period("smooth", True)

    def test_error_message_uses_caller_supplied_name(self) -> None:
        """Each call site's own parameter name must appear verbatim in the
        error, so a caller can't tell the guard was extracted from a
        shared helper."""
        with pytest.raises(TypeError, match=r"^d_period must be an int"):
            validate_period("d_period", None)
