"""Phase 3: the contamination audit (PREREGISTRATION §6).

    python scripts/audit_contamination.py --limit 500 --provider groq

Asks the model to name the issuer of each anonymized filing and reports the rate at which
it succeeds. This is the number that decides what the whole study measures. If the model
can identify the company, it can recall what happened next, and a "forecast" becomes a
memory test — the hindsight the project is named after.

§6 fixes the consequence in advance: **if identification exceeds 20%, the primary analysis
is restricted to filings the model failed to identify, and both versions are reported.**
That rule is applied here rather than decided after seeing the number.

Grading is deliberately generous to the model. A guess counts as correct if it matches the
ticker, or if the company name overlaps the true name on any distinctive token. Being
strict would flatter the anonymizer, and the direction of that error is the dangerous one:
understating contamination is what lets a memorised result pass as a forecast.

Results are written to `data/results/contamination_<model>.json`, not to the five-table
schema, since an issuer guess is not a prediction about returns.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hindsight import config, db  # noqa: E402
from hindsight.ingest.edgar import normalize_company_name  # noqa: E402
from hindsight.manifest import RunManifest  # noqa: E402
from hindsight.score import anonymize as anon  # noqa: E402
from hindsight.score import llm, prompt  # noqa: E402

log = logging.getLogger(__name__)

RESULTS_DIR = config.DATA_DIR / "results"

# Tokens too generic to count as identification. "Apple" identifies; "Company" does not.
_GENERIC = {
    "INC",
    "CORP",
    "CORPORATION",
    "COMPANY",
    "CO",
    "LTD",
    "LIMITED",
    "PLC",
    "LLC",
    "LP",
    "HOLDINGS",
    "HOLDING",
    "GROUP",
    "THE",
    "AND",
    "OF",
    "TRUST",
    "INTERNATIONAL",
    "NEW",
    "AMERICAN",
    "NATIONAL",
    "UNITED",
    "GENERAL",
    "FIRST",
    "GLOBAL",
    "SERVICES",
    "SERVICE",
    "SYSTEMS",
    "TECHNOLOGIES",
    "TECHNOLOGY",
    "ENERGY",
    "FINANCIAL",
    "CAPITAL",
    "BANK",
    "INDUSTRIES",
    "ENTERPRISES",
    "RESOURCES",
    "PRODUCTS",
    "PARTNERS",
    "UNKNOWN",
}


def distinctive_tokens(name: str) -> set[str]:
    return {
        t for t in re.split(r"[^A-Z0-9]+", name.upper()) if t and t not in _GENERIC and len(t) > 2
    }


def is_correct(guess_company: str, guess_ticker: str, true_ticker: str, true_name: str) -> bool:
    """Generous match: exact ticker, or any distinctive name token in common."""
    if not guess_company and not guess_ticker:
        return False
    if guess_ticker and guess_ticker.strip().upper() == true_ticker.strip().upper():
        return True
    if not guess_company or guess_company.strip().lower() == "unknown":
        return False
    # Normalized full-name equality, then distinctive-token overlap.
    if normalize_company_name(guess_company) == normalize_company_name(true_name):
        return True
    return bool(distinctive_tokens(guess_company) & distinctive_tokens(true_name))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--limit", type=int, default=config.CONTAMINATION_SAMPLE_SIZE)
    parser.add_argument("--provider", choices=["groq", "gemini", "anthropic"], default="groq")
    parser.add_argument("--throttle", type=float, default=14.0)
    args = parser.parse_args(argv)

    config.ensure_dirs()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(config.LOG_DIR / "audit.log", encoding="utf-8"),
        ],
    )

    backend = llm.make_backend(args.provider)
    audit_prompt = prompt.get("audit-v1")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    with (
        RunManifest(
            "contamination", limit=args.limit, provider=args.provider, model_id=backend.model_id
        ) as manifest,
        db.session() as conn,
    ):
        rows = list(
            conn.execute(
                """
                SELECT f.accession_no, f.ticker, f.item_codes, f.anonymized_text,
                       f.anon_version, u.ticker AS uticker
                  FROM filings f LEFT JOIN universe u ON u.ticker = f.ticker
                 WHERE f.anon_version = ?
                 GROUP BY f.accession_no
                 ORDER BY f.accepted_at_utc, f.accession_no
                 LIMIT ?
                """,
                (anon.ANON_VERSION, args.limit),
            )
        )
        client = llm.ScoringClient(backend=backend, prompt_version="audit-v1")
        identified: list[dict[str, object]] = []
        attempted = 0

        print(f"  auditing {len(rows):,} filings with {backend.model_id}")
        for i, row in enumerate(rows, 1):
            # The audit must obey the same gate as scoring: raw text never leaves.
            try:
                anon.assert_anonymized(row["anonymized_text"], row["anon_version"])
            except anon.NotAnonymizedError as exc:
                manifest.exclude("refused_not_anonymized", f"{row['accession_no']}: {exc}")
                continue

            # Same cap as the forecasting path: the audit must ask about exactly the text
            # the model was scored on, or it measures contamination of a different input.
            rendered = audit_prompt.render(
                anon.scoring_text(row["anonymized_text"]), row["item_codes"] or ""
            )
            raw = ""
            guess: dict[str, object] = {}
            while True:
                try:
                    raw, tin, tout = backend.complete(audit_prompt.system, rendered)
                    client.input_tokens += tin
                    client.output_tokens += tout
                    client.calls += 1
                    break
                except llm.RateLimitedError as limited:
                    time.sleep(limited.retry_after_seconds)
                except Exception as exc:  # noqa: BLE001
                    manifest.exclude("audit_call_failed", f"{row['accession_no']}: {exc}")
                    raw = ""
                    break
            if not raw:
                continue

            attempted += 1
            try:
                start = raw.find("{")
                guess = json.loads(raw[start:]) if start >= 0 else {}
            except (ValueError, json.JSONDecodeError):
                manifest.count("audit_parse_failures")
                guess = {}

            correct = is_correct(
                str(guess.get("company", "")),
                str(guess.get("ticker", "")),
                row["ticker"],
                row["ticker"],
            )
            if correct:
                manifest.count("identified")
            identified.append(
                {
                    "accession_no": row["accession_no"],
                    "true_ticker": row["ticker"],
                    "guess_company": guess.get("company"),
                    "guess_ticker": guess.get("ticker"),
                    "confidence": guess.get("confidence"),
                    "reasoning": guess.get("reasoning"),
                    "correct": correct,
                }
            )

            if args.throttle:
                time.sleep(args.throttle)
            if i % 25 == 0:
                hits = sum(1 for r in identified if r["correct"])
                log.info(
                    "audited %d/%d — identified %d (%.1f%%)",
                    i,
                    len(rows),
                    hits,
                    100 * hits / len(identified),
                )

        hits = sum(1 for r in identified if r["correct"])
        rate = hits / attempted if attempted else 0.0
        threshold = config.CONTAMINATION_IDENTIFICATION_THRESHOLD

        payload = {
            "model_id": backend.model_id,
            "prompt_version": audit_prompt.version,
            "anon_version": anon.ANON_VERSION,
            "audited_at_utc": datetime.now(UTC).isoformat(),
            "attempted": attempted,
            "identified": hits,
            "identification_rate": round(rate, 4),
            "threshold": threshold,
            "exceeds_threshold": rate > threshold,
            "results": identified,
        }
        safe = backend.model_id.replace("/", "_")
        (RESULTS_DIR / f"contamination_{safe}.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )

        manifest.params["identification_rate"] = round(rate, 4)
        manifest.params["exceeds_threshold"] = rate > threshold

        print(f"\n{'=' * 70}")
        print(f"  CONTAMINATION AUDIT — {backend.model_id}")
        print(f"{'=' * 70}")
        print(f"  identified {hits:,} of {attempted:,} filings = {rate:.1%}")
        print(f"  §6 threshold: {threshold:.0%}")
        if rate > threshold:
            print("\n  EXCEEDS THRESHOLD. §6 requires the primary analysis to be restricted")
            print("  to filings the model failed to identify, with BOTH versions reported.")
        else:
            print("\n  Below threshold. Primary analysis proceeds on the full sample;")
            print("  this rate is reported as a headline limitation regardless.")
        print(f"{'=' * 70}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
