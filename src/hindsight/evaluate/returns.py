"""Entry timing and market-excess returns (PREREGISTRATION §4, §5).

Every number downstream rests on this module, and every classic backtest bug lives here:

* **Lookahead.** Entry is `trading_calendar.entry_date_for()`, derived only from the
  acceptance timestamp. Nothing consults a price before it existed.
* **Split contamination.** Raw OHLC and `adj_close` must never be mixed — a 2-for-1 split
  between entry and exit reads as −50%. Both legs use the same-day adjustment factor.
* **Silent dropping.** A missing price is an exclusion with a reason, never a zero return.
  A zero would quietly shrink the measured effect toward nothing.

Returns are market-excess: the filing's return minus SPY's over the *identical* window,
which is what §5 requires. Using a fixed calendar window instead would leak market drift
into the estimate.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from hindsight import config, trading_calendar
from hindsight.manifest import RunManifest


@dataclass(frozen=True)
class PriceBar:
    """One session, with adjusted prices derived once."""

    day: date
    open: float
    close: float
    adj_close: float

    @property
    def factor(self) -> float:
        """Split/dividend factor. 1.0 when it cannot be computed."""
        if not self.close:
            return 1.0
        return self.adj_close / self.close

    @property
    def adj_open(self) -> float:
        return self.open * self.factor


@dataclass(frozen=True)
class Trade:
    """One evaluated position."""

    prediction_id: int
    accession_no: str
    ticker: str
    direction: str
    probability: float
    horizon: int
    entry_date: date
    exit_date: date
    raw_return: float
    benchmark_return: float
    excess_return: float

    def signed_excess(self) -> float:
        """Excess return in the direction predicted.

        A correct 'down' call earns the negative of a negative move, so shorting a stock
        that fell 3% against the market returns +3%.
        """
        return self.excess_return if self.direction == "up" else -self.excess_return

    def net_return(self, cost_bps: float) -> float:
        """Signed excess after round-trip costs (§10).

        `cost_bps` has no default. Invariant 6: a performance number must state what it
        cost to capture, so the caller is forced to say.
        """
        return self.signed_excess() - cost_bps / 10_000.0


class PriceLookup:
    """In-memory price table. Loading once beats ~10k round trips per horizon."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._bars: dict[str, dict[date, PriceBar]] = {}
        for row in conn.execute(
            "SELECT ticker, date, open, close, adj_close FROM prices "
            "WHERE open IS NOT NULL AND close IS NOT NULL"
        ):
            day = date.fromisoformat(row["date"])
            self._bars.setdefault(row["ticker"], {})[day] = PriceBar(
                day=day,
                open=float(row["open"]),
                close=float(row["close"]),
                adj_close=float(row["adj_close"] if row["adj_close"] is not None else row["close"]),
            )

    def bar(self, ticker: str, day: date) -> PriceBar | None:
        return self._bars.get(ticker, {}).get(day)

    def has_ticker(self, ticker: str) -> bool:
        return ticker in self._bars

    def prior_close(self, ticker: str, day: date) -> float | None:
        """Close on the session before `day` — the §3 penny-stock screen."""
        try:
            previous = trading_calendar.previous_trading_day(day)
        except ValueError:
            return None
        bar = self.bar(ticker, previous)
        return bar.close if bar else None


def window_return(prices: PriceLookup, ticker: str, entry: date, exit_day: date) -> float | None:
    """Adjusted open-to-close return. None if either leg is missing.

    Both legs are adjusted with their own day's factor, so a split inside the window
    cancels instead of masquerading as a return.
    """
    entry_bar = prices.bar(ticker, entry)
    exit_bar = prices.bar(ticker, exit_day)
    if entry_bar is None or exit_bar is None:
        return None
    entry_price = entry_bar.adj_open
    if entry_price <= 0:
        return None
    return exit_bar.adj_close / entry_price - 1.0


def evaluate_prediction(
    row: sqlite3.Row,
    horizon: int,
    prices: PriceLookup,
    manifest: RunManifest | None = None,
) -> Trade | None:
    """One prediction at one horizon, or None with a recorded reason."""

    def drop(reason: str) -> None:
        if manifest:
            manifest.exclude(reason, f"{row['accession_no']}:h{horizon}")

    if row["direction"] is None or row["probability"] is None:
        drop("prediction_is_null")
        return None

    ticker = row["ticker"]
    accepted = datetime.fromisoformat(row["accepted_at_utc"])
    entry = trading_calendar.entry_date_for(accepted)

    try:
        exit_day = trading_calendar.add_trading_days(entry, horizon)
    except ValueError:
        drop("exit_beyond_calendar")
        return None

    if not prices.has_ticker(ticker):
        drop("no_price_coverage_for_ticker")
        return None

    # §3: exclude if the prior close was under $5.
    prior = prices.prior_close(ticker, entry)
    if prior is None:
        drop("no_prior_close")
        return None
    if prior < config.MIN_PRIOR_CLOSE_USD:
        drop("prior_close_below_5_usd")
        return None

    # §3: days where the security did not trade.
    if prices.bar(ticker, entry) is None:
        drop("security_did_not_trade_on_entry")
        return None

    raw = window_return(prices, ticker, entry, exit_day)
    if raw is None:
        drop("missing_price_in_window")
        return None

    benchmark = window_return(prices, config.BENCHMARK_TICKER, entry, exit_day)
    if benchmark is None:
        drop("missing_benchmark_in_window")
        return None

    return Trade(
        prediction_id=int(row["id"]),
        accession_no=row["accession_no"],
        ticker=ticker,
        direction=row["direction"],
        probability=float(row["probability"]),
        horizon=horizon,
        entry_date=entry,
        exit_date=exit_day,
        raw_return=raw,
        benchmark_return=benchmark,
        excess_return=raw - benchmark,
    )


def evaluate_all(
    conn: sqlite3.Connection,
    model_id: str,
    manifest: RunManifest,
    horizons: tuple[int, ...] = config.HORIZONS_TRADING_DAYS,
) -> list[Trade]:
    """Every prediction for `model_id`, at every horizon. All horizons are reported (§5)."""
    rows = list(
        conn.execute(
            """
            SELECT p.id, p.accession_no, p.direction, p.probability,
                   f.ticker, f.accepted_at_utc, f.item_codes
              FROM predictions p
              JOIN filings f ON f.accession_no = p.accession_no
             WHERE p.model_id = ?
             ORDER BY f.accepted_at_utc, p.accession_no
            """,
            (model_id,),
        )
    )
    prices = PriceLookup(conn)
    trades: list[Trade] = []
    for horizon in horizons:
        for row in rows:
            trade = evaluate_prediction(row, horizon, prices, manifest)
            if trade is not None:
                trades.append(trade)
                manifest.count(f"trades_h{horizon}")
    manifest.count("predictions_considered", len(rows))
    return trades


def persist(conn: sqlite3.Connection, trades: list[Trade], cost_levels: tuple[int, ...]) -> int:
    """Write one evaluations row per (trade, cost level). Idempotent."""
    payload = [
        (
            t.prediction_id,
            t.horizon,
            t.entry_date.isoformat(),
            t.exit_date.isoformat(),
            t.raw_return,
            t.excess_return,
            float(cost),
            t.net_return(cost),
        )
        for t in trades
        for cost in cost_levels
    ]
    conn.executemany(
        """
        INSERT OR REPLACE INTO evaluations
            (prediction_id, horizon, entry_date, exit_date, raw_return,
             excess_return, cost_bps, net_return)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        payload,
    )
    return len(payload)
