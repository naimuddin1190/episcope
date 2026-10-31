"""Weekly 1-6-week-ahead forecasts per district for dengue and diarrhoea (AN-4, AN-5).

Model (deliberately interpretable, conflict C5): one Poisson GLM per district x disease x horizon
("direct" multi-horizon), with features that are all known at the forecast origin:
    log(1+cases) this week and last week, log of the 4-week mean, log(1+cases) in the target week
    one year earlier, seasonal sine/cosine of the target week, rainfall summed over weeks t-3..t
    and t-7..t-4 (so 4-8+ week lags reach the target week), mean temperature over 4 weeks.
Prediction intervals come from a negative-binomial distribution whose dispersion is estimated
from the training residuals.

Per-district models are trained in parallel with Spark (groupBy().applyInPandas).
Backtest: rolling origin over the last 52 mature weeks (model refitted every 4 weeks), compared
against a seasonal-naive baseline (same week last year). Metrics: MAE, 80% PI coverage, WIS
(Bracher et al. 2021).
"""
from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd
from pyspark.sql import functions as F

from common import config
from common.spark import get_spark, register_table

QUANTILES = [0.025, 0.1, 0.25, 0.5, 0.75, 0.9, 0.975]
QCOLS = [f"q{int(q * 1000):03d}" for q in QUANTILES]
HORIZONS = [1, 2, 3, 4, 5, 6]
BACKTEST_WEEKS = 52
REFIT_EVERY = 4

OUT_SCHEMA = ("kind string, district_code string, disease string, origin_week date, target_week date, "
              "horizon int, y_true double, point double, " + ", ".join(f"{c} double" for c in QCOLS) +
              ", baseline double, " + ", ".join(f"b_{c} double" for c in QCOLS))


def features(df: pd.DataFrame, h: int) -> pd.DataFrame:
    y = df["cases"].astype(float)
    X = pd.DataFrame(index=df.index)
    X["ly0"] = np.log1p(y)
    X["ly1"] = np.log1p(y.shift(1))
    X["lm4"] = np.log1p(y.rolling(4).mean())
    X["ly52"] = np.log1p(y.shift(52 - h))                       # target week, one year earlier
    tw = (df["week_start"] + pd.to_timedelta(7 * h, unit="D")).dt.isocalendar().week.astype(float)
    X["sin"] = np.sin(2 * np.pi * tw / 52.18)
    X["cos"] = np.cos(2 * np.pi * tw / 52.18)
    X["rain4"] = np.log1p(df["rain_mm"].rolling(4).sum())
    X["rain8"] = np.log1p(df["rain_mm"].shift(4).rolling(4).sum())
    X["temp4"] = df["temp_c"].rolling(4).mean()
    return X


def nb_quantiles(mu: np.ndarray, size: float) -> np.ndarray:
    from scipy.stats import nbinom
    mu = np.maximum(mu, 1e-6)
    p = size / (size + mu)
    return np.stack([nbinom.ppf(q, size, p) for q in QUANTILES], axis=-1)


class GLM:
    def __init__(self):
        from sklearn.linear_model import PoissonRegressor
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        self.m = make_pipeline(StandardScaler(), PoissonRegressor(alpha=1e-2, max_iter=500))
        self.size = 10.0

    def fit(self, X, y):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.m.fit(X, y)
        mu = self.m.predict(X)
        excess = np.mean((y - mu) ** 2 - mu)
        self.size = float(np.clip(np.mean(mu ** 2) / excess, 0.5, 500)) if excess > 0 else 500.0
        return self

    def predict(self, X):
        return self.m.predict(X)


def run_group(pdf: pd.DataFrame) -> pd.DataFrame:
    pdf = pdf.sort_values("week_start").reset_index(drop=True)
    pdf["week_start"] = pd.to_datetime(pdf["week_start"])
    district, disease = pdf.district_code.iloc[0], pdf.disease.iloc[0]
    # weather may lag behind the case feed (e.g. a new drop before the weather is refreshed):
    # fill missing weeks with that district's average for the same week of the year
    woy = pdf.week_start.dt.isocalendar().week.astype(int)
    for col in ("rain_mm", "temp_c"):
        clim = pdf.groupby(woy)[col].transform("mean")
        pdf[col] = pdf[col].fillna(clim).ffill()
    mature = pdf[pdf.mature].reset_index(drop=True)
    T = len(mature) - 1
    rows = []
    y_all = mature["cases"].to_numpy(float)
    for h in HORIZONS:
        X = features(mature, h)
        target = mature["cases"].shift(-h)
        valid = X.notna().all(axis=1)

        def train(upto: int):
            m = valid & target.notna() & (X.index + h <= upto)
            if m.sum() < 30:
                return None, None
            mdl = GLM().fit(X[m].to_numpy(), target[m].to_numpy())
            # empirical seasonal-naive error distribution for the baseline intervals
            yt, yb = target[m].to_numpy(), np.expm1(X.loc[m, "ly52"].to_numpy())
            return mdl, np.quantile(yt - yb, QUANTILES)

        # rolling-origin backtest: targets in the last 52 mature weeks
        if h <= 4:
            model, berr, fitted_at = None, None, -999
            for tgt in range(T - BACKTEST_WEEKS + 1, T + 1):
                o = tgt - h
                if o < 0 or not valid.iloc[o]:
                    continue
                if model is None or o - fitted_at >= REFIT_EVERY:
                    model, berr = train(o)
                    fitted_at = o
                if model is None:
                    continue
                mu = float(model.predict(X.iloc[[o]].to_numpy())[0])
                qs = nb_quantiles(np.array([mu]), model.size)[0]
                base = float(np.expm1(X["ly52"].iloc[o]))
                bq = np.maximum(base + berr, 0)
                rows.append(["backtest", district, disease, mature.week_start.iloc[o], mature.week_start.iloc[tgt], h,
                             y_all[tgt], mu, *qs, base, *bq])
        # production forecast from the last mature week
        model, berr = train(T)
        if model is not None and valid.iloc[T]:
            mu = float(model.predict(X.iloc[[T]].to_numpy())[0])
            qs = nb_quantiles(np.array([mu]), model.size)[0]
            base = float(np.expm1(X["ly52"].iloc[T]))
            rows.append(["forecast", district, disease, mature.week_start.iloc[T],
                         mature.week_start.iloc[T] + pd.Timedelta(days=7 * h), h, np.nan, mu, *qs, base,
                         *np.maximum(base + berr, 0)])
    out = pd.DataFrame(rows, columns=["kind", "district_code", "disease", "origin_week", "target_week", "horizon",
                                      "y_true", "point", *QCOLS, "baseline", *[f"b_{c}" for c in QCOLS]])
    for c in ("origin_week", "target_week"):
        out[c] = pd.to_datetime(out[c]).dt.date
    return out


def wis(y, q: np.ndarray, median) -> np.ndarray:
    """Weighted interval score for the central 95/80/50% intervals + median."""
    pairs = [(0.05, 0, 6), (0.2, 1, 5), (0.5, 2, 4)]
    total = 0.5 * np.abs(y - median)
    for alpha, lo, hi in pairs:
        l, u = q[:, lo], q[:, hi]
        is_ = (u - l) + 2 / alpha * (l - y) * (y < l) + 2 / alpha * (y - u) * (y > u)
        total = total + alpha / 2 * is_
    return total / (len(pairs) + 0.5)


def metrics(bt: pd.DataFrame) -> pd.DataFrame:
    res = []
    for (dis, h), g in bt.groupby(["disease", "horizon"]):
        y = g.y_true.to_numpy()
        q = g[QCOLS].to_numpy()
        bq = g[[f"b_{c}" for c in QCOLS]].to_numpy()
        res.append(dict(disease=dis, horizon=int(h), n=len(g),
                        mae_model=round(float(np.mean(np.abs(y - g.q500))), 3),
                        mae_seasonal_naive=round(float(np.mean(np.abs(y - g.baseline))), 3),
                        coverage80_model=round(float(np.mean((y >= g.q100) & (y <= g.q900))), 3),
                        coverage80_naive=round(float(np.mean((y >= g.b_q100) & (y <= g.b_q900))), 3),
                        wis_model=round(float(np.mean(wis(y, q, g.q500.to_numpy()))), 3),
                        wis_seasonal_naive=round(float(np.mean(wis(y, bq, g.baseline.to_numpy()))), 3)))
    m = pd.DataFrame(res)
    m["mae_skill_vs_naive"] = (1 - m.mae_model / m.mae_seasonal_naive).round(3)
    m["wis_skill_vs_naive"] = (1 - m.wis_model / m.wis_seasonal_naive).round(3)
    return m


def run() -> None:
    spark = get_spark("episcope-forecast")
    cases = (spark.read.parquet(str(config.GOLD / "weekly_cases"))
             .where(F.col("disease").isin(config.FORECAST_DISEASES))
             .select("district_code", "disease", "week_start", "cases", "mature"))
    wea = spark.read.parquet(str(config.GOLD / "weekly_weather")).select("district_code", "week_start", "rain_mm", "temp_c")
    df = cases.join(wea, ["district_code", "week_start"], "left")
    out = df.groupBy("district_code", "disease").applyInPandas(run_group, OUT_SCHEMA)
    out.write.mode("overwrite").partitionBy("kind").parquet(str(config.GOLD / "forecasts"))
    register_table(spark, "gold", "forecasts", config.GOLD / "forecasts", partitioned=True)
    bt = spark.read.parquet(str(config.GOLD / "forecasts")).where("kind = 'backtest'").toPandas()
    m = metrics(bt)
    (config.GOLD / "evaluation").mkdir(parents=True, exist_ok=True)
    (config.GOLD / "evaluation" / "forecast_backtest.json").write_text(json.dumps(m.to_dict("records"), indent=1))
    m.to_csv(config.EXPERIMENTS / "forecast_backtest_metrics.csv", index=False)
    print(m.to_string(index=False))


if __name__ == "__main__":
    run()
