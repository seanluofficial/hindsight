"""Stage 2 entrypoint: anonymize filings, then score them.

    python scripts/run_score.py anonymize --limit 500
    python scripts/run_score.py lexicon   --limit 500
    python scripts/run_score.py llm       --limit 500 --mode historical

Anonymization is a separate, idempotent step that writes `filings.anonymized_text`. Every
scorer reads only that column and refuses text that has not passed the current anonymizer
(invariant 3), so no scoring path can reach raw filing text even by mistake.

Filings are selected in a fixed order — by acceptance timestamp, then accession number —
so `--limit 500` means the same 500 filings on every run (invariant 4).
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hindsight import config, db  # noqa: E402
from hindsight.ingest import edgar  # noqa: E402
from hindsight.ingest.http import CachedFetcher  # noqa: E402
from hindsight.manifest import RunManifest  # noqa: E402
from hindsight.score import anonymize as anon  # noqa: E402
from hindsight.score import lexicon  # noqa: E402

log = logging.getLogger(__name__)

LEXICON_MODEL_ID = f"loughran-mcdonald-{lexicon.LEXICON_VERSION}"


def setup_logging(verbose: bool) -> None:
    config.ensure_dirs()
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(config.LOG_DIR / "score.log", encoding="utf-8"),
        ],
    )


def select_filings(
    conn: sqlite3.Connection, limit: int | None, need_anon: bool
) -> list[sqlite3.Row]:
    """Deterministic filing order, so --limit N is the same N every time."""
    where = "WHERE anonymized_text IS NOT NULL AND anon_version = ?" if need_anon else ""
    params: tuple[object, ...] = (anon.ANON_VERSION,) if need_anon else ()
    sql = f"""
        SELECT accession_no, cik, ticker, accepted_at_utc, item_codes, raw_path,
               anonymized_text, anon_version
          FROM filings {where}
         ORDER BY accepted_at_utc, accession_no
    """
    if limit:
        sql += " LIMIT ?"
        params = (*params, limit)
    return list(conn.execute(sql, params))


# --------------------------------------------------------------------------
def cmd_anonymize(args: argparse.Namespace) -> int:
    with (
        RunManifest("anonymize", limit=args.limit, anon_version=anon.ANON_VERSION) as manifest,
        db.session() as conn,
    ):
        rows = select_filings(conn, args.limit, need_anon=False)
        # Company names come from each filing's cached EDGAR header, which carries both the
        # conformed name and any former names. Reading the cache costs no requests.
        fetcher = CachedFetcher()

        done = 0
        for row in rows:
            if row["anon_version"] == anon.ANON_VERSION and not args.force:
                manifest.count("already_anonymized")
                continue

            path = config.ROOT / row["raw_path"]
            if not path.exists():
                manifest.exclude("extracted_text_missing", row["accession_no"])
                continue
            text = path.read_text(encoding="utf-8")

            try:
                name, formers = edgar.fetch_company_names(row["cik"], row["accession_no"], fetcher)
            except Exception as exc:  # noqa: BLE001
                manifest.exclude("company_names_unavailable", f"{row['accession_no']}: {exc}")
                name, formers = "", []

            result = anon.anonymize(
                text, company_name=name, ticker=row["ticker"], cik=row["cik"], former_names=formers
            )

            if len(result.text) < config.MIN_ANONYMIZED_CHARS:
                # §3: filings whose post-anonymization text is under 200 characters.
                manifest.exclude("anonymized_text_too_short", row["accession_no"])
                continue

            if result.leaks:
                # Recorded, and the text is still stored — but the scorer's gate will
                # reject it, so a leak can never reach the model.
                manifest.exclude("leak_detected", f"{row['accession_no']}: {result.leaks[:3]}")
                for leak in result.leaks:
                    manifest.count(f"leak_kind_{leak.split(':')[0]}")

            conn.execute(
                "UPDATE filings SET anonymized_text = ?, anon_version = ? WHERE accession_no = ?",
                (result.text, result.version, row["accession_no"]),
            )
            done += 1
            manifest.count("anonymized")
            manifest.count("replacements_total", result.total_replacements)
            if done % 250 == 0:
                log.info("anonymized %d filings", done)

        clean = conn.execute(
            "SELECT COUNT(*) FROM filings WHERE anon_version = ?", (anon.ANON_VERSION,)
        ).fetchone()[0]
        print(f"\n  {done:,} anonymized this run; {clean:,} filings now carry {anon.ANON_VERSION}")
        leaked = manifest.exclusions.get("leak_detected", 0)
        rate = 100 * leaked / done if done else 0.0
        print(f"  leak rate: {leaked:,}/{done:,} ({rate:.2f}%)")
        manifest.params["leak_rate_pct"] = round(rate, 3)
    return 0


def cmd_lexicon(args: argparse.Namespace) -> int:
    """Score with the Loughran-McDonald baseline. Deterministic, free, no network."""
    with (
        RunManifest("lexicon", limit=args.limit, model_id=LEXICON_MODEL_ID) as manifest,
        db.session() as conn,
    ):
        rows = select_filings(conn, args.limit, need_anon=True)
        created = datetime.now(UTC).isoformat()

        for row in rows:
            text = row["anonymized_text"]
            try:
                anon.assert_anonymized(text, row["anon_version"])
            except anon.NotAnonymizedError as exc:
                manifest.exclude("refused_not_anonymized", f"{row['accession_no']}: {exc}")
                continue

            result = lexicon.score_text(text)
            probability = lexicon.score_to_probability(result.score)
            conn.execute(
                """
                INSERT OR IGNORE INTO predictions
                    (accession_no, model_id, prompt_version, direction, probability,
                     rationale, raw_response, created_at, run_mode)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'historical')
                """,
                (
                    row["accession_no"],
                    LEXICON_MODEL_ID,
                    lexicon.LEXICON_VERSION,
                    result.direction,
                    round(probability, 4),
                    f"pos={result.positive} neg={result.negative} words={result.total_words}",
                    f"score={result.score:.6f}",
                    created,
                ),
            )
            manifest.count("scored")
            manifest.count(f"direction_{result.direction}")

        total = conn.execute(
            "SELECT COUNT(*) FROM predictions WHERE model_id = ?", (LEXICON_MODEL_ID,)
        ).fetchone()[0]
        print(
            f"\n  {manifest.counts.get('scored', 0):,} scored; {total:,} lexicon predictions stored"
        )
    return 0


def cmd_llm(args: argparse.Namespace) -> int:
    # Imported lazily so `anonymize` and `lexicon` work without the anthropic package
    # installed or an API key present.
    import hindsight.score.llm as llm

    with (
        RunManifest("llm", limit=args.limit, mode=args.mode, model_id=llm.MODEL_ID) as manifest,
        db.session() as conn,
    ):
        rows = select_filings(conn, args.limit, need_anon=True)
        client = llm.ScoringClient()
        print(f"  scoring {len(rows):,} filings with {llm.MODEL_ID} (temperature 0)")
        client.score_filings(conn, rows, manifest, run_mode=args.mode)
        print(f"\n  estimated cost: ${client.estimated_cost_usd:.4f}")
        print(f"  cost per filing: ${client.cost_per_filing:.6f}")
        manifest.params["estimated_cost_usd"] = round(client.estimated_cost_usd, 6)
        manifest.params["cost_per_filing_usd"] = round(client.cost_per_filing, 8)
    return 0


# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_anon = sub.add_parser("anonymize", help="strip identifiers and store anonymized text")
    p_anon.add_argument("--limit", type=int)
    p_anon.add_argument(
        "--force", action="store_true", help="re-anonymize already-processed filings"
    )
    p_anon.set_defaults(func=cmd_anonymize)

    p_lex = sub.add_parser("lexicon", help="score with the Loughran-McDonald baseline")
    p_lex.add_argument("--limit", type=int)
    p_lex.set_defaults(func=cmd_lexicon)

    p_llm = sub.add_parser("llm", help="score with the LLM")
    p_llm.add_argument("--limit", type=int)
    p_llm.add_argument("--mode", choices=["historical", "live"], default="historical")
    p_llm.set_defaults(func=cmd_llm)

    args = parser.parse_args(argv)
    setup_logging(args.verbose)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
