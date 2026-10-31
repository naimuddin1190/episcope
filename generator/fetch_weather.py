"""S3: download daily weather per district centroid from the Open-Meteo historical archive.

Raw API responses are cached unchanged in data/landing/weather/ (one JSON per district and
date range), so repeated runs never hit the API again (respect rate limits, ING-1).

Usage:
    python -m generator.fetch_weather --start 2021-01-01 --end 2025-12-31
    python -m generator.fetch_weather --synthetic   # offline fallback, clearly flagged as synthetic
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from common import config

API = "https://archive-api.open-meteo.com/v1/archive"
DAILY_VARS = "precipitation_sum,temperature_2m_mean,relative_humidity_2m_mean"


def out_path(code: str, start: str, end: str) -> Path:
    return config.LANDING / "weather" / f"weather_{code}_{start}_{end}.json"


def fetch_real(districts: pd.DataFrame, start: str, end: str, pause: float) -> None:
    import requests

    for row in districts.itertuples():
        path = out_path(row.district_code, start, end)
        if path.exists():
            continue
        params = {
            "latitude": row.lat, "longitude": row.lon, "start_date": start, "end_date": end,
            "daily": DAILY_VARS, "timezone": "Asia/Dhaka",
        }
        for attempt in range(5):
            r = requests.get(API, params=params, timeout=60)
            if r.status_code == 429:  # rate limited: back off
                time.sleep(30 * (attempt + 1))
                continue
            r.raise_for_status()
            payload = r.json()
            payload["episcope"] = {"district_code": row.district_code, "source": "open-meteo", "synthetic": False}
            path.write_text(json.dumps(payload))
            print(f"  {row.district_code} {row.district}: ok")
            break
        time.sleep(pause)


def fetch_synthetic(districts: pd.DataFrame, start: str, end: str, seed: int) -> None:
    """Offline fallback with a realistic monsoon climatology. Marked synthetic=True everywhere."""
    rng = np.random.default_rng(seed)
    days = pd.date_range(start, end, freq="D")
    doy = days.dayofyear.values
    for row in districts.itertuples():
        path = out_path(row.district_code, start, end)
        if path.exists():
            continue
        wet = 0.5 + 0.5 * np.cos(2 * np.pi * (doy - 200) / 365)          # monsoon Jun-Sep
        p_rain = 0.08 + 0.75 * wet ** 2
        amount = rng.gamma(0.8, 4 + 22 * wet)
        rain = np.where(rng.random(len(days)) < p_rain, amount, 0.0) * (1 + 0.3 * (row.lat < 23))
        temp = 26 + 4.5 * np.sin(2 * np.pi * (doy - 80) / 365) - 0.6 * (row.lat - 23) + rng.normal(0, 1.2, len(days))
        rh = np.clip(65 + 20 * wet + rng.normal(0, 5, len(days)), 35, 100)
        payload = {
            "latitude": row.lat, "longitude": row.lon,
            "daily": {
                "time": [d.strftime("%Y-%m-%d") for d in days],
                "precipitation_sum": np.round(rain, 1).tolist(),
                "temperature_2m_mean": np.round(temp, 1).tolist(),
                "relative_humidity_2m_mean": np.round(rh, 0).tolist(),
            },
            "episcope": {"district_code": row.district_code, "source": "synthetic-fallback", "synthetic": True},
        }
        path.write_text(json.dumps(payload))
    print(f"  wrote SYNTHETIC weather for {len(districts)} districts (fallback; replace with real data)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--synthetic", action="store_true", help="offline fallback (flagged synthetic)")
    ap.add_argument("--pause", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    (config.LANDING / "weather").mkdir(parents=True, exist_ok=True)
    districts = pd.read_csv(config.REFERENCE_DIR / "districts.csv")
    if a.synthetic:
        fetch_synthetic(districts, a.start, a.end, a.seed)
        return
    try:
        fetch_real(districts, a.start, a.end, a.pause)
    except Exception as exc:  # network blocked etc.
        print(f"[weather] Open-Meteo download failed ({exc}). Re-run later, or use --synthetic.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
