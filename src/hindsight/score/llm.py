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
# Generous on purpose. At 300 the model was cut off mid-rationale, so the closing brace
# never arrived and the strict parser refused a response that was otherwise fine — schema
# failures that looked like incompetence but were a truncated buffer.
MAX_TOKENS = 800

_RE_JSON = re.compile(r"\{.*\}", re.S)


# A per-minute limit clears in about a minute. A retry-after beyond this means a *daily*
# budget is spent, and no amount of waiting inside this run will clear it.
DAILY_QUOTA_RETRY_THRESHOLD_S = 300.0


class RateLimitedError(RuntimeError):
    """Provider throttling. Distinct from a schema failure, and waited out, not counted."""

    def __init__(self, retry_after_seconds: float) -> None:
        super().__init__(f"rate limited; retry after {retry_after_seconds:.0f}s")
        self.retry_after_seconds = retry_after_seconds

    @property
    def is_daily_quota(self) -> bool:
        """Whether waiting is futile within this run."""
        return self.retry_after_seconds >= DAILY_QUOTA_RETRY_THRESHOLD_S


class DailyQuotaExhaustedError(RuntimeError):
    """The provider's per-day token budget is spent. Stop; resume tomorrow."""


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

    # Take the FIRST balanced object, not a greedy span to the last brace: when the model
    # emits two objects, a greedy match captures both and json.loads reports "Extra data".
    # A truncated response yields no balanced object and is rejected, which is correct —
    # half a rationale is not a prediction.
    decoder = json.JSONDecoder()
    start = text.find("{")
    if start == -1:
        raise ValueError(f"no JSON object in response: {raw[:200]!r}")
    payload, _ = decoder.raw_decode(text[start:])
    return Prediction.model_validate(payload)


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

    # Pinned, never a `-latest` alias: a floating alias would silently change the model
    # between runs and break reproducibility (invariant 4). gemini-2.5-flash is capped at
    # 20 requests/day on the free tier, which is too tight for a 500-filing pilot.
    def __init__(self, model_id: str = "gemini-3.5-flash", pricing: Pricing | None = None):
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

    @staticmethod
    def _retry_after_seconds(payload: dict[str, Any]) -> float:
        """Google suggests a delay in the error body; honour it rather than guessing."""
        message = str(payload.get("error", {}).get("message", ""))
        match = re.search(r"retry in ([\d.]+)s", message, re.I)
        return min(float(match.group(1)) + 1.0, 65.0) if match else 20.0

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
                    # Schema-enforced output. The parser stays strict regardless — this
                    # just stops the model from emitting prose or a second object, which
                    # it otherwise does often enough to matter.
                    "responseSchema": {
                        "type": "OBJECT",
                        "properties": {
                            "direction": {"type": "STRING", "enum": ["up", "down"]},
                            "probability": {"type": "NUMBER"},
                            "rationale": {"type": "STRING"},
                        },
                        "required": ["direction", "probability", "rationale"],
                    },
                    # Gemini 2.5+ spends output tokens on internal reasoning before
                    # emitting anything. Left on, the budget is consumed thinking and the
                    # response comes back truncated or empty, which the strict parser
                    # correctly rejects — producing a wall of schema failures that look
                    # like model incompetence rather than a transport setting.
                    "thinkingConfig": {"thinkingBudget": 0},
                },
            },
            timeout=90,
        )
        if response.status_code == 429:
            # Throttling is not a schema failure. Surfacing it as a distinct exception
            # keeps §7's parse-failure rate meaning "the model produced invalid JSON"
            # rather than silently absorbing "we called too fast".
            raise RateLimitedError(self._retry_after_seconds(response.json()))
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


class GroqBackend:
    """Groq via its OpenAI-compatible endpoint.

    Free tier allows ~1,000 requests/day, enough to score the whole pilot in one run —
    Gemini's free tier caps `gemini-2.5-flash` at 20/day, which would have taken 25 days.
    """

    URL = "https://api.groq.com/openai/v1/chat/completions"

    # Free tier: 1,000 requests/day, but the binding limit is 12,000 tokens/minute. Filing
    # prompts average ~3,000 tokens, so throughput is ~4/minute regardless of throttle.
    # Filings are NOT truncated to fit: shortening the input to buy speed would change
    # what the model is being asked to read.
    def __init__(
        self, model_id: str = "openai/gpt-oss-120b", pricing: Pricing | None = None
    ) -> None:
        self.model_id = model_id
        # Free tier bills nothing; the table exists so a paid upgrade reports real cost.
        self.pricing = pricing or Pricing(input_per_mtok=0.59, output_per_mtok=0.79)
        self.session = requests.Session()

    def _api_key(self) -> str:
        key = os.getenv("GROQ_API_KEY", "").strip()
        if not key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Get a free key at https://console.groq.com/keys "
                "and add it to .env"
            )
        return key

    def complete(self, system: str, user: str) -> tuple[str, int, int]:
        response = self.session.post(
            self.URL,
            headers={
                "Authorization": f"Bearer {self._api_key()}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model_id,
                "temperature": config.LLM_TEMPERATURE,
                "max_tokens": MAX_TOKENS,
                # JSON mode, so the model cannot wrap the object in prose. The parser
                # stays strict regardless.
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=90,
        )
        if response.status_code == 429:
            retry_after = response.headers.get("retry-after")
            seconds = float(retry_after) if retry_after else 20.0
            # Do NOT clamp before classifying: a 680-second retry-after means the daily
            # token budget is spent, and clamping it to 65s turns a "come back tomorrow"
            # into an infinite polling loop that never scores anything.
            raise RateLimitedError(seconds)
        response.raise_for_status()
        payload = response.json()
        text = payload["choices"][0]["message"]["content"] or ""
        usage = payload.get("usage", {})
        return text, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))


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


def make_backend(provider: str = "groq") -> Backend:
    if provider == "groq":
        return GroqBackend()
    if provider == "gemini":
        return GeminiBackend()
    if provider == "anthropic":
        return AnthropicBackend()
    raise ValueError(f"unknown provider {provider!r}; expected groq, gemini or anthropic")


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
        self.rate_limit_waits = 0

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
        """(prediction, raw response). None after MAX_RETRIES *schema* failures.

        Throttling does not consume an attempt: §7's failure rate is a claim about the
        model's output, so burning attempts on rate limits would report the provider's
        quota as the model's incompetence.
        """
        rendered = self.prompt.render(text, item_codes)
        last_raw = ""
        attempt = 0
        while attempt <= MAX_RETRIES:
            try:
                raw, tin, tout = self.backend.complete(self.prompt.system, rendered)
            except RateLimitedError as limited:
                if limited.is_daily_quota:
                    raise DailyQuotaExhaustedError(
                        f"daily token budget spent; provider asks for "
                        f"{limited.retry_after_seconds:.0f}s"
                    ) from limited
                self.rate_limit_waits += 1
                log.info("throttled; sleeping %.0fs", limited.retry_after_seconds)
                time.sleep(min(limited.retry_after_seconds, 65.0))
                continue  # deliberately does not increment `attempt`
            except Exception as exc:  # noqa: BLE001 - transport errors get a backoff
                log.warning("API error (attempt %d): %s", attempt + 1, exc)
                last_raw = f"API_ERROR: {exc}"
                time.sleep(2.0 * (2**attempt))
                attempt += 1
                continue

            self.calls += 1
            self.input_tokens += tin
            self.output_tokens += tout
            last_raw = raw
            try:
                return parse_response(raw), raw
            except (ValueError, ValidationError, json.JSONDecodeError) as exc:
                log.warning("schema violation (attempt %d): %s", attempt + 1, exc)
                attempt += 1

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

            # Capped identically to the lexicon path (§8).
            text = anon.scoring_text(row["anonymized_text"])
            if anon.was_truncated(row["anonymized_text"]):
                manifest.count("truncated_to_cap")
            try:
                prediction, raw = self.score_one(text, row["item_codes"] or "")
            except DailyQuotaExhaustedError as exhausted:
                # Stop cleanly. Filings never attempted are NOT parse failures, and
                # counting them as such would report the provider's budget as the model's
                # failure rate. Everything scored so far is already committed.
                remaining = len(rows) - i + 1
                manifest.count("halted_daily_quota")
                manifest.count("filings_unattempted", remaining)
                manifest.error(
                    f"{exhausted} — stopped with {remaining} filings unattempted; "
                    "re-run to resume, nothing is lost."
                )
                log.warning("daily quota spent; %d filings unattempted", remaining)
                break
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
        # Recorded separately so the failure rate above stays a claim about the model.
        manifest.count("rate_limit_waits", self.rate_limit_waits)
        return stored
