"""Run the trend/absolute-momentum ETF allocation and write its result bundle.

    uv run python scripts/run_allocate.py
"""

from __future__ import annotations

import json

from hindsight import config, db
from hindsight.allocate import trend

RESULTS_DIR = config.DATA_DIR / "results"


def main() -> None:
    with db.session() as conn:
        bundle = trend.run(conn)
    bundle["strategy"] = "Diversified absolute-momentum (trend) on 6 liquid ETFs, monthly"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / "allocation.json"
    out.write_text(json.dumps(bundle, indent=2), encoding="utf-8")

    header = f"{'strategy':22} {'window':20} {'mo':>4} {'CAGR':>7} {'vol':>7} {'Sharpe':>7}"
    print(f"{header} {'maxDD':>7}")
    for r in bundle["results"]:
        print(
            f"{r['label']:22} {r['partition']:20} {r['n_months']:4d} "
            f"{r['cagr'] * 100:6.1f}% {r['vol_annual'] * 100:6.1f}% "
            f"{r['sharpe']:7.2f} {r['max_drawdown'] * 100:6.1f}%"
        )
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
