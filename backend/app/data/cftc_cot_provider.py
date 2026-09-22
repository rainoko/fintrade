"""CFTC Commitments of Traders (COT) report data -- Elder ch. 37's one "genuinely new,
freely available" data source (docs/ideas.md's ch. 37 entry): the CFTC publishes weekly
long/short futures positioning broken down by commercials / large speculators / small
speculators, for every futures market, publicly and for free. Elder's own framing: follow
commercials (the historically successful group), fade small speculators (the historically
unsuccessful group), and read current positioning against historical norms rather than an
absolute level.

Research finding (see this task's `decisions` entry on docs/tasks/backend-cftc-cot-data.json
for the full writeup): the CFTC's "Legacy" Commitments of Traders report -- "Futures Only",
the classic Commercial / Non-Commercial / Non-Reportable three-way breakdown Elder describes
(the newer "Disaggregated"/"Traders in Financial Futures" reports split those same groups
further -- e.g. producer/merchant vs. swap dealer -- detail this app has no use for) -- is
published as a public Socrata Open Data (SODA) JSON API, confirmed live at
``https://publicreporting.cftc.gov/resource/6dca-aqww.json``. No API key/app token is
required for this app's low request volume (Socrata offers an optional app token purely for
higher rate limits). Confirmed fields: ``market_and_exchange_names`` /
``cftc_contract_market_code`` identify one specific futures contract,
``report_date_as_yyyy_mm_dd`` is the report's as-of Tuesday, and
``noncomm_positions_long_all`` / ``noncomm_positions_short_all`` (large speculators),
``comm_positions_long_all`` / ``comm_positions_short_all`` (commercials), and
``nonrept_positions_long_all`` / ``nonrept_positions_short_all`` (small speculators) are
exactly Elder's three-way breakdown, alongside ``open_interest_all``. New reports are
released weekly (Fridays, covering the prior Tuesday's positions).

Scoped to a small, fixed set of major futures markets -- matching the ch. 57 daily-homework
idea's own list (Euro, Yen, Oil, Gold, Bonds), per this task's `description` -- rather than
every futures market the CFTC tracks.
"""

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime

from app.data.exceptions import DataProviderUnavailableError

_BASE_URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"

# Fixed, small set of major futures markets (docs/ideas.md's ch. 57 daily-homework list:
# Euro, Yen, Oil, Gold, Bonds), keyed by a stable short label the API/frontend use, mapped to
# the specific CFTC `cftc_contract_market_code` Elder's list intends. Each code was confirmed
# live against the Socrata endpoint above (most recent `report_date_as_yyyy_mm_dd` returned
# for it) rather than assumed from the contract name alone -- several of these commodities
# have multiple CFTC-tracked contracts across different exchanges (e.g. NYMEX WTI vs. ICE
# Brent for oil), and this app deliberately picks the single most commonly-referenced US
# contract for each rather than surfacing all of them -- see this task's `decisions` entry.
COT_MARKETS: dict[str, str] = {
    "eur": "099741",  # EURO FX - CHICAGO MERCANTILE EXCHANGE
    "jpy": "097741",  # JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE
    "oil": "067651",  # CRUDE OIL, LIGHT SWEET (WTI) - NEW YORK MERCANTILE EXCHANGE
    "gold": "088691",  # GOLD - COMMODITY EXCHANGE INC.
    "bonds": "020601",  # U.S. TREASURY BONDS - CHICAGO BOARD OF TRADE
}

# ~1 trading year of weekly reports -- enough to judge Elder's "against historical norms"
# framing (see `cot_index` below) without unbounded history growth on every request. See
# this task's `decisions` entry.
WEEKS_OF_HISTORY = 52


@dataclass(frozen=True)
class COTWeeklyReport:
    """One futures market's positioning for one weekly CFTC report date."""

    report_date: date
    market_and_exchange_name: str
    open_interest: int
    commercial_long: int
    commercial_short: int
    large_speculator_long: int
    large_speculator_short: int
    small_speculator_long: int
    small_speculator_short: int

    @property
    def commercial_net(self) -> int:
        """Positive = commercials net long. Elder's "follow commercials" group."""
        return self.commercial_long - self.commercial_short

    @property
    def large_speculator_net(self) -> int:
        """CFTC's "Non-Commercial" category -- Elder's large speculators."""
        return self.large_speculator_long - self.large_speculator_short

    @property
    def small_speculator_net(self) -> int:
        """CFTC's "Non-Reportable" category -- Elder's small speculators, the group he
        says to fade rather than follow."""
        return self.small_speculator_long - self.small_speculator_short


class CFTCCOTProvider:
    """Fetches CFTC Commitments of Traders positioning for `COT_MARKETS`' fixed futures
    list. Stateless (a fresh instance is cheap to construct per request, matching
    `StooqProvider`/`YFinanceProvider`'s own pattern) -- unlike `IBKRProvider`, there's no
    per-instance rate-limit/cache state that would make a shared singleton necessary.
    """

    def get_recent_reports(self, market_key: str, weeks: int = WEEKS_OF_HISTORY) -> list[COTWeeklyReport]:
        """Up to `weeks` most recent weekly reports for `market_key` (a `COT_MARKETS`
        key), most recent first.

        Raises:
            KeyError: `market_key` isn't one of `COT_MARKETS`.
            DataProviderUnavailableError: the CFTC request itself failed (network error,
                unexpected/malformed response).
        """
        code = COT_MARKETS[market_key]
        rows = self._fetch_rows_for_codes([code], weeks)
        return [self._to_report(row) for row in rows]

    def get_all_recent(self, weeks: int = WEEKS_OF_HISTORY) -> dict[str, list[COTWeeklyReport]]:
        """`get_recent_reports` for every `COT_MARKETS` key, in a single HTTP request (one
        compound ``cftc_contract_market_code IN (...)`` filter) rather than one request per
        market -- see this task's `decisions` entry. Returns most-recent-first per key,
        same as `get_recent_reports`.

        Raises:
            DataProviderUnavailableError: the CFTC request itself failed, or came back
                missing rows entirely for one of `COT_MARKETS`' fixed codes (treated as a
                malformed/incomplete response, not a per-market "no data" case -- these
                are all long-established, actively-traded contracts that always have
                current data, unlike an arbitrary user-supplied ticker).
        """
        codes = list(COT_MARKETS.values())
        rows = self._fetch_rows_for_codes(codes, weeks)

        reports_by_code: dict[str, list[dict]] = {code: [] for code in codes}
        for row in rows:
            try:
                row_code = row["cftc_contract_market_code"]
            except (KeyError, TypeError) as exc:
                raise DataProviderUnavailableError(
                    f"CFTC COT row missing 'cftc_contract_market_code': {exc}"
                ) from exc
            reports_by_code.setdefault(row_code, []).append(row)

        result: dict[str, list[COTWeeklyReport]] = {}
        for market_key, code in COT_MARKETS.items():
            code_rows = reports_by_code.get(code, [])
            if not code_rows:
                raise DataProviderUnavailableError(
                    f"CFTC COT response had no rows for {market_key!r} (contract code {code!r})"
                )
            result[market_key] = [self._to_report(row) for row in code_rows]
        return result

    def _fetch_rows_for_codes(self, codes: list[str], weeks: int) -> list[dict]:
        where_codes = ",".join(f"'{code}'" for code in codes)
        params = {
            "$where": f"cftc_contract_market_code in({where_codes})",
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$limit": str(weeks * len(codes)),
        }
        url = f"{_BASE_URL}?{urllib.parse.urlencode(params)}"
        return self._request(url)

    def _request(self, url: str) -> list[dict]:
        """Perform the actual HTTP GET against CFTC's Socrata endpoint and parse its JSON
        body. Isolated in its own method so tests can mock this one boundary (matches
        `IBKRProvider._request`'s pattern) rather than urllib internals.
        """
        try:
            with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 - fixed https host, not user input
                body = response.read().decode("utf-8")
        except Exception as exc:  # noqa: BLE001 - any transport failure is a provider-availability problem
            raise DataProviderUnavailableError(f"CFTC COT request failed: {exc}") from exc

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise DataProviderUnavailableError(f"CFTC COT returned an unparseable response: {exc}") from exc

        if not isinstance(parsed, list):
            raise DataProviderUnavailableError(
                f"CFTC COT returned an unexpected response shape: {type(parsed).__name__}"
            )
        return parsed

    @staticmethod
    def _to_report(row: dict) -> COTWeeklyReport:
        try:
            return COTWeeklyReport(
                report_date=datetime.fromisoformat(row["report_date_as_yyyy_mm_dd"]).date(),
                market_and_exchange_name=row["market_and_exchange_names"],
                open_interest=int(row["open_interest_all"]),
                commercial_long=int(row["comm_positions_long_all"]),
                commercial_short=int(row["comm_positions_short_all"]),
                large_speculator_long=int(row["noncomm_positions_long_all"]),
                large_speculator_short=int(row["noncomm_positions_short_all"]),
                small_speculator_long=int(row["nonrept_positions_long_all"]),
                small_speculator_short=int(row["nonrept_positions_short_all"]),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise DataProviderUnavailableError(f"CFTC COT returned a malformed row: {exc}") from exc


def cot_index(current_net: int, history_net: list[int]) -> float | None:
    """The classic Williams "COT Index": where `current_net` sits within
    `history_net`'s own high/low range, scaled 0-100 (0 = at or below the lowest net
    position seen in the window, 100 = at or above the highest) -- the standard way to
    operationalize Elder's "read current positioning against historical norms" framing
    (raw net-position counts alone aren't comparable across time as overall open interest
    grows/shrinks). See this task's `decisions` entry for why this well-known formula was
    used rather than a bespoke percentile-rank scheme.

    `history_net` must include `current_net` itself (the caller's own most recent week) --
    matches this indicator's standard definition, where the current reading is always part
    of its own reference window.

    Returns `None` if `history_net` has fewer than 2 points (no meaningful range yet) or
    every value in it is identical (a zero-width range -- undefined, not 50/neutral, since
    that would silently imply a real reading where there's actually no information).
    """
    if len(history_net) < 2:
        return None
    lowest = min(history_net)
    highest = max(history_net)
    if highest == lowest:
        return None
    return (current_net - lowest) / (highest - lowest) * 100
