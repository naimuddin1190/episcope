"""Outbreak detection per district and disease (AN-1, AN-3).

Two established methods, both run at scale in Spark:

  1. EARS C2 (Hutwagner et al. 2003) with Spark window functions.
     baseline = mean/sd of weeks t-9..t-3 (7 weeks, 2-week guard band);
     C2 = (x_t - mean) / max(sd, sqrt(mean), 1)
  2. Historical limits / Farrington-style seasonal baseline with grouped applyInPandas.
     baseline = same week +-2 in each previous year (up to 3 years), scaled by recent level;
     z = (x_t - mean) / max(sd, sqrt(mean), 1)

Reporting delay (P4): weeks that are not yet "mature" are nowcast, i.e. inflated by the share
of cases that historically has been reported by now (from gold.delay_distribution).
Reporting artefact (P4): detection uses ONSET weeks, so a facility that back-fills three weeks of
reports on one day does not create a spike. evaluate.py compares this with a naive detector on
report weeks.

The ground-truth outbreak file is never read here.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from pyspark.sql import Window
from pyspark.sql import functions as F

from common import config
from common.spark import get_spark, register_table

SETTINGS = config.GOLD / "detection_settings.json"
DEFAULT = {"method": "ears_c2", "threshold": 3.0, "min_cases": 5, "max_cases_floor": 3}


def settings() -> dict:
    """Operating point; evaluate.py writes the recommended one after the trade-off analysis (C1)."""
    if SETTINGS.exists():
        return {**DEFAULT, **json.loads(SETTINGS.read_text())}
    return dict(DEFAULT)


def ears_c2(df, value_col: str = "x"):
    w = Window.partitionBy("district_code", "disease").orderBy("week_start").rowsBetween(-9, -3)
    mu = F.avg(value_col).over(w)
    sd = F.stddev_samp(value_col).over(w)
    n = F.count(value_col).over(w)
    sigma = F.greatest(F.coalesce(sd, F.lit(0.0)), F.sqrt(mu), F.lit(1.0))
    return (df.withColumn("ears_expected", mu)
              .withColumn("ears_sigma", sigma)
              .withColumn("ears_stat", F.when(n >= 5, (F.col(value_col) - mu) / sigma)))


def historical_limits(pdf: pd.DataFrame) -> pd.DataFrame:
    """Seasonal baseline for one district x disease series (runs inside applyInPandas)."""
    pdf = pdf.sort_values("week_start").reset_index(drop=True)
    x = pdf["x"].to_numpy(float)
    n = len(x)
    exp = np.full(n, np.nan)
    sig = np.full(n, np.nan)
    for t in range(n):
        hist = []
        for lag in (52, 104, 156):
            lo, hi = t - lag - 2, t - lag + 3
            if lo >= 0:
                hist.append(x[lo:hi])
        if len(hist) == 0:
            continue
        h = np.concatenate(hist)
        # scale the seasonal baseline to the recent level (weeks t-12..t-5 vs the same weeks in history)
        rec = x[max(t - 12, 0): max(t - 4, 0)]
        rec_hist = np.concatenate([x[max(t - lag - 12, 0): max(t - lag - 4, 0)] for lag in (52, 104, 156)
                                   if t - lag - 12 >= 0] or [np.array([])])
        scale = 1.0
        if len(rec) and len(rec_hist) and rec_hist.mean() > 0:
            scale = float(np.clip((rec.mean() + 1) / (rec_hist.mean() + 1), 0.5, 1.3))
        mu = h.mean() * scale
        exp[t] = mu
        sig[t] = max(h.std(ddof=1) * scale if len(h) > 1 else 0.0, np.sqrt(mu), 1.0)
    pdf["hl_expected"] = exp
    pdf["hl_sigma"] = sig
    pdf["hl_stat"] = (x - exp) / sig
    return pdf[["district_code", "disease", "week_start", "hl_expected", "hl_sigma", "hl_stat"]]


def nowcast_factors(spark, cutoff) -> pd.DataFrame:
    """P(reported within d days | disease) from the empirical delay distribution."""
    dd = spark.read.parquet(str(config.GOLD / "delay_distribution")).groupBy("disease", "delay_days").agg(
        F.sum("n").alias("n")).toPandas()
    out = []
    for dis, g in dd.groupby("disease"):
        g = g.sort_values("delay_days")
        cum = g.n.cumsum() / g.n.sum()
        out += [dict(disease=dis, delay_days=int(d), reported_share=float(c)) for d, c in zip(g.delay_days, cum)]
    return pd.DataFrame(out)


def signals(spark, table: str = "weekly_cases", nowcast: bool = True):
    """Return a Spark DataFrame of detection statistics for a gold weekly table."""
    meta = json.loads((config.META / "gold_meta.json").read_text())
    cutoff = meta["data_cutoff"]
    df = spark.read.parquet(str(config.GOLD / table)).select("district_code", "disease", "week_start", "cases",
                                                              *(["mature"] if table == "weekly_cases" else []))
    if table != "weekly_cases":
        df = df.withColumn("mature", F.date_add("week_start", 6) <= F.date_sub(F.lit(cutoff), config.MATURITY_DAYS))
    if nowcast:
        nc = spark.createDataFrame(nowcast_factors(spark, cutoff))
        # days between mid-week and the cutoff: how much of this week can have been reported yet
        df = df.withColumn("delay_days", F.least(F.datediff(F.lit(cutoff), F.date_add("week_start", 3)), F.lit(60)))
        df = (df.join(F.broadcast(nc), ["disease", "delay_days"], "left")
                .withColumn("reported_share", F.when(F.col("mature"), 1.0)
                            .otherwise(F.greatest(F.coalesce("reported_share", F.lit(1.0)), F.lit(0.2))))
                .withColumn("x", F.col("cases") / F.col("reported_share")).drop("delay_days"))
    else:
        df = df.withColumn("reported_share", F.lit(1.0)).withColumn("x", F.col("cases").cast("double"))
    df = ears_c2(df)
    hl = df.select("district_code", "disease", "week_start", "x").groupBy("district_code", "disease").applyInPandas(
        historical_limits, "district_code string, disease string, week_start date, hl_expected double, "
                           "hl_sigma double, hl_stat double")
    return df.join(hl, ["district_code", "disease", "week_start"], "left")


def run() -> None:
    spark = get_spark("episcope-detection")
    st = settings()
    out = signals(spark, "weekly_cases", nowcast=True)
    stat = "ears_stat" if st["method"] == "ears_c2" else "hl_stat"
    out = (out.withColumn("alert", F.coalesce((F.col(stat) > st["threshold"]) & (F.col("x") >= st["min_cases"]),
                                              F.lit(False)))
              .withColumn("method", F.lit(st["method"])).withColumn("threshold", F.lit(st["threshold"])))
    out.write.mode("overwrite").parquet(str(config.GOLD / "detection_signals"))
    naive = signals(spark, "weekly_by_report", nowcast=False)
    naive.write.mode("overwrite").parquet(str(config.GOLD / "detection_signals_naive"))
    register_table(spark, "gold", "detection_signals", config.GOLD / "detection_signals")
    n = spark.read.parquet(str(config.GOLD / "detection_signals")).where("alert").count()
    print(f"[detection] method={st['method']} threshold={st['threshold']}: {n} alert district-weeks")


if __name__ == "__main__":
    run()
