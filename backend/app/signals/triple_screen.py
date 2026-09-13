import pandas as pd


def evaluate_tide(weekly_ohlcv: pd.DataFrame) -> str:
    """Screen 1: 'BULLISH' | 'BEARISH' | 'NEUTRAL'.

    From weekly MACD-Histogram slope + 13/26-week EMA relationship (docs/Analyse.md §2).
    """
    raise NotImplementedError


def evaluate_wave(daily_ohlcv: pd.DataFrame, tide: str) -> dict:
    """Screen 2: oscillator state evaluated against the tide direction (docs/Analyse.md §2)."""
    raise NotImplementedError


def evaluate_trigger(daily_ohlcv: pd.DataFrame, tide: str) -> dict:
    """Screen 3: has price resumed direction (close crossed prior day's high/low) (docs/Analyse.md §2).

    This is a daily-bar EOD approximation of Elder's classic intraday buy-stop/sell-stop
    trigger, per docs/Analyse.md §2 ("For a daily-bar app (no intraday feed required),
    approximate with...") and §10, which recommends end-of-day-only evaluation for the MVP
    given that same approximation -- see this task's `decisions` entry for confirmation this
    is still the intended approach.

    Bullish trigger (tide == "BULLISH") fires when today's close is strictly above
    yesterday's high; bearish trigger (tide == "BEARISH") fires when today's close is
    strictly below yesterday's low. Returns the exact shape docs/architecture/API.md's
    `screens.trigger` documents: ``{"fired": bool, "reference": str}``. `reference` names
    which directional rule applies given the tide ('close_above_prior_high' /
    'close_below_prior_low'), or 'not_applicable' when the tide is NEUTRAL (no directional
    rule applies) or there are fewer than two daily bars to compare (no prior bar to
    reference against at all) -- in both cases `fired` is False rather than forcing a guess.
    """
    if tide == "BULLISH":
        reference = "close_above_prior_high"
    elif tide == "BEARISH":
        reference = "close_below_prior_low"
    else:
        return {"fired": False, "reference": "not_applicable"}

    if len(daily_ohlcv) < 2:
        return {"fired": False, "reference": "not_applicable"}

    today_close = daily_ohlcv["close"].iloc[-1]
    prior_high = daily_ohlcv["high"].iloc[-2]
    prior_low = daily_ohlcv["low"].iloc[-2]

    if tide == "BULLISH":
        fired = today_close > prior_high
    else:
        fired = today_close < prior_low

    return {"fired": fired, "reference": reference}
