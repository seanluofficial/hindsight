"""Stage 3 entrypoint: returns, portfolios, costs, calibration.

    python scripts/run_evaluate.py --model loughran-mcdonald-lm-v1

All three horizons and all three cost levels are printed, always. §5 forbids reporting
only the best horizon and §10 forbids presenting results cost-free alone, so the report
has no flags to hide anything behind.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hindsight import config, db  # noqa: E402
from hindsight.evaluate import calibration, portfolio, returns  # noqa: E402
from hindsight.manifest import RunManifest  # noqa: E402


def setup_logging(verbose: bool) -> None:
    config.ensure_dirs()
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(config.LOG_DIR / "evaluate.log", encoding="utf-8"),
        ],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--model", required=True, help="model_id to evaluate")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    setup_logging(args.verbose)

    with RunManifest("evaluate", model_id=args.model) as manifest, db.session() as conn:
        trades = returns.evaluate_all(conn, args.model, manifest)
        if not trades:
            print("No evaluable predictions. Has scoring run for this model_id?")
            return 1

        written = returns.persist(conn, trades, config.COST_LEVELS_BPS)
        manifest.count("evaluation_rows_written", written)

        print(f"\n{'=' * 74}")
        print(f"  RESULTS — {args.model}")
        print(f"{'=' * 74}")

        n_considered = manifest.counts.get("predictions_considered", 0)
        print(
            f"\n  {n_considered:,} predictions -> {len(trades):,} evaluable trades "
            f"across {len(config.HORIZONS_TRADING_DAYS)} horizons"
        )
        if manifest.exclusions:
            print("  excluded:")
            for reason, count in manifest.exclusions.most_common():
                print(f"    {reason}: {count:,}")

        # ---- §9/§10: quintile long/short at every horizon and cost level ----
        print("\n  Quintile long/short, market-excess, monthly rebalance")
        print(
            f"  {'h':>3} {'cost':>5} {'months':>7} {'trades':>7} {'mean':>9} "
            f"{'t-stat':>7} {'Sharpe':>7} {'maxDD':>7} {'hit':>6}"
        )
        print(f"  {'-' * 68}")
        for horizon in config.HORIZONS_TRADING_DAYS:
            for cost in config.COST_LEVELS_BPS:
                r = portfolio.build(trades, horizon, float(cost))
                base = " <- base" if cost == config.BASE_CASE_COST_BPS else ""
                flag = " [!]" if not r.is_statistically_meaningful else ""
                print(
                    f"  {horizon:>3} {cost:>5} {r.n_periods:>7} {r.n_positions:>7} "
                    f"{r.mean_return:>+9.4f} {r.t_statistic:>+7.2f} "
                    f"{r.sharpe_annualized:>+7.2f} {r.max_drawdown:>7.3f} "
                    f"{r.hit_rate:>6.2f}{base}{flag}"
                )

        sample = portfolio.build(trades, config.HORIZONS_TRADING_DAYS[0], 0.0)
        if not sample.is_statistically_meaningful:
            print(
                f"\n  [!] {sample.caveat}. Monthly rebalancing over this sample gives only\n"
                f"      {sample.n_periods} return observations, so the Sharpe ratios, "
                "t-statistics and drawdowns\n"
                "      above are arithmetic, not evidence. The calibration results below "
                "rest on\n"
                "      per-prediction sample size and are interpretable."
            )
            manifest.params["portfolio_underpowered"] = True

        # ---- §11: calibration ----
        print()
        for horizon in config.HORIZONS_TRADING_DAYS:
            cal = calibration.evaluate(trades, horizon)
            print(f"\n{cal.diagram()}")
            manifest.params[f"brier_h{horizon}"] = round(cal.brier_score, 5)
            manifest.params[f"overconfidence_h{horizon}"] = round(cal.overconfidence, 5)
            print(f"  directional hit rate: {portfolio.directional_hit_rate(trades, horizon):.4f}")

        # ---- §14: does the pre-registered null-result threshold bite? ----
        print(f"\n{'=' * 74}")
        base_case = portfolio.build(trades, 5, float(config.BASE_CASE_COST_BPS))
        threshold = config.NULL_RESULT_SHARPE_THRESHOLD
        if not base_case.is_statistically_meaningful:
            # The §14 test is a decision rule for the full study, not for a pilot. Applying
            # it to two months would let sampling noise decide the headline hypothesis.
            verdict = (
                f"NOT TESTED — {base_case.caveat}. §14 is a decision rule for the full "
                "2010-2024 run;\n           applying it here would let noise settle H1."
            )
        elif base_case.sharpe_annualized < threshold:
            verdict = "H1 NOT SUPPORTED — this is the finding, reported as such (§14)"
        else:
            verdict = f"H1 not rejected at the pre-registered threshold (Sharpe >= {threshold})"
        print(
            f"  §14 test: 5-day Sharpe after {config.BASE_CASE_COST_BPS}bps = "
            f"{base_case.sharpe_annualized:+.3f}  (threshold {threshold})"
        )
        print(f"  {verdict}")
        print(f"{'=' * 74}\n")
        manifest.params["sharpe_5d_base_case"] = round(base_case.sharpe_annualized, 5)
        manifest.params["h1_supported"] = (
            bool(base_case.sharpe_annualized >= threshold)
            if base_case.is_statistically_meaningful
            else None
        )
        manifest.params["portfolio_months"] = base_case.n_periods

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
