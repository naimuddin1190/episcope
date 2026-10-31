"""Seasonal preparedness calendar for the next year (AN-9).

For every division x disease the weekly series (mature weeks, summed over districts) is decomposed
with STL (period 52, robust). From the seasonal component we derive:
  * peak week          week with the largest seasonal effect
  * season start       first week of the above-average run that contains the peak
  * pre-position       supplies 4 weeks before season start
  * prevention         campaigns 6 weeks before season start (larval control, WASH, ...)
The decomposition runs per group in parallel with Spark (applyInPandas).
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from pyspark.sql import functions as F

from common import config
from common.spark import get_spark, register_table

ACTIONS = {
    "dengue": "Larval-source reduction, fogging plan, NS1 kits and IV saline to hospitals",
    "diarrhoea": "WASH and safe-water campaign, ORS and IV saline pre-positioning, cholera RDTs",
    "ili": "Infection prevention in hospitals, oxygen and PPE check, vaccination of risk groups",
    "malaria": "Bed-net distribution and indoor spraying, antimalarials and RDTs to hill districts",
}
SUPPLY_LEAD_WEEKS = 4
CAMPAIGN_LEAD_WEEKS = 6
SCHEMA = ("division string, disease string, epi_week int, seasonal double, level double, peak_week int, "
          "season_start_week int, season_end_week int, amplitude double")


def decompose(pdf: pd.DataFrame) -> pd.DataFrame:
    from statsmodels.tsa.seasonal import STL
    pdf = pdf.sort_values("week_start")
    y = pdf["cases"].astype(float).to_numpy()
    div, dis = pdf.division.iloc[0], pdf.disease.iloc[0]
    if len(y) < 104 or y.sum() == 0:
        return pd.DataFrame(columns=SCHEMA_COLS)
    res = STL(np.log1p(y), period=52, robust=True).fit()
    s = pd.DataFrame({"wk": pd.to_datetime(pdf.week_start).dt.isocalendar().week.clip(upper=52).to_numpy(),
                      "seasonal": res.seasonal})
    prof = s.groupby("wk").seasonal.mean().reindex(range(1, 53)).interpolate().bfill().ffill()
    sm = np.convolve(np.concatenate([prof.values[-2:], prof.values, prof.values[:2]]), np.ones(5) / 5, "valid")
    peak = int(np.argmax(sm)) + 1
    above = sm > 0
    start = peak
    for _ in range(52):  # walk backwards (cyclically) while above average
        prev = (start - 2) % 52 + 1
        if not above[prev - 1] or prev == peak:
            break
        start = prev
    end = peak
    for _ in range(52):
        nxt = end % 52 + 1
        if not above[nxt - 1] or nxt == start:
            break
        end = nxt
    level = float(np.expm1(np.mean(res.trend[-52:])))
    amp = float(np.expm1(sm.max()) - np.expm1(sm.min()))
    return pd.DataFrame({"division": div, "disease": dis, "epi_week": np.arange(1, 53), "seasonal": sm,
                         "level": level, "peak_week": peak, "season_start_week": start, "season_end_week": end,
                         "amplitude": amp})


SCHEMA_COLS = [c.split()[0] for c in SCHEMA.split(", ")]


def iso_monday(year: int, week: int) -> pd.Timestamp:
    return pd.Timestamp.fromisocalendar(year, week, 1)


def run() -> None:
    spark = get_spark("episcope-calendar")
    wk = (spark.read.parquet(str(config.GOLD / "weekly_cases")).where("mature")
          .groupBy("division", "disease", "week_start").agg(F.sum("cases").alias("cases")))
    prof = wk.groupBy("division", "disease").applyInPandas(decompose, SCHEMA).toPandas()
    meta = json.loads((config.META / "gold_meta.json").read_text())
    year = pd.Timestamp(meta["data_cutoff"]).year + 1
    rows = []
    for (div, dis), g in prof.groupby(["division", "disease"]):
        r = g.iloc[0]
        start_w = int(r.season_start_week)
        start = iso_monday(year, start_w)
        rows.append(dict(division=div, disease=dis, year=year, peak_week=int(r.peak_week),
                         peak_date=str(iso_monday(year, int(r.peak_week)).date()),
                         season_start_week=start_w, season_start=str(start.date()),
                         season_end=str((iso_monday(year, int(r.season_end_week)) + pd.Timedelta(days=6)).date()),
                         preposition_supplies_by=str((start - pd.Timedelta(weeks=SUPPLY_LEAD_WEEKS)).date()),
                         start_prevention_campaign=str((start - pd.Timedelta(weeks=CAMPAIGN_LEAD_WEEKS)).date()),
                         seasonal_amplitude=round(float(r.amplitude), 3), typical_weekly_cases=round(float(r.level), 1),
                         reliable=bool(r.level >= 1.0),  # too few cases -> seasonal pattern not trustworthy
                         recommended_actions=ACTIONS[dis]))
    cal = pd.DataFrame(rows).sort_values(["disease", "division"])
    cal.to_parquet(config.GOLD / "preparedness_calendar.parquet", index=False)
    prof.to_parquet(config.GOLD / "seasonal_profiles.parquet", index=False)
    print(cal[["division", "disease", "season_start", "peak_date", "preposition_supplies_by"]].to_string(index=False))


if __name__ == "__main__":
    run()
