"""Central configuration: paths, study constants, secrets.

Every number a result depends on lives here, so a reviewer can find all of them in
one file and a rerun cannot silently drift. Constants fixed by PREREGISTRATION.md
carry the section that fixes them; those are LOCKED and changing one invalidates
the study unless the change is recorded in DEVIATIONS.md.
"""

from __future__ import annotations

import os
from datetime import date, time
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
MANIFEST_DIR = DATA_DIR / "manifests"
LOG_DIR = ROOT / "logs"

DB_PATH = Path(os.getenv("HINDSIGHT_DB_PATH") or (DATA_DIR / "hindsight.db"))
LM_DICTIONARY_PATH = DATA_DIR / "lm_dictionary.csv"

# Point-in-time S&P 500 membership, reconstructed once and then frozen. Ingest reads
# only this file, never the live web, so reruns reproduce exactly (invariant 4).
UNIVERSE_CSV_PATH = DATA_DIR / "sp500_membership.csv"


def ensure_dirs() -> None:
    """Create the directories a run writes into. Safe to call repeatedly."""
    for d in (DATA_DIR, RAW_DIR, MANIFEST_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# Study window and universe (PREREGISTRATION §3)
# --------------------------------------------------------------------------
STUDY_START = date(2010, 1, 1)
STUDY_END = date(2024, 12, 31)

# Exclusions fixed in advance (§3). Each is counted and reported, never silently applied.
ACCEPTANCE_WINDOW_ET = (time(4, 0), time(20, 0))
MIN_PRIOR_CLOSE_USD = 5.00
MIN_ANONYMIZED_CHARS = 200

# --------------------------------------------------------------------------
# Timing (PREREGISTRATION §4) — the most important rule in the project
# --------------------------------------------------------------------------
MARKET_TZ = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
ENTRY_CUTOFF_ET = time(16, 0)
NYSE_CALENDAR_NAME = "XNYS"

# --------------------------------------------------------------------------
# Horizons and benchmark (PREREGISTRATION §5)
# --------------------------------------------------------------------------
# All three are reported. There is no primary horizon; reporting only the best is prohibited.
HORIZONS_TRADING_DAYS: tuple[int, ...] = (1, 5, 20)
BENCHMARK_TICKER = "SPY"

# --------------------------------------------------------------------------
# Costs (PREREGISTRATION §10)
# --------------------------------------------------------------------------
COST_LEVELS_BPS: tuple[int, ...] = (0, 10, 25)
BASE_CASE_COST_BPS = 10

# --------------------------------------------------------------------------
# Contamination audit (PREREGISTRATION §6) and null result (§14)
# --------------------------------------------------------------------------
CONTAMINATION_SAMPLE_SIZE = 500
CONTAMINATION_IDENTIFICATION_THRESHOLD = 0.20
NULL_RESULT_SHARPE_THRESHOLD = 0.30

# --------------------------------------------------------------------------
# Determinism (invariant 4)
# --------------------------------------------------------------------------
RANDOM_SEED = 20260727
LLM_TEMPERATURE = 0.0

# --------------------------------------------------------------------------
# Data sources
# --------------------------------------------------------------------------
EDGAR_ARCHIVES = "https://www.sec.gov/Archives"
EDGAR_FULL_INDEX = f"{EDGAR_ARCHIVES}/edgar/full-index"
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

# SEC publishes a ceiling of 10 requests/second. We sit deliberately under it: being
# throttled mid-crawl costs far more than the throughput we give up.
EDGAR_MAX_REQUESTS_PER_SECOND = 8.0
EDGAR_CONTACT = os.getenv("HINDSIGHT_EDGAR_CONTACT", "seanlu727@gmail.com")
EDGAR_USER_AGENT = f"hindsight research pipeline ({EDGAR_CONTACT})"

TIINGO_BASE_URL = "https://api.tiingo.com/tiingo/daily"


def tiingo_api_key() -> str:
    """Return the Tiingo key, failing loudly rather than silently degrading.

    Resolved at call time, not import time, so the package can be imported and tested
    without credentials present.
    """
    key = os.getenv("TIINGO_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "TIINGO_API_KEY is not set. Copy .env.example to .env and add your key "
            "from https://www.tiingo.com/account/api/token"
        )
    return key
