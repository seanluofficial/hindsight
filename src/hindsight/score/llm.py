"""LLM scoring: pluggable backend, strict JSON parsing, retries, cost accounting (§7).

Three rules from the brief are enforced here rather than hoped for:

* **Never coerce.** A response that fails the schema is retried, and after two retries
  recorded as a null prediction and counted in a reported failure rate (§7). Silently
  patching a malformed response into `direction="up"` would be fabricated data.
* **Never send raw text.** Every call passes `assert_anonymized()`, which raises unless
  the text carries the current anonymizer version and survives a leak scan (invariant 3).
* **Determinism.** Temperature 0, a pinned model ID recorded on every row, and a
  deterministic filing order upstream.

The backend is pluggable because the pre-registration fixes the *protocol* — one pinned
model, temperature 0, strict JSON — not the vendor. Which model was used is recorded on
every prediction row and in DEVIATIONS.md, so the choice is disclosed rather than assumed.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import requests
from pydantic import BaseModel, Field, ValidationError

from hindsight import config
from hindsight.manifest import RunManifest
from hindsight.score import anonymize as anon
from hindsight.score import prompt as prompts

log = logging.getLogger(__name__)

MAX_RETRIES = 2
MAX_TOKENS = 300

_RE_JSON = re.compile(r"\{.*\}", re.S)


@dataclass(frozen=True)
class Pricing:
    """USD per million tokens, pinned beside the model so a swap forces a price change."""

    input_per_mtok: float
    output_per_mtok: float


class Prediction(BaseModel):
    """The §7 output schema. Pydantic rejects anything else — no coercion."""

    direction: str = Field(pattern="^(up|down)$")
    probability: float = Field(ge=0.50, le=1.00)
    rationale: str = Field(min_length=1, max_length=2000)


def parse_response(raw: str) -> Prediction:
    """Strict parse. Raises on anything that is not the agreed schema.

    Tolerates a code fence or surrounding prose — a formatting quirk, not a semantic one —
    but never repairs the content.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    match = _RE_JSON.search(text)
    if not match:
        raise ValueError(f"no JSON object in response: {raw[:200]!r}")
    return Prediction.model_validate(json.loads(match.group(0)))


# --------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------
class Backend(Protocol):
    model_id: str
    pricing: Pricing

    def complete(self, system: str, user: str) -> tuple[str, int, int]:
        """(text, input_tokens, output_tokens)."""


class GeminiBackend:
    """Google Gemini via the REST API.

    Chosen for the pilot because its free tier needs no card. The key goes in the
    `x-goog-api-key` header rather than the documented `?key=` query parameter: this
    project caches by URL, and a key in the query string would be written into filenames
    under `data/raw/`.
    """

    BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, model_id: str = "gemini-2.0-flash", pricing: Pricing | None = None):
        self.model_id = model_id
        # Free tier bills nothing; the table exists so a paid upgrade reports real cost.
        self.pricing = pricing or Pricing(input_per_mtok=0.10, output_per_mtok=0.40)
        self.session = requests.Session()

    def _api_key(self) -> str:
        key = os.getenv("GEMINI_API_KEY", "").strip()
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Get a free key at https://aistudio.google.com/apikey "
                "and add it to .env"
            )
        return key

    def complete(self, system: str, user: str) -> tuple[str, int, int]:
        response = self.session.post(
            f"{self.BASE}/{self.model_id}:generateContent",
            headers={"x-goog-api-key": self._api_key(), "Content-Type": "application/json"},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {
                    "temperature": config.LLM_TEMPERATURE,
                    "maxOutputTokens": MAX_TOKENS,
                    # Ask for JSON at the transport level as well as in the prompt; it
                    # reduces formatting failures without loosening the parser.
                    "responseMimeType": "application/json",
                },
            },
            timeout=90,
        )
        response.raise_for_status()
        payload = response.json()
        candidates = payload.get("candidates") or []
        if not candidates:
            raise ValueError(f"no candidates in response: {str(payload)[:200]}")
        parts = candidates[0].get("content", {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
        usage = payload.get("usageMetadata", {})
        return (
            text,
            int(usage.get("promptTokenCount", 0)),
            int(usage.get("candidatesTokenCount", 0)),
        )


class AnthropicBackend:
    """Claude via the official SDK. Used when an ANTHROPIC_API_KEY is available."""

    def __init__(self, model_id: str = "claude-opus-4-5-20251101", pricing: Pricing | None = None):
        self.model_id = model_id
        self.pricing = pricing or Pricing(input_per_mtok=5.00, output_per_mtok=25.00)
        self._client: Any = None

    def _lazy_client(self) -> Any:
        if self._client is None:
            if not os.getenv("ANTHROPIC_API_KEY"):
                raise RuntimeError("ANTHROPIC_API_KEY is not set.")
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("The `anthropic` package is not installed.") from exc
            self._client = anthropic.Anthropic()
        return self._client

    def complete(self, system: str, user: str) -> tuple[str, int, int]:
        response = self._lazy_client().messages.create(
            model=self.model_id,
            max_tokens=MAX_TOKENS,
            temperature=config.LLM_TEMPERATURE,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return text, response.usage.input_tokens, response.usage.output_tokens


def make_backend(provider: str = "gemini") -> Backend:
    if provider == "gemini":
        return GeminiBackend()
    if provider == "anthropic":
        return AnthropicBackend()
    raise ValueError(f"unknown provider {provider!r}; expected 'gemini' or 'anthropic'")


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------
class ScoringClient:
    """Scores anonymized filings, tracking tokens and cost."""

    def __init__(
        self,
        backend: Backend | None = None,
        prompt_version: str = prompts.PROMPT_VERSION,
    ) -> None:
        self.backend = backend or make_backend()
        self.model_id = self.backend.model_id
        self.prompt = prompts.get(prompt_version)
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0

    @property
    def estimated_cost_usd(self) -> float:
        p = self.backend.pricing
        return (
            self.input_tokens / 1_000_000 * p.input_per_mtok
            + self.output_tokens / 1_000_000 * p.output_per_mtok
        )

    @property
    def cost_per_filing(self) -> float:
        return self.estimated_cost_usd / self.calls if self.calls else 0.0

    def score_one(self, text: str, item_codes: str) -> tuple[Prediction | None, str]:
        """(prediction, raw response). None after MAX_RETRIES schema failures."""
        rendered = self.prompt.render(text, item_codes)
        last_raw = ""
        for attempt in range(MAX_RETRIES + 1):
            try:
                raw, tin, tout = self.backend.complete(self.prompt.system, rendered)
            except Exception as exc:  # noqa: BLE001 - transport errors get a backoff
                log.warning("API error (attempt %d): %s", attempt + 1, exc)
                last_raw = f"API_ERROR: {exc}"
                time.sleep(2.0 * (2**attempt))
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
        throttle_seconds: float = 0.0,
    ) -> int:
        """Score each row. `throttle_seconds` paces free-tier per-minute limits."""
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
            values: tuple[Any, ...]
            if prediction is None:
                # §7: recorded as null and counted, never silently dropped.
                manifest.count("parse_failures")
                values = (
                    row["accession_no"],
                    self.model_id,
                    self.prompt.version,
                    None,
                    None,
                    None,
                    raw,
                    created,
                    run_mode,
                )
            else:
                values = (
                    row["accession_no"],
                    self.model_id,
                    self.prompt.version,
                    prediction.direction,
                    prediction.probability,
                    prediction.rationale,
                    raw,
                    created,
                    run_mode,
                )
                stored += 1
                manifest.count("scored")
                manifest.count(f"direction_{prediction.direction}")

            conn.execute(
                """
                INSERT OR IGNORE INTO predictions
                    (accession_no, model_id, prompt_version, direction, probability,
                     rationale, raw_response, created_at, run_mode)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )

            if throttle_seconds:
                time.sleep(throttle_seconds)
            if i % 25 == 0:
                log.info("scored %d/%d (cost so far $%.4f)", i, len(rows), self.estimated_cost_usd)

        failures = manifest.counts.get("parse_failures", 0)
        total = stored + failures
        manifest.params["parse_failure_rate"] = round(failures / total, 5) if total else 0.0
        manifest.count("input_tokens", self.input_tokens)
        manifest.count("output_tokens", self.output_tokens)
        return stored
