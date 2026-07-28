"""Run manifests: what went in, what came out, and what was thrown away.

Invariant 5 says nothing is silently dropped. That is only true if dropping something
is *inconvenient* — so every exclusion goes through `RunManifest.exclude()`, which
demands a reason and keeps a count. The manifest is written to disk as JSON whether the
run succeeds or fails; a crashed run that discarded 4,000 filings should leave evidence.

Manifests are files rather than a sixth table because CLAUDE.md fixes the schema at five.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from hindsight import config


def git_sha() -> str:
    """Current commit, with a marker if the tree is dirty. 'unknown' outside a repo."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=config.ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=config.ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return f"{sha}-dirty" if dirty else sha
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


class RunManifest:
    """Accumulates provenance for one run and writes it to `data/manifests/`."""

    def __init__(self, stage: str, **params: Any) -> None:
        self.stage = stage
        self.params = params
        self.started_at = datetime.now(UTC)
        self.counts: Counter[str] = Counter()
        self.exclusions: Counter[str] = Counter()
        self.exclusion_examples: dict[str, list[str]] = {}
        self.errors: list[str] = []
        self.finished_at: datetime | None = None

    # -- recording -------------------------------------------------------
    def count(self, key: str, n: int = 1) -> None:
        """Record throughput, e.g. `count('filings_written')`."""
        self.counts[key] += n

    def exclude(self, reason: str, identifier: str | None = None) -> None:
        """Record one dropped item. `reason` is required; that is the point."""
        self.exclusions[reason] += 1
        if identifier is not None:
            examples = self.exclusion_examples.setdefault(reason, [])
            if len(examples) < 5:
                examples.append(identifier)

    def error(self, message: str) -> None:
        self.errors.append(message)

    @property
    def total_excluded(self) -> int:
        return sum(self.exclusions.values())

    # -- output ----------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        finished = self.finished_at or datetime.now(UTC)
        return {
            "stage": self.stage,
            "git_sha": git_sha(),
            "started_at_utc": self.started_at.isoformat(),
            "finished_at_utc": finished.isoformat(),
            "duration_seconds": round((finished - self.started_at).total_seconds(), 1),
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "params": self.params,
            "counts": dict(sorted(self.counts.items())),
            "exclusions": dict(sorted(self.exclusions.items())),
            "exclusion_examples": self.exclusion_examples,
            "total_excluded": self.total_excluded,
            "errors": self.errors,
        }

    def write(self) -> Path:
        config.ensure_dirs()
        stamp = self.started_at.strftime("%Y%m%dT%H%M%SZ")
        path = config.MANIFEST_DIR / f"{stamp}_{self.stage}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return path

    def summary(self) -> str:
        lines = [f"[{self.stage}] {self.params}"]
        for k, v in sorted(self.counts.items()):
            lines.append(f"  {k}: {v:,}")
        if self.exclusions:
            lines.append(f"  excluded ({self.total_excluded:,} total):")
            for reason, n in self.exclusions.most_common():
                lines.append(f"    {reason}: {n:,}")
        if self.errors:
            lines.append(f"  errors: {len(self.errors)}")
        return "\n".join(lines)

    # -- context manager -------------------------------------------------
    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # Written on the failure path too — a crash must not erase the exclusion record.
        if exc is not None:
            self.error(f"{exc_type.__name__ if exc_type else 'Error'}: {exc}")
        self.finished_at = datetime.now(UTC)
        path = self.write()
        print(self.summary())
        print(f"  manifest: {path}")
