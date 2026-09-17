def validate_period(name: str, value: int) -> None:
    """Validate a lookback-period parameter shared across the indicator engine.

    Used by every indicator that takes a window-length parameter (``ema``,
    ``stochastic_oscillator``, ...) to reject the same two classes of bad
    input identically everywhere: a non-``int`` (including ``bool``, which
    Python treats as an ``int`` subclass but which must not be silently
    accepted as ``0``/``1``), and a non-positive ``int``.

    Args:
        name: the parameter's name as the caller knows it (e.g. ``"period"``,
            ``"k_period"``), used verbatim in the raised error message so
            each call site's errors still read as if hand-written for it.
        value: the period value to validate.

    Raises:
        TypeError: if ``value`` is not an ``int`` (e.g. a ``bool`` or a
            ``float`` like ``13.5``).
        ValueError: if ``value`` is not >= 1.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if value < 1:
        raise ValueError(f"{name} must be >= 1")
