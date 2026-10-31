"""S5: synthetic facility registry (>= 600 facilities: hospitals, upazila health complexes, clinics)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def build_registry(districts: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for d in districts.itertuples():
        num = d.district_code[2:]
        seq = 0

        def add(ftype, beds, icu):
            nonlocal seq
            seq += 1
            rows.append(dict(
                facility_id=f"F{num}{seq:03d}", facility_name=f"{d.district} {ftype.replace('_', ' ').title()} {seq}",
                facility_type=ftype, district_code=d.district_code, district=d.district, division=d.division,
                lat=round(d.lat + rng.normal(0, 0.08), 5), lon=round(d.lon + rng.normal(0, 0.08), 5),
                beds=int(beds), icu_beds=int(icu)))

        add("district_hospital", rng.integers(100, 260), rng.integers(4, 12))
        n_mch = 4 if d.district == "Dhaka" else (2 if d.urban_index >= 0.45 else 0)
        for _ in range(n_mch):
            add("medical_college_hospital", rng.integers(500, 2200), rng.integers(10, 60))
        for _ in range(max(3, round(d.population / 330_000))):
            add("upazila_health_complex", rng.choice([31, 50]), 0)
        for _ in range(1 + round(d.population / 900_000 * (1 + 2 * d.urban_index))):
            add("clinic", rng.integers(10, 60), rng.integers(0, 3))
    reg = pd.DataFrame(rows)
    assert len(reg) >= 600, len(reg)
    return reg
