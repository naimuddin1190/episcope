"""Gold layer: epi-week marts and features (ING-3, ING-4, DQ-3).

Only the epi-years touched by new or late records are recomputed (partition pruning on the
silver `epi_year` partition + dynamic partition overwrite), so a late record (up to 21 days)
updates exactly the affected weeks' year partition and nothing else.

Tables (all Parquet, registered as episcope_gold.*):
  weekly_cases          district x disease x ISO week (zeros filled), incidence, completeness, lineage
  weekly_by_report      same counts by REPORT week (used only to show the naive-detector artefact, AN-3)
  delay_distribution    disease x delay_days counts (nowcasting of incomplete recent weeks)
  weekly_weather        district x week rainfall / temperature / humidity
  stock_latest          latest stock and bed occupancy per district
  batches               lineage: bronze batch -> files -> checksums -> rows
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd
from pyspark.sql import functions as F

from common import config
from common.spark import get_spark, register_table
from common.timing import stage
from pipeline.bronze.ingest import read_manifest
from pipeline.silver.transform import load_state, save_state

DISEASES = config.DISEASES


def run() -> None:
    spark = get_spark("episcope-gold")
    state = load_state()
    pending = state.get("pending_gold_years", [])
    if not pending:
        print("[gold] nothing to rebuild")
        return
    enc_all = spark.read.parquet(str(config.SILVER / "encounters"))
    all_years = sorted(r[0] for r in enc_all.select("epi_year").distinct().collect())
    years = all_years if "__all__" in pending else sorted(int(y) for y in pending)
    print(f"[gold] rebuilding epi-years {years}")

    cutoff = enc_all.agg(F.max("report_date")).first()[0]
    mature_before = F.date_sub(F.lit(cutoff), config.MATURITY_DAYS)

    # cross-batch de-duplication of resubmitted records (keep one copy of each encounter_id)
    enc = enc_all.where(F.col("epi_year").isin(years)).dropDuplicates(["encounter_id"]).cache()

    dist = spark.read.parquet(str(config.SILVER / "districts"))
    fac = spark.read.parquet(str(config.SILVER / "facilities"))
    n_fac = fac.groupBy("district_code").agg(F.count("*").alias("registered_facilities"))

    # complete grid of weeks x districts x diseases (zeros are information too)
    wk = enc.select("week_start", "epi_year", "epi_week").distinct().where(F.col("week_start") <= F.lit(cutoff))
    grid = (wk.crossJoin(dist.select("district_code", "district", "division", "population"))
              .crossJoin(spark.createDataFrame([(d,) for d in DISEASES], ["disease"])))

    cases = (enc.where(F.col("disease") != "other")
             .groupBy("district_code", "disease", "week_start")
             .agg(F.count("*").alias("cases"),
                  F.sum(F.col("admitted").cast("int")).alias("admitted"),
                  F.sum(F.col("lab_confirmed").cast("int")).alias("lab_confirmed"),
                  F.sum((F.col("outcome") == "died").cast("int")).alias("deaths"),
                  F.array_sort(F.collect_set("batch_id")).alias("bronze_batch_ids")))
    completeness = (enc.groupBy("district_code", "week_start")
                    .agg(F.countDistinct("facility_id").alias("reporting_facilities")))
    weekly = (grid.join(cases, ["district_code", "disease", "week_start"], "left")
                  .join(completeness, ["district_code", "week_start"], "left")
                  .join(n_fac, "district_code", "left")
                  .fillna(0, ["cases", "admitted", "lab_confirmed", "deaths", "reporting_facilities"])
                  .withColumn("bronze_batch_ids", F.coalesce("bronze_batch_ids", F.array().cast("array<string>")))
                  .withColumn("incidence_per_100k", F.round(F.col("cases") / F.col("population") * 1e5, 3))
                  .withColumn("completeness", F.round(F.col("reporting_facilities") / F.col("registered_facilities"), 3))
                  .withColumn("mature", F.date_add("week_start", 6) <= mature_before)
                  .select("district_code", "district", "division", "disease", "week_start", "epi_week", "cases",
                          "admitted", "lab_confirmed", "deaths", "population", "incidence_per_100k",
                          "reporting_facilities", "registered_facilities", "completeness", "mature",
                          "bronze_batch_ids", "epi_year"))
    weekly.write.mode("overwrite").partitionBy("epi_year").parquet(str(config.GOLD / "weekly_cases"))

    # naive view: counts by report week (what a spreadsheet of "reports received" would show)
    by_report = (enc_all.where(F.col("report_epi_year").isin(years)).dropDuplicates(["encounter_id"])
                 .where(F.col("disease") != "other")
                 .groupBy("district_code", "disease", "report_week_start", "report_epi_year")
                 .agg(F.count("*").alias("cases"))
                 .withColumnRenamed("report_week_start", "week_start").withColumnRenamed("report_epi_year", "epi_year"))
    by_report.write.mode("overwrite").partitionBy("epi_year").parquet(str(config.GOLD / "weekly_by_report"))

    delays = (enc.where(F.col("disease") != "other").groupBy("disease", "delay_days", "epi_year")
              .agg(F.count("*").alias("n")))
    delays.write.mode("overwrite").partitionBy("epi_year").parquet(str(config.GOLD / "delay_distribution"))
    enc.unpersist()

    # small, fully rebuilt tables
    wea = (spark.read.parquet(str(config.SILVER / "weather"))
           .withColumn("week_start", F.date_trunc("week", "date").cast("date"))
           .groupBy("district_code", "week_start")
           .agg(F.round(F.sum("precip_mm"), 1).alias("rain_mm"), F.round(F.avg("temp_c"), 2).alias("temp_c"),
                F.round(F.avg("rh_pct"), 1).alias("rh_pct"), F.first("weather_source").alias("weather_source")))
    wea.write.mode("overwrite").parquet(str(config.GOLD / "weekly_weather"))

    if (config.SILVER / "stock").exists():
        st = spark.read.parquet(str(config.SILVER / "stock")).dropDuplicates(["facility_id", "snapshot_date"])
        last = st.groupBy("facility_id").agg(F.max("snapshot_date").alias("snapshot_date"))
        latest = (st.join(last, ["facility_id", "snapshot_date"])
                  .join(fac.select("facility_id", "beds", "icu_beds"), "facility_id")
                  .groupBy("district_code")
                  .agg(F.max("snapshot_date").alias("snapshot_date"),
                       *[F.sum(c).alias(c) for c in ["iv_saline", "ns1_kits", "ors", "antimalarials",
                                                      "occupied_beds", "beds", "icu_beds"]]))
        latest.write.mode("overwrite").parquet(str(config.GOLD / "stock_latest"))
        register_table(spark, "gold", "stock_latest", config.GOLD / "stock_latest")

    man = read_manifest()
    spark.createDataFrame(man.astype(str)).write.mode("overwrite").parquet(str(config.GOLD / "batches"))

    for t, part in (("weekly_cases", True), ("weekly_by_report", True), ("delay_distribution", True),
                    ("weekly_weather", False), ("batches", False), ("dq_report", True)):
        register_table(spark, "gold", t, config.GOLD / t, partitioned=part)

    meta = dict(data_cutoff=str(cutoff), built_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                rebuilt_years=[int(y) for y in years])
    (config.META / "gold_meta.json").write_text(json.dumps(meta, indent=1))
    state["pending_gold_years"] = []
    save_state(state)
    print(f"[gold] done; data cutoff {cutoff}")


if __name__ == "__main__":
    with stage("gold_build"):
        run()
