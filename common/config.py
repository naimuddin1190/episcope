"""Central configuration for EpiScope.

Every path is derived from environment variables (loaded from .env) so that nothing
(dates, file names, row counts) is hard-coded in the pipeline. See README "Configuration".
"""
from __future__ import annotations

import os
from pathlib import Path

try:  # python-dotenv is optional at import time (tests may run without it)
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

REPO_ROOT = Path(__file__).resolve().parents[1]
if load_dotenv is not None:
    load_dotenv(REPO_ROOT / ".env")

DATA_DIR = Path(os.environ.get("EPISCOPE_DATA_DIR", REPO_ROOT / "data")).resolve()
REFERENCE_DIR = REPO_ROOT / "reference"

LANDING = DATA_DIR / "landing"            # where feeds (and the hidden test drop) arrive
GROUND_TRUTH = DATA_DIR / "ground_truth"  # written by the generator ONLY; never read by detection
LAKE = DATA_DIR / "lake"
BRONZE = LAKE / "bronze"
SILVER = LAKE / "silver"
GOLD = LAKE / "gold"
META = LAKE / "_meta"
CATALOG_DIR = LAKE / "_catalog"
SERVING_OUT = Path(os.environ.get("EPISCOPE_SERVING_DIR", REPO_ROOT / "dashboard" / "data")).resolve()
EXPERIMENTS = REPO_ROOT / "docs" / "experiments"

SALT_ENV = "EPISCOPE_SALT"

# Disease groups used throughout (ICD-10 prefix -> group). Background codes map to "other".
DISEASES = ["dengue", "diarrhoea", "ili", "malaria"]
FORECAST_DISEASES = ["dengue", "diarrhoea"]

# Reporting delays can be up to 21 days (Section 5.2); a week is treated as "mature"
# once its last day is at least this many days before the data cutoff.
MATURITY_DAYS = 14
MAX_DELAY_DAYS = 21


def get_salt() -> str:
    salt = os.environ.get(SALT_ENV)
    if not salt:
        raise RuntimeError(
            f"{SALT_ENV} is not set. Run `make env` (creates .env with a random salt) "
            "or export it. The salt must never be committed (PRV-1)."
        )
    return salt


def ensure_dirs() -> None:
    for p in (LANDING, GROUND_TRUTH, BRONZE, SILVER, GOLD, META, CATALOG_DIR, SERVING_OUT, EXPERIMENTS):
        p.mkdir(parents=True, exist_ok=True)
