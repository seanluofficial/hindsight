"""Strict response parsing (§7).

Every case here came from a real Gemini response during the pilot. The rule the module
must never break: reject rather than repair. A prediction patched together from half a
response is fabricated data, and it would be indistinguishable from a real one afterwards.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hindsight.score import llm


class TestWellFormed:
    def test_plain_json(self) -> None:
        p = llm.parse_response('{"direction":"up","probability":0.7,"rationale":"revenue beat"}')
        assert (p.direction, p.probability) == ("up", 0.7)

    def test_code_fenced(self) -> None:
        raw = '```json\n{"direction":"down","probability":0.6,"rationale":"guidance cut"}\n```'
        assert llm.parse_response(raw).direction == "down"

    def test_leading_prose(self) -> None:
        raw = 'Here is my answer:\n{"direction":"up","probability":0.55,"rationale":"ok"}'
        assert llm.parse_response(raw).direction == "up"


class TestMalformed:
    def test_truncated_response_is_rejected(self) -> None:
        """maxOutputTokens too low cut the model off mid-rationale.

        The closing brace never arrives. Accepting this would mean inventing the missing
        fields, so it must raise.
        """
        raw = '{"direction": "down", "probability": 0.55, "rationale": "The sudden resignation'
        with pytest.raises((ValueError, ValidationError)):
            llm.parse_response(raw)

    def test_two_objects_takes_the_first(self) -> None:
        """A greedy `\\{.*\\}` span captured both and json.loads reported 'Extra data'."""
        raw = (
            '{"direction":"up","probability":0.8,"rationale":"a"}\n'
            '{"direction":"down","probability":0.9,"rationale":"b"}'
        )
        assert llm.parse_response(raw).direction == "up"

    def test_no_json_at_all(self) -> None:
        with pytest.raises(ValueError, match="no JSON object"):
            llm.parse_response("I am unable to make a prediction.")

    def test_empty_response(self) -> None:
        with pytest.raises(ValueError):
            llm.parse_response("")


class TestSchemaIsNotCoerced:
    """§7 bounds the output. Values outside it are rejected, never clamped."""

    def test_probability_below_half_rejected(self) -> None:
        with pytest.raises(ValidationError):
            llm.parse_response('{"direction":"up","probability":0.2,"rationale":"x"}')

    def test_probability_above_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            llm.parse_response('{"direction":"up","probability":1.4,"rationale":"x"}')

    def test_invalid_direction_rejected(self) -> None:
        with pytest.raises(ValidationError):
            llm.parse_response('{"direction":"sideways","probability":0.7,"rationale":"x"}')

    def test_missing_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            llm.parse_response('{"direction":"up","probability":0.7}')

    def test_empty_rationale_rejected(self) -> None:
        with pytest.raises(ValidationError):
            llm.parse_response('{"direction":"up","probability":0.7,"rationale":""}')

    def test_boundary_values_accepted(self) -> None:
        assert (
            llm.parse_response('{"direction":"up","probability":0.5,"rationale":"x"}').probability
            == 0.5
        )
        assert (
            llm.parse_response('{"direction":"down","probability":1.0,"rationale":"x"}').probability
            == 1.0
        )


class TestRateLimitIsNotASchemaFailure:
    """Throttling must not pollute the §7 parse-failure rate."""

    def test_retry_delay_is_read_from_the_error_body(self) -> None:
        payload = {"error": {"message": "Quota exceeded. Please retry in 17.6421s."}}
        assert llm.GeminiBackend._retry_after_seconds(payload) == pytest.approx(18.6421, abs=0.01)

    def test_missing_delay_falls_back(self) -> None:
        assert llm.GeminiBackend._retry_after_seconds({"error": {"message": "nope"}}) == 20.0

    def test_delay_is_capped(self) -> None:
        payload = {"error": {"message": "retry in 9999s"}}
        assert llm.GeminiBackend._retry_after_seconds(payload) == 65.0

    def test_rate_limited_carries_its_delay(self) -> None:
        assert llm.RateLimitedError(30.0).retry_after_seconds == 30.0


class TestDailyQuotaIsNotAMinuteLimit:
    """A 680s retry-after means 'come back tomorrow', not 'wait a minute'.

    Clamping it to 65s and looping turned a spent daily budget into an infinite poll that
    scored nothing for 60 consecutive attempts.
    """

    def test_short_delay_is_a_minute_limit(self) -> None:
        assert not llm.RateLimitedError(45.0).is_daily_quota

    def test_long_delay_is_a_daily_quota(self) -> None:
        assert llm.RateLimitedError(680.0).is_daily_quota

    def test_threshold_boundary(self) -> None:
        assert not llm.RateLimitedError(299.0).is_daily_quota
        assert llm.RateLimitedError(300.0).is_daily_quota


class TestPinnedModel:
    def test_default_model_is_pinned_not_an_alias(self) -> None:
        """A `-latest` alias would silently change models between runs (invariant 4)."""
        assert "latest" not in llm.GeminiBackend().model_id
