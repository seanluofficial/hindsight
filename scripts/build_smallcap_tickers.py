"""Write the ticker list Experiment 009 needs prices for.

Reads the whole-market insider purchases file and emits the distinct tickers that have at
least one *cluster-buy* event (>= 2 insiders within 30 days) — the minimal set of names the
009 event study and materiality book actually price. Prioritising cluster-event tickers keeps
the (paid) price ingest as small as possible.

    uv run python scripts/build_smallcap_tickers.py

Output: data/smallcap_tickers.txt (one ticker per line), plus a count of the full purchase
universe for reference.
"""

from __future__ import annotations

from hindsight import config
from hindsight.experiments import insider

ALL_CSV = config.DATA_DIR / "insider_purchases_all.csv"
OUTPUT = config.DATA_DIR / "smallcap_tickers.txt"


def main() -> None:
    purchases = insider.load_purchases(ALL_CSV)
    all_tickers = sorted({p.ticker for p in purchases})
    events = insider.build_events(purchases)  # >= 2 insiders / 30 days
    cluster_tickers = sorted({ev.ticker for ev in events})

    OUTPUT.write_text("\n".join(cluster_tickers) + "\n", encoding="utf-8")
    print(f"purchases: {len(purchases):,} rows")
    print(f"all purchase tickers: {len(all_tickers):,}")
    print(f"cluster-buy events: {len(events):,}")
    print(f"cluster-buy tickers (need prices): {len(cluster_tickers):,}")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
