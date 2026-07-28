"""Rate-limited, disk-cached HTTP.

Two rules, both from CLAUDE.md:

* EDGAR gets a descriptive User-Agent and no more than 10 requests/second. We throttle
  below that ceiling.
* Every fetch is cached under `data/raw/`, so a rerun never refetches. This is what makes
  a full 2010-2024 crawl restartable and what keeps the pipeline reproducible offline.

The cache is keyed by URL path, not by a hash, so a human can browse `data/raw/` and see
exactly which EDGAR documents the study used.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from hindsight import config

log = logging.getLogger(__name__)

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


class RateLimitExhaustedError(RuntimeError):
    """A quota was hit and retrying inside this run cannot clear it.

    Distinct from a fetch failure on purpose. A vendor refusing to serve a ticker because
    the hourly allocation is spent says nothing about whether that ticker has data — and
    recording it as missing coverage would corrupt the one statistic that tells us whether
    survivorship bias crept in. Callers should stop and resume later, not mark the
    remaining work as unavailable.
    """


class RateLimiter:
    """Thread-safe minimum-interval limiter."""

    def __init__(self, max_per_second: float) -> None:
        self._min_interval = 1.0 / max_per_second
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            sleep_for = self._min_interval - (now - self._last)
            if sleep_for > 0:
                time.sleep(sleep_for)
            self._last = time.monotonic()


_edgar_limiter = RateLimiter(config.EDGAR_MAX_REQUESTS_PER_SECOND)


def cache_path_for(url: str) -> Path:
    """Mirror the remote path under `data/raw/<host>/...` so the cache is browsable."""
    parsed = urlparse(url)
    host = _UNSAFE.sub("_", parsed.netloc)
    parts = [_UNSAFE.sub("_", p) for p in parsed.path.strip("/").split("/") if p]
    if not parts:
        parts = ["index"]
    if parsed.query:
        stem = parts[-1]
        parts[-1] = f"{stem}__{_UNSAFE.sub('_', parsed.query)}"
    return config.RAW_DIR / host / Path(*parts)


class CachedFetcher:
    """Fetches URLs, caching bodies to disk and throttling live requests."""

    def __init__(
        self,
        user_agent: str = config.EDGAR_USER_AGENT,
        limiter: RateLimiter | None = None,
        max_retries: int = 4,
    ) -> None:
        self.max_retries = max_retries
        self.limiter = limiter or _edgar_limiter
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Encoding": "gzip, deflate",
            }
        )
        self.hits = 0
        self.misses = 0

    def get(self, url: str, *, use_cache: bool = True, timeout: int = 60) -> bytes:
        """Return the response body, from disk when available.

        Raises `requests.HTTPError` after exhausting retries. A 404 fails immediately —
        retrying a missing document just wastes the rate-limit budget.
        """
        path = cache_path_for(url)
        if use_cache and path.exists():
            self.hits += 1
            return path.read_bytes()

        body = self._fetch_live(url, timeout=timeout)
        self.misses += 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return body

    def get_text(self, url: str, *, encoding: str = "latin-1", use_cache: bool = True) -> str:
        """EDGAR archives are a mix of encodings; latin-1 never raises and never loses bytes."""
        return self.get(url, use_cache=use_cache).decode(encoding, errors="replace")

    def _fetch_live(self, url: str, timeout: int) -> bytes:
        last_error: Exception | None = None
        throttled = False
        for attempt in range(self.max_retries):
            self.limiter.wait()
            try:
                response = self.session.get(url, timeout=timeout)
                if response.status_code == 404:
                    response.raise_for_status()
                if response.status_code in (429, 503):
                    # Backing off is mandatory here: SEC blocks persistent offenders.
                    throttled = True
                    wait = 2.0 * (2**attempt)
                    log.warning(
                        "throttled (%s) on %s; sleeping %.1fs", response.status_code, url, wait
                    )
                    time.sleep(wait)
                    last_error = requests.HTTPError(f"{response.status_code} for {url}")
                    continue
                response.raise_for_status()
                return response.content
            except requests.HTTPError:
                raise
            except requests.RequestException as exc:
                last_error = exc
                wait = 1.0 * (2**attempt)
                log.warning("request failed on %s (%s); retrying in %.1fs", url, exc, wait)
                time.sleep(wait)

        if throttled:
            # Every attempt was refused for throttling. Treat as a quota wall, not a
            # verdict on whether this resource exists.
            raise RateLimitExhaustedError(
                f"still throttled after {self.max_retries} attempts: {url}"
            ) from last_error
        raise RuntimeError(f"giving up on {url} after {self.max_retries} attempts") from last_error
