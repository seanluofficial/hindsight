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
import csv
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

SAMPLE_PATH = config.DATA_DIR / "study_sample.csv"


def load_sample_accessions(path: Path) -> set[str]:
    """Accession numbers of the frozen study sample (D16).

    The study is defined to run on this stratified sample, not on whichever filings happen
    to be anonymized first. Scoring reads the frozen CSV so the scored population is exactly
    the one drawn under a fixed seed — reproducible and immune to redrawing after seeing
    results (invariant 4).
    """
    if not path.exists():
        raise SystemExit(
            f"{path} does not exist. Draw the frozen sample first:\n"
            "    python scripts/draw_sample.py --size 5000"
        )
    with path.open(newline="", encoding="utf-8") as fh:
        accessions = {row["accession_no"] for row in csv.DictReader(fh)}
    if not accessions:
        raise SystemExit(f"{path} is empty; nothing to score.")
    return accessions


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
    conn: sqlite3.Connection,
    limit: int | None,
    need_anon: bool,
    restrict_to: set[str] | None = None,
) -> list[sqlite3.Row]:
    """Deterministic filing order, so --limit N is the same N every time.

    When `restrict_to` is given, only those accession numbers are returned — this is how the
    frozen study sample is enforced on the scored population (D16). Ordering is by acceptance
    timestamp then accession number regardless, so the result is reproducible.
    """
    conditions: list[str] = []
    params: list[object] = []
    if need_anon:
        conditions.append("anonymized_text IS NOT NULL AND anon_version = ?")
        params.append(anon.ANON_VERSION)
    if restrict_to is not None:
        placeholders = ",".join("?" * len(restrict_to))
        conditions.append(f"accession_no IN ({placeholders})")
        params.extend(sorted(restrict_to))
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"""
        SELECT accession_no, cik, ticker, accepted_at_utc, item_codes, raw_path,
               anonymized_text, anon_version
          FROM filings {where}
         ORDER BY accepted_at_utc, accession_no
    """
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return list(conn.execute(sql, params))


def already_scored(
    conn: sqlite3.Connection, model_id: str, prompt_version: str, run_mode: str
) -> set[str]:
    """Accession numbers that already carry a prediction for this exact configuration.

    Used to resume a long paid run without re-charging for work already committed. A row
    exists whether the prior attempt parsed or was recorded as a null (§7), so a null is not
    retried — acceptable because parse failures are near-zero and rerunning is about cost, not
    salvage.
    """
    rows = conn.execute(
        """
        SELECT accession_no FROM predictions
         WHERE model_id = ? AND prompt_version = ? AND run_mode = ?
        """,
        (model_id, prompt_version, run_mode),
    )
    return {r[0] for r in rows}


# --------------------------------------------------------------------------
def resolve_sample(args: argparse.Namespace) -> set[str] | None:
    """The frozen sample's accession numbers when --sample is passed, else None."""
    if not getattr(args, "sample", False):
        return None
    return load_sample_accessions(SAMPLE_PATH)


def cmd_anonymize(args: argparse.Namespace) -> int:
    sample = resolve_sample(args)
    with (
        RunManifest(
            "anonymize", limit=args.limit, anon_version=anon.ANON_VERSION, sample=bool(sample)
        ) as manifest,
        db.session() as conn,
    ):
        rows = select_filings(conn, args.limit, need_anon=False, restrict_to=sample)
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
    sample = resolve_sample(args)
    with (
        RunManifest(
            "lexicon", limit=args.limit, model_id=LEXICON_MODEL_ID, sample=bool(sample)
        ) as manifest,
        db.session() as conn,
    ):
        rows = select_filings(conn, args.limit, need_anon=True, restrict_to=sample)
        created = datetime.now(UTC).isoformat()

        for row in rows:
            text = row["anonymized_text"]
            try:
                anon.assert_anonymized(text, row["anon_version"])
            except anon.NotAnonymizedError as exc:
                manifest.exclude("refused_not_anonymized", f"{row['accession_no']}: {exc}")
                continue

            # Identical capping to the LLM path, so §8's "identical anonymized text"
            # holds and H3 compares readers rather than inputs.
            result = lexicon.score_text(anon.scoring_text(text))
            probability = lexicon.score_to_probability(result.score)
            if anon.was_truncated(text):
                manifest.count("truncated_to_cap")
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
    # Imported lazily so `anonymize` and `lexicon` work without any provider SDK or key.
    import hindsight.score.llm as llm

    backend = llm.make_backend(args.provider)
    if args.model:
        backend.model_id = args.model
    sample = resolve_sample(args)
    with (
        RunManifest(
            "llm",
            limit=args.limit,
            mode=args.mode,
            provider=args.provider,
            model_id=backend.model_id,
            sample=bool(sample),
        ) as manifest,
        db.session() as conn,
    ):
        rows = select_filings(conn, args.limit, need_anon=True, restrict_to=sample)
        client = llm.ScoringClient(backend=backend, budget_usd=args.budget)

        # Resume cost-safely (Phase 5): skip filings already scored under this exact
        # model + prompt + run_mode, so a crash at filing 4,000 never re-charges the API for
        # the first 3,999 on the next run. Uniqueness is enforced in the schema too, but the
        # INSERT there fires only *after* the paid call — this skips the call itself.
        done = already_scored(conn, client.model_id, client.prompt.version, args.mode)
        before = len(rows)
        rows = [r for r in rows if r["accession_no"] not in done]
        if before - len(rows):
            print(f"  resuming: {before - len(rows):,} already scored, {len(rows):,} remaining")
        manifest.count("already_scored_skipped", before - len(rows))

        if args.budget:
            print(f"  spend ceiling: ${args.budget:.2f} (run halts cleanly at the limit)")
        print(f"  scoring {len(rows):,} filings with {backend.model_id} (temperature 0)")
        client.score_filings(
            conn, rows, manifest, run_mode=args.mode, throttle_seconds=args.throttle
        )
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

    sample_help = "restrict to the frozen study sample (data/study_sample.csv), per D16"

    p_anon = sub.add_parser("anonymize", help="strip identifiers and store anonymized text")
    p_anon.add_argument("--limit", type=int)
    p_anon.add_argument("--sample", action="store_true", help=sample_help)
    p_anon.add_argument(
        "--force", action="store_true", help="re-anonymize already-processed filings"
    )
    p_anon.set_defaults(func=cmd_anonymize)

    p_lex = sub.add_parser("lexicon", help="score with the Loughran-McDonald baseline")
    p_lex.add_argument("--limit", type=int)
    p_lex.add_argument("--sample", action="store_true", help=sample_help)
    p_lex.set_defaults(func=cmd_lexicon)

    p_llm = sub.add_parser("llm", help="score with the LLM")
    p_llm.add_argument("--limit", type=int)
    p_llm.add_argument("--sample", action="store_true", help=sample_help)
    p_llm.add_argument("--mode", choices=["historical", "live"], default="historical")
    p_llm.add_argument(
        "--provider", choices=["groq", "deepseek", "gemini", "anthropic"], default="groq"
    )
    p_llm.add_argument("--model", help="override the provider's default model")
    p_llm.add_argument(
        "--budget",
        type=float,
        help="halt cleanly once estimated spend reaches this many USD",
    )
    p_llm.add_argument(
        "--throttle",
        type=float,
        default=1.0,
        help="seconds between calls; paces free-tier per-minute limits",
    )
    p_llm.set_defaults(func=cmd_llm)

    args = parser.parse_args(argv)
    setup_logging(args.verbose)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
