"""Brier score and reliability bins (PREREGISTRATION §11).

H2 predicts the model is overconfident — that when it says 70% it is right less often than
70%, with the gap widening as confidence rises. Confirming that is a valid result, so this
module has to be able to embarrass the model.

The event scored is "the signed excess return was positive", i.e. the direction call was
right. Probability is the stated confidence in that call, which §7 bounds to [0.50, 1.00].

That bound matters for reading the Brier score. A model that always says 0.50 scores 0.25;
one that is always right and always says 1.00 scores 0.0. Because the floor is 0.50 rather
than 0.0, the naive baseline is 0.25, not 0.5 — comparisons should be against that.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from hindsight.evaluate.returns import Trade


@dataclass(frozen=True)
class ReliabilityBin:
    """One bucket of the reliability diagram."""

    lower: float
    upper: float
    count: int
    mean_predicted: float
    observed_frequency: float

    @property
    def gap(self) -> float:
        """Predicted minus observed. Positive means overconfident — H2's prediction."""
        return self.mean_predicted - self.observed_frequency

    @property
    def label(self) -> str:
        return f"{self.lower:.2f}-{self.upper:.2f}"


@dataclass(frozen=True)
class CalibrationResult:
    horizon: int
    n: int
    brier_score: float
    mean_predicted: float
    observed_frequency: float
    bins: list[ReliabilityBin]

    @property
    def overconfidence(self) -> float:
        """Mean predicted confidence minus realised hit rate, over all predictions."""
        return self.mean_predicted - self.observed_frequency

    def diagram(self, width: int = 40) -> str:
        """Text reliability diagram — perfect calibration is the diagonal.

        A text version exists so a result is visible from a terminal without a plotting
        stack, and so it can be pasted into a write-up unchanged.
        """
        lines = [
            f"Reliability, horizon {self.horizon}d  (n={self.n:,}, Brier={self.brier_score:.4f})",
            f"  {'bin':<12}{'n':>6}  {'pred':>6} {'obs':>6}  {'gap':>7}",
        ]
        for b in self.bins:
            if b.count == 0:
                continue
            marker = int(round(b.observed_frequency * width))
            bar = "." * marker + "#" + "." * max(0, width - marker)
            lines.append(
                f"  {b.label:<12}{b.count:>6}  {b.mean_predicted:>6.3f} "
                f"{b.observed_frequency:>6.3f}  {b.gap:>+7.3f}  {bar}"
            )
        verdict = "overconfident" if self.overconfidence > 0 else "underconfident"
        lines.append(
            f"  overall: predicted {self.mean_predicted:.3f} vs observed "
            f"{self.observed_frequency:.3f} -> {verdict} by {abs(self.overconfidence):.3f}"
        )
        return "\n".join(lines)


def was_correct(trade: Trade) -> bool:
    """The directional call paid off in market-excess terms."""
    return trade.signed_excess() > 0


def brier_score(trades: list[Trade]) -> float:
    """Mean squared error between stated confidence and the 0/1 outcome. Lower is better."""
    if not trades:
        return float("nan")
    return statistics.fmean((t.probability - (1.0 if was_correct(t) else 0.0)) ** 2 for t in trades)


def reliability_bins(trades: list[Trade], n_bins: int = 10) -> list[ReliabilityBin]:
    """Bucket predictions by stated confidence (§11 specifies 10 bins).

    Bins span the full [0, 1] so the diagram is readable on a standard axis, even though
    §7 confines predictions to the upper half.
    """
    edges = [i / n_bins for i in range(n_bins + 1)]
    out: list[ReliabilityBin] = []
    for lower, upper in zip(edges[:-1], edges[1:], strict=True):
        # Last bin is closed so a prediction of exactly 1.00 is counted.
        in_bin = [
            t
            for t in trades
            if lower <= t.probability < upper or (upper == 1.0 and t.probability == 1.0)
        ]
        out.append(
            ReliabilityBin(
                lower=lower,
                upper=upper,
                count=len(in_bin),
                mean_predicted=statistics.fmean(t.probability for t in in_bin) if in_bin else 0.0,
                observed_frequency=(
                    statistics.fmean(1.0 if was_correct(t) else 0.0 for t in in_bin)
                    if in_bin
                    else 0.0
                ),
            )
        )
    return out


def evaluate(trades: list[Trade], horizon: int, n_bins: int = 10) -> CalibrationResult:
    at_horizon = [t for t in trades if t.horizon == horizon]
    if not at_horizon:
        return CalibrationResult(horizon, 0, float("nan"), 0.0, 0.0, [])
    return CalibrationResult(
        horizon=horizon,
        n=len(at_horizon),
        brier_score=brier_score(at_horizon),
        mean_predicted=statistics.fmean(t.probability for t in at_horizon),
        observed_frequency=statistics.fmean(1.0 if was_correct(t) else 0.0 for t in at_horizon),
        bins=reliability_bins(at_horizon, n_bins),
    )
