"""Injected outbreaks and reporting artefacts (ground truth for AN-2 / AN-3).

The ground truth is written to data/ground_truth/ ONLY. Detection code never reads it;
only analytics/detection/evaluate.py does, after the alerts have been produced.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from generator.epi_model import CATS

# Fixed, named events (included only when they fall inside the simulated range)
SPECIAL_EVENTS = [
    # Nationwide novel-respiratory surge that spreads out from Dhaka (also used for SEIR, AN-10)
    dict(kind="novel_respiratory_surge", disease="ili", start="2024-11-24", days=70, mult=4.0),
    # Slow-growing diarrhoeal outbreak (gradual ramp over ~4 months)
    dict(kind="slow_growing", disease="diarrhoea", district="Cox's Bazar", start="2025-01-19", days=119, mult=2.6),
    # Record dengue year in the big cities (cf. 2023 season in Bangladesh)
    dict(kind="dengue_epidemic_2023", disease="dengue", start="2023-06-25", days=140, mult=3.0,
         districts=["Dhaka", "Chattogram", "Narayanganj", "Gazipur", "Cox's Bazar", "Barishal", "Khulna",
                    "Cumilla", "Patuakhali", "Bhola", "Barguna", "Pirojpur", "Chandpur", "Munshiganj"]),
]

# Facility that goes silent for 3 weeks and then back-fills (P4 artefact; AN-3)
ARTEFACTS = [dict(district="Rajshahi", facility_rank=0, silence_start="2024-02-04", silence_days=21)]


def _profile(n: int, kind: str) -> np.ndarray:
    t = np.arange(n) / max(n - 1, 1)
    if kind == "slow_growing":
        up = np.clip(t / 0.85, 0, 1) ** 1.6
        down = np.clip((1 - t) / 0.15, 0, 1)
        return np.minimum(up, down)
    return np.sin(np.pi * t) ** 1.2


def build_outbreaks(rng, districts: pd.DataFrame, days: pd.DatetimeIndex, base_lam: dict, n_local: int):
    """Return (multiplier array [days, districts, cats], ground-truth DataFrame)."""
    n_t, n_d = len(days), len(districts)
    mult = np.ones((n_t, n_d, len(CATS)))
    names = districts["district"].tolist()
    rows = []
    day0 = days[0]

    def add(d_idx, k_idx, start_i, n, m, kind, oid):
        s, e = max(start_i, 0), min(start_i + n, n_t)
        if e <= s:
            return False
        prof = _profile(n, kind)[s - start_i: e - start_i]
        mult[s:e, d_idx, k_idx] *= 1 + (m - 1) * prof
        rows.append(dict(outbreak_id=oid, kind=kind, district_code=districts.iloc[d_idx]["district_code"],
                         district=names[d_idx], disease=CATS[k_idx],
                         start_date=(day0 + pd.Timedelta(days=start_i)).date().isoformat(),
                         end_date=(day0 + pd.Timedelta(days=start_i + n - 1)).date().isoformat(),
                         peak_multiplier=round(m, 2)))
        return True

    # --- special events
    lat0, lon0 = districts.loc[districts.district == "Dhaka", ["lat", "lon"]].iloc[0]
    for i, ev in enumerate(SPECIAL_EVENTS):
        k = CATS.index(ev["disease"])
        start_i = (pd.Timestamp(ev["start"]) - day0).days
        oid = f"SP{i + 1:02d}_{ev['kind']}"
        if ev["kind"] == "novel_respiratory_surge":
            for d in range(n_d):
                dist = float(np.hypot(districts.iloc[d].lat - lat0, districts.iloc[d].lon - lon0))
                lag = int(dist * 9 + rng.integers(0, 7))
                add(d, k, start_i + lag, ev["days"], ev["mult"] * rng.uniform(0.8, 1.2), ev["kind"], oid)
        elif "districts" in ev:
            for name in ev["districts"]:
                d = names.index(name)
                add(d, k, start_i + int(rng.integers(0, 21)), ev["days"], ev["mult"] * rng.uniform(0.7, 1.3),
                    ev["kind"], oid)
        else:
            add(names.index(ev["district"]), k, start_i, ev["days"], ev["mult"], ev["kind"], oid)

    # --- random local outbreaks of different size, duration and location
    disease_p = {"dengue": 0.35, "diarrhoea": 0.35, "ili": 0.15, "malaria": 0.15}
    placed, tries = 0, 0
    min_start = min(70, max(n_t // 4, 0))
    while placed < n_local and tries < 5000:
        tries += 1
        cat = rng.choice(list(disease_p), p=list(disease_p.values()))
        k = CATS.index(cat)
        lam = base_lam[cat]                     # mean daily expected cases per district at SF=1
        ok = np.where(lam * 7 >= 5)[0]           # only where an outbreak is observable at SF=1
        if len(ok) == 0:
            continue
        d = int(rng.choice(ok))
        n = int(rng.integers(14, 57))
        if n_t - n - 1 <= min_start:
            n = max(7, n_t - min_start - 1)
        start_i = int(rng.integers(min_start, max(min_start + 1, n_t - n)))
        # keep outbreaks of the same district/disease apart
        if (mult[max(start_i - 28, 0): start_i + n + 28, d, k] > 1.01).any():
            continue
        if add(d, k, start_i, n, float(rng.uniform(2.0, 5.0)), "local", f"LO{placed + 1:02d}"):
            placed += 1
    return mult, pd.DataFrame(rows)
