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

PROMPT_VERSION = "p1"


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

PROMPTS: dict[str, Prompt] = {P1.version: P1}


def get(version: str = PROMPT_VERSION) -> Prompt:
    if version not in PROMPTS:
        raise KeyError(f"unknown prompt version {version!r}; known: {sorted(PROMPTS)}")
    return PROMPTS[version]
