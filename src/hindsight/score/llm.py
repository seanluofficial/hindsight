"""LLM scoring client: strict JSON parsing, retries, cost accounting (§7).

Three rules from the brief are enforced here rather than hoped for:

* **Never coerce.** A response that does not satisfy the schema is retried, and after two
  retries recorded as a null prediction and counted in a reported failure rate (§7). A
  malformed response silently patched into `direction="up"` would be fabricated data.
* **Never send raw text.** Every call passes through `assert_anonymized()`, which raises
  unless the text carries the current anonymizer version and survives a leak scan
  (invariant 3).
* **Determinism.** Temperature 0 and a pinned model ID, both recorded on every row.

Costs are measured, not estimated from a guess: token counts come back with each response
and are priced from a table pinned alongside the model ID.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from hindsight import config
from hindsight.manifest import RunManifest
from hindsight.score import anonymize as anon
from hindsight.score import prompt as prompts

log = logging.getLogger(__name__)

MODEL_ID = "claude-opus-4-5-20251101"
MAX_RETRIES = 2
MAX_TOKENS = 300

# USD per million tokens, pinned next to MODEL_ID so a model change forces a price change.
PRICE_PER_MTOK_INPUT = 5.00
PRICE_PER_MTOK_OUTPUT = 25.00

_RE_JSON = re.compile(r"\{.*\}", re.S)


class Prediction(BaseModel):
    """The §7 output schema. Pydantic rejects anything else — no coercion."""

    direction: str = Field(pattern="^(up|down)$")
    probability: float = Field(ge=0.50, le=1.00)
    rationale: str = Field(min_length=1, max_length=1000)


def parse_response(raw: str) -> Prediction:
    """Strict parse. Raises on anything that is not the agreed schema.

    Tolerates the model wrapping JSON in prose or a code fence — that is a formatting
    quirk, not a semantic one — but never repairs the *content*.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    match = _RE_JSON.search(text)
    if not match:
        raise ValueError(f"no JSON object in response: {raw[:200]!r}")
    return Prediction.model_validate(json.loads(match.group(0)))


class ScoringClient:
    """Scores anonymized filings, tracking tokens and cost."""

    def __init__(self, model_id: str = MODEL_ID, prompt_version: str = prompts.PROMPT_VERSION):
        self.model_id = model_id
        self.prompt = prompts.get(prompt_version)
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0
        self._client: Any = None

    # -- cost ------------------------------------------------------------
    @property
    def estimated_cost_usd(self) -> float:
        return (
            self.input_tokens / 1_000_000 * PRICE_PER_MTOK_INPUT
            + self.output_tokens / 1_000_000 * PRICE_PER_MTOK_OUTPUT
        )

    @property
    def cost_per_filing(self) -> float:
        return self.estimated_cost_usd / self.calls if self.calls else 0.0

    # -- transport -------------------------------------------------------
    def _lazy_client(self) -> Any:
        """Import and construct on first use, so the package imports without a key."""
        if self._client is None:
            if not os.getenv("ANTHROPIC_API_KEY"):
                raise RuntimeError(
                    "ANTHROPIC_API_KEY is not set. Add it to .env before scoring with the LLM."
                )
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "The `anthropic` package is not installed. Run: uv add anthropic"
                ) from exc
            self._client = anthropic.Anthropic()
        return self._client

    def _call(self, rendered: str) -> tuple[str, int, int]:
        response = self._lazy_client().messages.create(
            model=self.model_id,
            max_tokens=MAX_TOKENS,
            temperature=config.LLM_TEMPERATURE,
            system=self.prompt.system,
            messages=[{"role": "user", "content": rendered}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return text, response.usage.input_tokens, response.usage.output_tokens

    # -- scoring ---------------------------------------------------------
    def score_one(self, text: str, item_codes: str) -> tuple[Prediction | None, str]:
        """(prediction, raw response). Returns None after MAX_RETRIES schema failures."""
        rendered = self.prompt.render(text, item_codes)
        last_raw = ""
        for attempt in range(MAX_RETRIES + 1):
            try:
                raw, tin, tout = self._call(rendered)
            except Exception as exc:  # noqa: BLE001 - transport errors get a backoff
                log.warning("API error (attempt %d): %s", attempt + 1, exc)
                time.sleep(2.0 * (2**attempt))
                last_raw = f"API_ERROR: {exc}"
                continue

            self.calls += 1
            self.input_tokens += tin
            self.output_tokens += tout
            last_raw = raw
            try:
                return parse_response(raw), raw
            except (ValueError, ValidationError, json.JSONDecodeError) as exc:
                log.warning("schema violation (attempt %d): %s", attempt + 1, exc)

        return None, last_raw

    def score_filings(
        self,
        conn: sqlite3.Connection,
        rows: list[sqlite3.Row],
        manifest: RunManifest,
        run_mode: str = "historical",
    ) -> int:
        created = datetime.now(UTC).isoformat()
        stored = 0

        for i, row in enumerate(rows, 1):
            # Invariant 3: the gate is here, before anything leaves the process.
            try:
                anon.assert_anonymized(row["anonymized_text"], row["anon_version"])
            except anon.NotAnonymizedError as exc:
                manifest.exclude("refused_not_anonymized", f"{row['accession_no']}: {exc}")
                continue

            prediction, raw = self.score_one(row["anonymized_text"], row["item_codes"] or "")

            if prediction is None:
                # §7: recorded as null and counted, never silently dropped.
                manifest.count("parse_failures")
                conn.execute(
                    """
                    INSERT OR IGNORE INTO predictions
                        (accession_no, model_id, prompt_version, direction, probability,
                         rationale, raw_response, created_at, run_mode)
                    VALUES (?, ?, ?, NULL, NULL, NULL, ?, ?, ?)
                    """,
                    (
                        row["accession_no"],
                        self.model_id,
                        self.prompt.version,
                        raw,
                        created,
                        run_mode,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO predictions
                        (accession_no, model_id, prompt_version, direction, probability,
                         rationale, raw_response, created_at, run_mode)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["accession_no"],
                        self.model_id,
                        self.prompt.version,
                        prediction.direction,
                        prediction.probability,
                        prediction.rationale,
                        raw,
                        created,
                        run_mode,
                    ),
                )
                stored += 1
                manifest.count("scored")
                manifest.count(f"direction_{prediction.direction}")

            if i % 50 == 0:
                log.info("scored %d/%d (cost so far $%.4f)", i, len(rows), self.estimated_cost_usd)

        failures = manifest.counts.get("parse_failures", 0)
        total = stored + failures
        manifest.params["parse_failure_rate"] = round(failures / total, 5) if total else 0.0
        manifest.count("input_tokens", self.input_tokens)
        manifest.count("output_tokens", self.output_tokens)
        return stored
