"""Portfolio construction, costs and annualization (§9, §10).

The annualization test exists because getting it wrong is invisible: it produces a
plausible-looking Sharpe that is simply too big, and nothing else in the pipeline
disagrees with it.
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from hindsight.evaluate import portfolio
from hindsight.evaluate.returns import Trade


def make_trade(
    excess: float,
    direction: str = "up",
    probability: float = 0.75,
    horizon: int = 5,
    entry: date = date(2018, 1, 3),
    ticker: str = "AAA",
    pid: int = 1,
) -> Trade:
    return Trade(
        prediction_id=pid,
        accession_no=f"acc-{pid}",
        ticker=ticker,
        direction=direction,
        probability=probability,
        horizon=horizon,
        entry_date=entry,
        exit_date=date(2018, 1, 10),
        raw_return=excess,
        benchmark_return=0.0,
        excess_return=excess,
    )


class TestSignedExcess:
    def test_up_call_takes_the_move_as_is(self) -> None:
        assert make_trade(0.03, "up").signed_excess() == pytest.approx(0.03)

    def test_down_call_profits_from_a_fall(self) -> None:
        # Shorting a stock that fell 3% against the market earns +3%.
        assert make_trade(-0.03, "down").signed_excess() == pytest.approx(0.03)

    def test_down_call_loses_on_a_rise(self) -> None:
        assert make_trade(0.03, "down").signed_excess() == pytest.approx(-0.03)


class TestCosts:
    """Invariant 6 and CLAUDE.md: net must be strictly below gross for any nonzero cost."""

    @pytest.mark.parametrize("cost", [1, 10, 25, 100])
    def test_net_is_strictly_below_gross(self, cost: float) -> None:
        trade = make_trade(0.03)
        assert trade.net_return(cost) < trade.signed_excess()

    def test_zero_cost_is_gross(self) -> None:
        trade = make_trade(0.03)
        assert trade.net_return(0) == pytest.approx(trade.signed_excess())

    def test_cost_is_in_basis_points(self) -> None:
        assert make_trade(0.03).net_return(10) == pytest.approx(0.03 - 0.0010)

    def test_cost_argument_is_required(self) -> None:
        # No default equal to zero, per invariant 6.
        with pytest.raises(TypeError):
            make_trade(0.03).net_return()  # type: ignore[call-arg]

    def test_higher_cost_is_monotonically_worse(self) -> None:
        trade = make_trade(0.03)
        assert trade.net_return(0) > trade.net_return(10) > trade.net_return(25)


class TestQuintiles:
    def test_needs_at_least_five(self) -> None:
        top, bottom = portfolio.quintile_split([make_trade(0.01, pid=i) for i in range(4)])
        assert top == [] and bottom == []

    def test_splits_by_signed_score(self) -> None:
        trades = [
            make_trade(0.0, "up", 0.95, pid=1),
            make_trade(0.0, "up", 0.60, pid=2),
            make_trade(0.0, "down", 0.55, pid=3),
            make_trade(0.0, "down", 0.80, pid=4),
            make_trade(0.0, "down", 0.99, pid=5),
        ]
        top, bottom = portfolio.quintile_split(trades)
        assert top[0].prediction_id == 1  # most confident up
        assert bottom[0].prediction_id == 5  # most confident down

    def test_signed_score_direction(self) -> None:
        assert portfolio.signed_score(make_trade(0.0, "up", 0.8)) == pytest.approx(0.8)
        assert portfolio.signed_score(make_trade(0.0, "down", 0.8)) == pytest.approx(-0.8)


class TestMonthlySorting:
    def test_months_are_kept_separate(self) -> None:
        """§9 sorts within each calendar month.

        Pooling months would let a later month's distribution decide an earlier month's
        quintile — lookahead through the back door.
        """
        jan = [make_trade(0.01, entry=date(2018, 1, 5), pid=i) for i in range(10)]
        feb = [make_trade(0.02, entry=date(2018, 2, 5), pid=100 + i) for i in range(10)]
        months = portfolio.monthly_returns(jan + feb, cost_bps=0.0)
        assert set(months) == {"2018-01", "2018-02"}


class TestAnnualization:
    """The series is monthly because §9 rebalances monthly. Annualize by sqrt(12)."""

    @staticmethod
    def _trades_over_months(n_months: int, horizon: int) -> list[Trade]:
        """Months with differing spreads, so the return series has nonzero variance."""
        trades: list[Trade] = []
        pid = 0
        for month in range(1, n_months + 1):
            # Vary the magnitude by month, otherwise every monthly return is identical,
            # stdev is 0, and Sharpe is undefined rather than merely wrong.
            magnitude = 0.005 * (1 + month % 4)
            for k in range(10):
                pid += 1
                trades.append(
                    make_trade(
                        magnitude if k % 2 else -magnitude,
                        direction="up" if k % 2 else "down",
                        probability=0.5 + k / 20,
                        horizon=horizon,
                        entry=date(2018, month, 5),
                        pid=pid,
                    )
                )
        return trades

    def test_sharpe_uses_twelve_not_252_over_horizon(self) -> None:
        import statistics

        result = portfolio.build(self._trades_over_months(6, horizon=1), horizon=1, cost_bps=0.0)
        series = result.period_returns
        assert len(series) == 6
        expected = (statistics.fmean(series) / statistics.stdev(series)) * math.sqrt(
            portfolio.MONTHS_PER_YEAR
        )
        assert result.sharpe_annualized == pytest.approx(expected)

    def test_sqrt_252_scaling_would_be_visibly_larger(self) -> None:
        """Guards the specific regression: sqrt(252/1) vs sqrt(12) is a 4.6x difference."""
        result = portfolio.build(self._trades_over_months(6, horizon=1), horizon=1, cost_bps=0.0)
        wrong = result.sharpe_annualized * math.sqrt(252) / math.sqrt(12)
        assert abs(wrong) > abs(result.sharpe_annualized) * 4

    def test_horizon_does_not_change_the_annualization_factor(self) -> None:
        """The bug: scaling by sqrt(252/horizon) inflated the 1-day Sharpe ~4.6x."""
        one_day = portfolio.build(self._trades_over_months(6, 1), horizon=1, cost_bps=0.0)
        twenty_day = portfolio.build(self._trades_over_months(6, 20), horizon=20, cost_bps=0.0)
        # Identical return series, so identical Sharpe regardless of holding period.
        assert one_day.sharpe_annualized == pytest.approx(twenty_day.sharpe_annualized)


class TestUnderpoweredSamples:
    def test_two_months_is_flagged(self) -> None:
        trades = TestAnnualization._trades_over_months(2, horizon=5)
        result = portfolio.build(trades, horizon=5, cost_bps=10.0)
        assert not result.is_statistically_meaningful
        assert "not interpretable" in result.caveat

    def test_twelve_months_is_acceptable(self) -> None:
        trades = TestAnnualization._trades_over_months(12, horizon=5)
        result = portfolio.build(trades, horizon=5, cost_bps=10.0)
        assert result.is_statistically_meaningful
        assert result.caveat == ""


class TestDrawdown:
    def test_monotonic_gains_have_no_drawdown(self) -> None:
        assert portfolio.max_drawdown([0.01, 0.02, 0.03]) == pytest.approx(0.0)

    def test_drawdown_is_positive_after_a_loss(self) -> None:
        assert portfolio.max_drawdown([0.10, -0.20, 0.05]) > 0

    def test_empty_series(self) -> None:
        assert portfolio.max_drawdown([]) == 0.0

    def test_known_value(self) -> None:
        # 1.0 -> 1.5 -> 0.75: peak 1.5, trough 0.75, drawdown 50%.
        assert portfolio.max_drawdown([0.5, -0.5]) == pytest.approx(0.5)
