"""Invariant 5: nothing is silently dropped.

That invariant is only real if a dropped item is impossible to record without a reason,
and if the record survives a crash.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hindsight import config
from hindsight.manifest import RunManifest


@pytest.fixture(autouse=True)
def _isolated_manifest_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "MANIFEST_DIR", tmp_path / "manifests")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")


class TestCounting:
    def test_counts_accumulate(self) -> None:
        m = RunManifest("test")
        m.count("filings_written", 3)
        m.count("filings_written")
        assert m.counts["filings_written"] == 4

    def test_exclusions_require_a_reason_and_are_tallied(self) -> None:
        m = RunManifest("test")
        m.exclude("no_extractable_text", "acc-1")
        m.exclude("no_extractable_text", "acc-2")
        m.exclude("not_in_universe_on_filing_date", "acc-3")
        assert m.exclusions["no_extractable_text"] == 2
        assert m.total_excluded == 3

    def test_examples_are_capped_but_counts_are_not(self) -> None:
        m = RunManifest("test")
        for i in range(50):
            m.exclude("thin_text", f"acc-{i}")
        assert m.exclusions["thin_text"] == 50
        assert len(m.exclusion_examples["thin_text"]) == 5


class TestPersistence:
    def test_writes_json_with_provenance(self) -> None:
        with RunManifest("ingest", year=2018) as m:
            m.count("filings_written", 10)
            m.exclude("no_extractable_text", "acc-1")

        files = list(config.MANIFEST_DIR.glob("*_ingest.json"))
        assert len(files) == 1
        payload = json.loads(files[0].read_text(encoding="utf-8"))
        assert payload["params"]["year"] == 2018
        assert payload["counts"]["filings_written"] == 10
        assert payload["exclusions"]["no_extractable_text"] == 1
        assert payload["total_excluded"] == 1
        assert "git_sha" in payload and "duration_seconds" in payload

    def test_manifest_survives_a_crash(self) -> None:
        # A run that dies after discarding 4,000 filings must still leave the evidence.
        with pytest.raises(ValueError), RunManifest("ingest") as m:
            m.exclude("something", "x")
            raise ValueError("boom")

        payload = json.loads(next(config.MANIFEST_DIR.glob("*_ingest.json")).read_text("utf-8"))
        assert payload["exclusions"]["something"] == 1
        assert any("boom" in e for e in payload["errors"])
