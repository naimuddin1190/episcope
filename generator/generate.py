"""Synthetic DHIS2-style feeds S4 (encounters), S5 (facility registry) and S6 (stock/beds).

Deterministic for a given --seed; volume scales with --sf (SF=1 -> >= 25M encounters, 2021-2025).
Output (the "landing zone", in the schema contract of docs/schema.md):

    data/landing/facilities/facility_registry.csv
    data/landing/encounters/encounters_YYYYMMDD.csv       one file per report date (daily feed)
    data/landing/stock/stock_YYYYMMDD.jsonl               one file per snapshot date
    data/ground_truth/ground_truth_outbreaks*.csv         NEVER read by detection code
    data/ground_truth/artefacts*.csv

Examples:
    python -m generator.generate --sf 0.25 --seed 42
    python -m generator.generate --sf 0.25 --seed 43 --start 2026-01-01 --end 2026-01-14 --drop
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd

from common import config
from generator import epi_model as em
from generator.facilities import build_registry
from generator.outbreaks import ARTEFACTS, build_outbreaks

WARMUP_DAYS = 400      # weather lags and day-of-year climatology need history before the first output day
CODES = {
    "dengue": (["A90", "A91"], [0.85, 0.15]),
    "diarrhoea": (["A09", "A00.1", "A00.9"], [0.92, 0.04, 0.04]),
    "ili": (["J11.1", "J10.1"], [0.7, 0.3]),
    "malaria": (["B50.9", "B54", "B51.9"], [0.6, 0.3, 0.1]),
    "other": (["I10", "E11.9", "J18.9", "K29.7", "O80", "S06.0", "R50.9", "N39.0", "L03.9", "Z00.0", "J45.9", "A15.0"],
              [0.14, 0.12, 0.10, 0.10, 0.08, 0.06, 0.12, 0.08, 0.06, 0.06, 0.05, 0.03]),
}
AGE_BANDS = [(0, 4), (5, 14), (15, 24), (25, 44), (45, 64), (65, 95)]
AGE_P = {
    "dengue": [0.05, 0.15, 0.25, 0.35, 0.15, 0.05],
    "diarrhoea": [0.35, 0.15, 0.12, 0.18, 0.12, 0.08],
    "ili": [0.25, 0.25, 0.12, 0.15, 0.13, 0.10],
    "malaria": [0.08, 0.20, 0.22, 0.30, 0.15, 0.05],
    "other": [0.10, 0.12, 0.15, 0.28, 0.22, 0.13],
}
LAB_P = {"dengue": 0.55, "diarrhoea": 0.10, "ili": 0.05, "malaria": 0.80, "other": 0.0}
ADMIT_P = {"dengue": 0.18, "diarrhoea": 0.08, "ili": 0.04, "malaria": 0.15, "other": 0.10}
DEATH_P = {"dengue": 0.006, "diarrhoea": 0.002, "ili": 0.003, "malaria": 0.01, "other": 0.004}
# Public holidays (fixed-date) + approximate Eid holidays: fewer reports on these days
FIXED_HOLIDAYS = ["02-21", "03-26", "04-14", "05-01", "08-15", "12-16"]
EID = ["2021-05-13", "2021-07-21", "2022-05-03", "2022-07-10", "2023-04-22", "2023-06-29", "2024-04-11",
       "2024-06-17", "2025-03-31", "2025-06-07", "2026-03-20", "2026-05-27"]


def load_weather(districts: pd.DataFrame, days: pd.DatetimeIndex):
    files = sorted((config.LANDING / "weather").glob("*.json"))
    if not files:
        raise SystemExit("No weather in data/landing/weather. Run `make weather` (or `make weather-synthetic`).")
    frames = []
    for f in files:
        js = json.loads(f.read_text())
        d = js["daily"]
        frames.append(pd.DataFrame({"district_code": js["episcope"]["district_code"], "date": pd.to_datetime(d["time"]),
                                    "precip": d["precipitation_sum"], "temp": d["temperature_2m_mean"],
                                    "rh": d["relative_humidity_2m_mean"]}))
    w = pd.concat(frames).drop_duplicates(["district_code", "date"], keep="last")
    out = []
    for col in ["precip", "temp", "rh"]:
        p = w.pivot(index="date", columns="district_code", values=col).reindex(columns=districts.district_code)
        p = p.astype(float)
        clim = p.groupby(p.index.dayofyear).mean()           # fill dates outside the downloaded range
        p = p.reindex(days)
        miss = p.isna()
        if miss.values.any():
            fill = clim.reindex(days.dayofyear).set_axis(days)
            p = p.fillna(fill).fillna(p.mean())
        out.append(p.to_numpy())
    synthetic = any(json.loads(f.read_text())["episcope"].get("synthetic") for f in files[:1])
    return out[0], out[1], out[2], synthetic


def holiday_mask(dates: pd.DatetimeIndex) -> np.ndarray:
    md = dates.strftime("%m-%d")
    hol = np.isin(md, FIXED_HOLIDAYS) | np.isin(dates.strftime("%Y-%m-%d"), EID)
    return hol


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sf", type=float, default=0.25)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--outbreaks", type=int, default=None, help="number of random local outbreaks")
    ap.add_argument("--drop", action="store_true", help="incremental drop: keep existing landing files")
    a = ap.parse_args()
    t0 = time.time()
    rng = np.random.default_rng(a.seed)
    start, end = pd.Timestamp(a.start), pd.Timestamp(a.end)
    days = pd.date_range(start - pd.Timedelta(days=WARMUP_DAYS), end, freq="D")
    offset = WARMUP_DAYS
    n_t = len(days)
    districts = pd.read_csv(config.REFERENCE_DIR / "districts.csv")
    n_d = len(districts)
    tag = start.strftime("%Y%m%d")

    enc_dir, stock_dir, fac_dir = (config.LANDING / x for x in ("encounters", "stock", "facilities"))
    if not a.drop:
        for p in (enc_dir, stock_dir, fac_dir, config.GROUND_TRUTH):
            shutil.rmtree(p, ignore_errors=True)
    for p in (enc_dir, stock_dir, fac_dir, config.GROUND_TRUTH):
        p.mkdir(parents=True, exist_ok=True)

    # ---------------- S5 facility registry (fixed seed so a drop sees the same facilities)
    reg_path = fac_dir / "facility_registry.csv"
    registry = build_registry(districts, np.random.default_rng(1000))
    if not reg_path.exists():
        registry.to_csv(reg_path, index=False)

    # ---------------- expected cases
    precip, temp, rh, synthetic_weather = load_weather(districts, days)
    doy = days.dayofyear.to_numpy()
    pop = districts.population.to_numpy(float) / 1e5
    lam = np.zeros((n_t, n_d, len(em.CATS)))
    base_daily = {}
    for k, cat in enumerate(em.CATS):
        sp = em.spatial(cat, districts, rng)
        base_daily[cat] = pop * em.BASE_RATE[cat] * sp
        lam[:, :, k] = (base_daily[cat][None, :] * em.season(cat, doy)[:, None]
                        * em.climate(cat, precip, temp, rh, doy)
                        * em.year_factor(cat, days.year.to_numpy(), rng)[:, None])
    n_local = a.outbreaks if a.outbreaks is not None else max(1, round(30 * (end - start).days / 1825))
    sub_days = days[offset:]
    mult_sub, truth = build_outbreaks(rng, districts, sub_days, base_daily, n_local)
    mult = np.ones_like(lam)
    mult[offset:] = mult_sub
    lam *= mult * a.sf
    counts = np.zeros_like(lam, dtype=np.int64)
    for k, cat in enumerate(em.CATS):
        counts[:, :, k] = em.nb_sample(rng, lam[:, :, k], em.NB_SIZE[cat])
    intensity = mult - 1.0

    # facility sampling weights within each district (big hospitals get more patients -> skew)
    fac_idx_by_d, fac_cum_by_d = [], []
    for code in districts.district_code:
        sub = registry.index[registry.district_code == code].to_numpy()
        w = registry.loc[sub, "beds"].to_numpy(float) ** 0.8 + 5
        fac_idx_by_d.append(sub)
        fac_cum_by_d.append(np.cumsum(w) / w.sum())
    fac_ids = registry.facility_id.to_numpy()
    n_fac = len(registry)

    hol = holiday_mask(pd.date_range(days[0], end + pd.Timedelta(days=40)))
    art = ARTEFACTS[0]
    cand = fac_idx_by_d[districts.index[districts.district == art["district"]][0]]
    art_fac = cand[np.argsort(-registry.loc[cand, "beds"].to_numpy())[art["facility_rank"]]]  # largest hospital
    art_s = pd.Timestamp(art["silence_start"])
    art_e = art_s + pd.Timedelta(days=art["silence_days"] - 1)

    # per facility & day: [dengue cases, dengue admitted, diarrhoea cases, diarrhoea admitted, malaria cases, other adm]
    usage = np.zeros((n_t, n_fac, 6), dtype=np.float32)
    first_onset = offset - config.MAX_DELAY_DAYS     # onsets earlier than this never report in range
    written = 0
    counter = 0
    month_keys = pd.Series(days.to_period("M"))
    for period in month_keys.unique():
        t_idx = np.where((month_keys == period).to_numpy())[0]
        t_idx = t_idx[t_idx >= first_onset]
        if len(t_idx) == 0:
            continue
        c = counts[t_idx]                                  # (t, d, k)
        n = int(c.sum())
        if n == 0:
            continue
        flat = c.reshape(-1)
        cell = np.repeat(np.arange(flat.size), flat)
        ti, di, ki = np.unravel_index(cell, c.shape)
        ti = t_idx[ti]
        inten = intensity[ti, di, ki]

        # facility
        fac = np.empty(n, dtype=np.int64)
        u = rng.random(n)
        for d in range(n_d):
            m = di == d
            if m.any():
                fac[m] = fac_idx_by_d[d][np.minimum(np.searchsorted(fac_cum_by_d[d], u[m]), len(fac_idx_by_d[d]) - 1)]

        # codes, age, sex, severity
        code = np.empty(n, dtype=object)
        age = np.empty(n, dtype=np.int64)
        lab = np.zeros(n, dtype=bool)
        adm = np.zeros(n, dtype=bool)
        died = np.zeros(n, dtype=bool)
        for k, cat in enumerate(em.CATS):
            m = ki == k
            nk = int(m.sum())
            if nk == 0:
                continue
            codes, p = CODES[cat]
            p = np.array(p, float)
            if cat == "diarrhoea":  # more cholera (A00) during diarrhoeal outbreaks
                ch = 0.08 + 0.3 * np.minimum(1, inten[m] / 3)
                code[m] = np.where(rng.random(nk) < ch, rng.choice(["A00.1", "A00.9"], nk), "A09")
            else:
                code[m] = rng.choice(codes, nk, p=p / p.sum())
            band = rng.choice(len(AGE_BANDS), nk, p=AGE_P[cat])
            lo = np.array([b[0] for b in AGE_BANDS])[band]
            hi = np.array([b[1] for b in AGE_BANDS])[band]
            age[m] = lo + (rng.random(nk) * (hi - lo + 1)).astype(int)
            lab[m] = rng.random(nk) < LAB_P[cat]
            ap_ = ADMIT_P[cat] + (0.12 * np.minimum(1, inten[m] / 2) if cat == "dengue" else 0)
            adm[m] = rng.random(nk) < ap_
            died[m] = adm[m] & (rng.random(nk) < DEATH_P[cat] * (1.5 if cat == "dengue" else 1))
        sex = np.where(rng.random(n) < 0.49, "F", "M")
        outcome = np.where(died, "died", np.where(rng.random(n) < 0.04, "referred", "recovered"))
        outcome = np.where(rng.random(n) < 0.01, "unknown", outcome)

        # reporting delay: right-skewed 0-21 days, fewer reports on weekends (Fri/Sat) and holidays
        slow = rng.random(n) < 0.15
        delay = np.where(slow, rng.negative_binomial(2, 2 / (2 + 8.0), n), rng.negative_binomial(2, 2 / (2 + 2.5), n))
        rep = ti + np.clip(delay, 0, config.MAX_DELAY_DAYS)
        for _ in range(3):
            rep_dates = days[0] + pd.to_timedelta(rep, unit="D")
            dow = rep_dates.dayofweek.to_numpy()
            off = ((dow == 4) | (dow == 5) | hol[np.clip(rep, 0, len(hol) - 1)]) & (rng.random(n) < 0.75)
            rep = rep + off.astype(int)
        rep = np.minimum(rep, ti + config.MAX_DELAY_DAYS)
        # artefact: facility silent for 3 weeks, then back-fills everything on one day
        rep_dates = days[0] + pd.to_timedelta(rep, unit="D")
        silent = (fac == art_fac) & (rep_dates >= art_s) & (rep_dates <= art_e)
        rep = np.where(silent, (art_e - days[0]).days + 1, rep)

        # usage for S6 (by onset day)
        for j, (kk, use_adm) in enumerate([(0, False), (0, True), (1, False), (1, True), (3, False), (4, True)]):
            m = (ki == kk) & (adm if use_adm else True)
            np.add.at(usage[:, :, j], (ti[m], fac[m]), 1)

        df = pd.DataFrame({
            "encounter_id": [f"E{tag}-{x:011d}" for x in range(counter, counter + n)],
            "patient_id": rng.integers(1_000_000_000, 9_999_999_999, n).astype(str),
            "facility_id": fac_ids[fac],
            "onset_date": (days[0] + pd.to_timedelta(ti, unit="D")).strftime("%Y-%m-%d"),
            "report_date": (days[0] + pd.to_timedelta(rep, unit="D")).strftime("%Y-%m-%d"),
            "age_years": age.astype(str), "sex": sex, "icd10_code": code,
            "lab_confirmed": np.where(lab, "true", "false"), "admitted": np.where(adm, "true", "false"),
            "outcome": outcome,
        })
        counter += n

        # ~2% resubmitted duplicates (same encounter_id, reported again 1-5 days later)
        dup = df.sample(frac=0.02, random_state=int(rng.integers(1 << 31)))
        dup = dup.assign(report_date=(pd.to_datetime(dup.report_date)
                                      + pd.to_timedelta(rng.integers(1, 6, len(dup)), unit="D")).dt.strftime("%Y-%m-%d"))
        df = pd.concat([df, dup], ignore_index=True)
        # ~0.5% orphan facility keys
        m = rng.random(len(df)) < 0.005
        df.loc[m, "facility_id"] = [f"F9{x:04d}" for x in rng.integers(0, 9999, m.sum())]
        # ~1% invalid values of several kinds
        m = rng.random(len(df)) < 0.01
        kind = rng.integers(0, 6, len(df))
        df.loc[m & (kind == 0), "age_years"] = rng.choice(["212", "-4", "", "abc"], (m & (kind == 0)).sum())
        df.loc[m & (kind == 1), "sex"] = rng.choice(["X", "", "U"], (m & (kind == 1)).sum())
        df.loc[m & (kind == 2), "icd10_code"] = rng.choice(["XX9", "A9O", "", "999"], (m & (kind == 2)).sum())
        sw = m & (kind == 3)  # onset after report
        df.loc[sw, ["onset_date", "report_date"]] = df.loc[sw, ["report_date", "onset_date"]].to_numpy()
        df.loc[m & (kind == 4), "patient_id"] = ""
        df.loc[m & (kind == 5), "onset_date"] = rng.choice(["2023/13/45", "", "N/A"], (m & (kind == 5)).sum())

        # deliver only what is reported inside [start, end]
        rd = df["report_date"]
        keep = (rd >= start.strftime("%Y-%m-%d")) & (rd <= end.strftime("%Y-%m-%d"))
        df = df[keep]
        for rdate, g in df.groupby("report_date", sort=True):
            path = enc_dir / f"encounters_{rdate.replace('-', '')}.csv"
            g.to_csv(path, mode="a", header=not path.exists(), index=False)
        written += len(df)
        print(f"  {period}: {written:,} encounter rows written", flush=True)

    # ---------------- S6 daily stock and bed-occupancy snapshots
    beds = registry.beds.to_numpy(float)

    def consumption(u_):
        return np.stack([4 * u_[..., 1] + 6 * u_[..., 3] + 0.3 * u_[..., 5], 1.3 * u_[..., 0], 4 * u_[..., 2],
                         1.0 * u_[..., 4]], axis=-1)

    # par level ~ 10 days of the facility's AVERAGE consumption (x 0.5-1.3): enough in the low season,
    # short during seasonal peaks and outbreaks -> realistic stock-outs for the optimiser to fix
    mean_daily = consumption(usage[offset:]).mean(axis=0) if n_t > offset else consumption(usage).mean(axis=0)
    par = np.maximum(np.array([5, 2, 10, 1]), 10 * mean_daily * rng.uniform(0.5, 1.3, (n_fac, 1)))
    level = par.copy()
    restock_dow = rng.integers(0, 7, n_fac)
    adm_hist = np.zeros((5, n_fac))
    snap_rng = np.random.default_rng(a.seed + 7)
    for t in range(n_t):
        u_ = usage[t]
        cons = consumption(u_)
        level = np.maximum(0, level - cons)
        restock = (restock_dow == days[t].dayofweek)
        level[restock] = np.maximum(level[restock], par[restock] * snap_rng.uniform(0.6, 1.1, (restock.sum(), 4)))
        adm_hist[t % 5] = u_[:, 1] + u_[:, 3] + u_[:, 5]
        occ = np.minimum(beds, np.round(beds * snap_rng.uniform(0.45, 0.7, n_fac) + adm_hist.sum(0)))
        if t < offset:
            continue
        snap = pd.DataFrame({
            "snapshot_date": days[t].strftime("%Y-%m-%d"), "facility_id": fac_ids,
            "iv_saline": level[:, 0].round().astype(int), "ns1_kits": level[:, 1].round().astype(int),
            "ors": level[:, 2].round().astype(int), "antimalarials": level[:, 3].round().astype(int),
            "occupied_beds": occ.astype(int),
        })
        bad = snap_rng.random(n_fac) < 0.003           # a few defective stock records
        snap.loc[bad, "iv_saline"] = -1
        snap.to_json(stock_dir / f"stock_{days[t].strftime('%Y%m%d')}.jsonl", orient="records", lines=True)

    # ---------------- ground truth (outside the landing zone)
    suffix = "" if not a.drop else f"_drop_{tag}"
    truth.assign(generator_seed=a.seed, sf=a.sf).to_csv(config.GROUND_TRUTH / f"ground_truth_outbreaks{suffix}.csv", index=False)
    if art_s >= start and art_e <= end:
        pd.DataFrame([dict(artefact="facility_silent_then_backfill", facility_id=fac_ids[art_fac], district=art["district"],
                           silence_start=art_s.date().isoformat(), silence_end=art_e.date().isoformat(),
                           backfill_date=(art_e + pd.Timedelta(days=1)).date().isoformat())]
                     ).to_csv(config.GROUND_TRUTH / f"artefacts{suffix}.csv", index=False)
    meta = dict(sf=a.sf, seed=a.seed, start=a.start, end=a.end, encounters=written, facilities=n_fac,
                outbreak_events=int(truth.outbreak_id.nunique()) if len(truth) else 0,
                synthetic_weather=bool(synthetic_weather), seconds=round(time.time() - t0, 1))
    (config.GROUND_TRUTH / f"generator_run{suffix}.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
