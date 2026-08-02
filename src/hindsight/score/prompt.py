"""Versioned prompt templates (PREREGISTRATION §7).

Every stored prediction records the `prompt_version` that produced it, so a change here
creates a new generation of predictions rather than silently reinterpreting old ones.
Templates are append-only: never edit a released version, add the next one.

The prompt deliberately does *not* ask the model to identify the company, mention that
filings are anonymized in a recoverable way, or hint at the study period. Any of those
invites the model to reach for what it remembers instead of what it reads.
"""

from __future__ import annotations

from dataclasses import dataclass

# p1.1 supersedes p1. The prompt *text* is unchanged; the generation configuration is not.
# Under p1 the output budget was 300 tokens with no response schema, which truncated the
# model mid-rationale and produced null predictions that looked like model failures but
# were a harness bug. Those p1 rows are left in place — predictions are immutable — and
# p1.1 re-scores under the corrected configuration, so the §7 failure rate describes the
# model rather than my buffer size.
PROMPT_VERSION = "p1.1"


@dataclass(frozen=True)
class Prompt:
    version: str
    system: str
    template: str

    def render(self, anonymized_text: str, item_codes: str = "") -> str:
        items = item_codes or "not disclosed"
        return self.template.format(items=items, filing=anonymized_text)


# Asks for exactly the §7 schema and nothing else. "One sentence" keeps the rationale
# from becoming a hedge long enough to contain both directions.
P1 = Prompt(
    version="p1",
    system=(
        "You are a careful equity analyst. You read a corporate disclosure and forecast "
        "the issuer's stock return over the next five trading days, relative to the "
        "market. You cannot see the company name, ticker, or date, and you must not "
        "guess at them. Judge only what the text says. Respond with JSON only."
    ),
    template=(
        "Below is an anonymized excerpt from a US public company's SEC Form 8-K filing. "
        "Identifying details have been replaced with placeholders such as [COMPANY], "
        "[PERSON] and [DATE].\n\n"
        "Reported 8-K item codes: {items}\n\n"
        "--- BEGIN FILING ---\n{filing}\n--- END FILING ---\n\n"
        "Forecast the issuer's market-excess stock return over the five trading days "
        "following this disclosure.\n\n"
        "Respond with a single JSON object and nothing else:\n"
        '{{"direction": "up" or "down", "probability": a number from 0.50 to 1.00, '
        '"rationale": "one sentence"}}\n\n'
        "`probability` is your confidence that `direction` is correct. Use 0.50 when the "
        "filing gives you no directional information; reserve values above 0.80 for "
        "disclosures whose implication is unambiguous."
    ),
)

# Same text, re-versioned to mark the corrected generation configuration.
P1_1 = Prompt(version="p1.1", system=P1.system, template=P1.template)

# Contamination audit (PREREGISTRATION §6). Asks the model to do the one thing the
# forecasting prompt forbids: name the issuer.
#
# This prompt is deliberately *generous* to the model — it invites a guess and offers an
# explicit "unknown" escape hatch. An audit that made identification hard would understate
# contamination, and understating it is the failure mode that would let a memorised result
# pass as a forecast. Better to overestimate the threat than to flatter the anonymizer.
AUDIT = Prompt(
    version="audit-v1",
    system=(
        "You are an expert on US public companies and their SEC filings. You will be "
        "shown an anonymized excerpt from a Form 8-K. Identify the company if you can. "
        "Respond with JSON only."
    ),
    template=(
        "The following is an anonymized SEC Form 8-K. Identifying details have been "
        "replaced with placeholders such as [COMPANY], [PERSON], [DATE] and [ADDRESS].\n\n"
        "Reported 8-K item codes: {items}\n\n"
        "--- BEGIN FILING ---\n{filing}\n--- END FILING ---\n\n"
        "Which company filed this? Use any clue: business description, financial scale, "
        "industry jargon, segment names, products, or writing style. Guess if you are "
        "unsure.\n\n"
        "Respond with a single JSON object and nothing else:\n"
        '{{"company": "your best guess, or \\"unknown\\" if you truly cannot tell", '
        '"ticker": "ticker symbol, or \\"unknown\\"", '
        '"confidence": a number from 0.00 to 1.00, '
        '"reasoning": "one sentence naming the clues you used"}}'
    ),
)

PROMPTS: dict[str, Prompt] = {P1.version: P1, P1_1.version: P1_1, AUDIT.version: AUDIT}


def get(version: str = PROMPT_VERSION) -> Prompt:
    if version not in PROMPTS:
        raise KeyError(f"unknown prompt version {version!r}; known: {sorted(PROMPTS)}")
    return PROMPTS[version]
