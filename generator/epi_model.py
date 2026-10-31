"""Epidemiological model behind the synthetic generator (Section 5.2 "Epidemiological realism").

Expected daily cases per district d, disease k and day t:

    lambda[t,d,k] = pop_d/1e5 * base_k * SF * season_k(doy) * spatial_k(d) * climate_k(t,d)
                    * year_k(t) * outbreak[t,d,k]

Observed counts are drawn from a negative-binomial (Poisson-gamma) distribution, not Poisson.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

CATS = ["dengue", "diarrhoea", "ili", "malaria", "other"]

# cases per 100,000 population per day at SF=1 (calibrated so SF=1 gives >= 25M encounters)
BASE_RATE = {"dengue": 0.20, "diarrhoea": 2.4, "ili": 1.6, "malaria": 1.0, "other": 4.6}
NB_SIZE = {"dengue": 4.0, "diarrhoea": 8.0, "ili": 6.0, "malaria": 3.0, "other": 25.0}  # overdispersion

YEAR_FACTOR = {
    "dengue": {2021: 0.7, 2022: 1.3, 2023: 1.0, 2024: 1.4, 2025: 1.1},
}


def von_mises(doy: np.ndarray, peak: float, kappa: float) -> np.ndarray:
    x = np.exp(kappa * np.cos(2 * np.pi * (doy - peak) / 365.25))
    return x / np.i0(kappa)  # mean 1 over the year


def season(cat: str, doy: np.ndarray) -> np.ndarray:
    if cat == "dengue":      # monsoon / post-monsoon peak (Aug-Oct)
        return von_mises(doy, 255, 2.2)
    if cat == "diarrhoea":   # pre-monsoon peak (Apr-May) + smaller post-monsoon peak
        return 0.65 * von_mises(doy, 110, 1.5) + 0.35 * von_mises(doy, 265, 1.2)
    if cat == "ili":         # rainy-season peak + small winter peak
        return 0.7 * von_mises(doy, 200, 1.6) + 0.3 * von_mises(doy, 20, 1.5)
    if cat == "malaria":     # May-Oct transmission season
        return von_mises(doy, 200, 1.4)
    return np.ones_like(doy, dtype=float)


def spatial(cat: str, districts: pd.DataFrame, rng: np.random.Generator) -> np.ndarray:
    u = districts["urban_index"].to_numpy(float)
    pop = districts["population"].to_numpy(float)
    if cat == "dengue":       # concentrated in large cities
        f = (0.15 + u) ** 1.6
    elif cat == "diarrhoea":
        f = (0.8 + 0.4 * u) * rng.lognormal(0, 0.2, len(u))
    elif cat == "ili":
        f = 0.9 + 0.3 * u
    elif cat == "malaria":    # Chittagong Hill Tracts dominate
        zone = districts["malaria_zone"].map({"high": 1.0, "low": 0.03, "none": 0.001}).to_numpy(float)
        return zone
    else:
        return np.ones(len(u))
    return f / np.average(f, weights=pop)  # population-weighted mean of 1


def _doy_climatology(values: np.ndarray, doy: np.ndarray, window: int = 31) -> np.ndarray:
    """Per-district smoothed day-of-year climatology, returned aligned to the input days."""
    n_d = values.shape[1]
    clim = np.zeros((367, n_d))
    for k in range(1, 367):
        m = doy == k
        clim[k] = values[m].mean(axis=0) if m.any() else np.nan
    clim[366] = np.where(np.isnan(clim[366]), clim[365], clim[366])
    core = clim[1:366]
    core = np.where(np.isnan(core), np.nanmean(values, axis=0), core)   # short series: fill gaps
    pad = np.concatenate([core[-window:], core, core[:window]])
    kern = np.ones(window) / window
    smooth = np.stack([np.convolve(pad[:, j], kern, mode="same") for j in range(n_d)], axis=1)[window:-window]
    out = np.concatenate([[smooth[0]], smooth, [smooth[-1]]])
    return out[np.clip(doy, 1, 366)]


def rolling_sum(x: np.ndarray, window: int, lag: int) -> np.ndarray:
    """Sum of x over days [t-lag-window+1, t-lag] along axis 0 (zeros before the series start)."""
    c = np.vstack([np.zeros((1, x.shape[1])), np.cumsum(x, axis=0)])
    t = np.arange(x.shape[0])
    hi = np.clip(t - lag + 1, 0, x.shape[0])
    lo = np.clip(t - lag - window + 1, 0, x.shape[0])
    return c[hi] - c[lo]


def climate(cat: str, precip: np.ndarray, temp: np.ndarray, rh: np.ndarray, doy: np.ndarray) -> np.ndarray:
    """Multiplicative climate effect driven by real (S3) weather, shape (days, districts)."""
    if cat == "dengue":
        # rainfall 4-8 weeks earlier, relative to normal for that time of year
        r = rolling_sum(precip, 28, 28)
        r_clim = _doy_climatology(r, doy)
        rain_f = np.clip(((r + 20) / (r_clim + 20)) ** 0.8, 0.4, 2.5)
        t = rolling_sum(temp, 28, 21) / 28
        t_clim = _doy_climatology(t, doy)
        temp_f = np.clip(np.exp(0.15 * (t - t_clim)), 0.6, 1.6)
        return rain_f * temp_f
    if cat == "diarrhoea":
        # spikes 2-10 days after extreme rainfall (above the district's 97th percentile)
        p97 = np.percentile(precip, 97, axis=0)
        extreme = np.where(precip > p97, precip / np.maximum(p97, 1), 0.0)
        kern = np.array([0, 0, 0.5, 1, 1, 0.8, 0.6, 0.4, 0.3, 0.2, 0.1])
        conv = np.stack([np.convolve(extreme[:, j], kern)[: len(extreme)] for j in range(extreme.shape[1])], axis=1)
        return 1 + 0.35 * conv
    if cat == "ili":
        h_clim = _doy_climatology(rh, doy)
        return np.clip(1 + 0.02 * (rh - h_clim), 0.8, 1.3)
    if cat == "malaria":
        r = rolling_sum(precip, 28, 14)
        r_clim = _doy_climatology(r, doy)
        return np.clip(((r + 20) / (r_clim + 20)) ** 0.5, 0.5, 2.0)
    return np.ones_like(precip)


def year_factor(cat: str, years: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    table = YEAR_FACTOR.get(cat)
    uniq = np.unique(years)
    if table is None:
        rnd = {y: float(np.exp(rng.normal(0, 0.08))) for y in uniq}
        return np.array([rnd[y] for y in years])
    return np.array([table.get(int(y), 1.0) for y in years])


def nb_sample(rng: np.random.Generator, lam: np.ndarray, size: float) -> np.ndarray:
    """Negative binomial with mean lam and size (dispersion) parameter."""
    lam = np.maximum(lam, 1e-9)
    p = size / (size + lam)
    return rng.negative_binomial(size, p)
