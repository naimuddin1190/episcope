"""Silver layer: clean, conformed, de-identified (DQ-1, DQ-2, PRV-1, ING-3, ING-4).

For every bronze batch not yet processed:
  * apply the quality rules; failing rows go to silver/quarantine with a reason code
  * de-identify: patient_id -> salted SHA-256 (salt from .env, never in the repo); age -> age band;
    the raw identifiers never leave bronze
  * conform: join the facility registry (broadcast join, ENG-3), map ICD-10 -> disease group,
    compute epi week (ISO week, Monday start)
  * write Parquet partitioned by (epi_year, batch_id); dynamic overwrite makes re-runs idempotent
  * write one data-quality report per batch (gold/dq_report)
"""
from __future__ import annotations

import json

import pandas as pd
from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from common import config
from common.spark import get_spark, register_table
from common.timing import stage
from pipeline.bronze.ingest import read_manifest
from pipeline.quality import rules

STATE = config.META / "silver_state.json"


def load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {"processed": [], "pending_gold_years": []}


def save_state(s: dict) -> None:
    STATE.write_text(json.dumps(s, indent=1))


def disease_of(code: F.Column) -> F.Column:
    return (F.when(code.rlike(r"^A9[01]"), "dengue")
             .when(code.rlike(r"^A0[09]"), "diarrhoea")
             .when(code.rlike(r"^J1[01]"), "ili")
             .when(code.rlike(r"^B5[0-4]"), "malaria")
             .otherwise("other"))


def age_band(age: F.Column) -> F.Column:
    return (F.when(age < 5, "00-04").when(age < 15, "05-14").when(age < 25, "15-24")
             .when(age < 45, "25-44").when(age < 65, "45-64").otherwise("65+"))


def with_epiweek(df: DataFrame, date_col: str, prefix: str = "") -> DataFrame:
    ws = F.date_trunc("week", F.col(date_col)).cast("date")           # Monday of the ISO week
    return (df.withColumn(f"{prefix}week_start", ws)
              .withColumn(f"{prefix}epi_year", F.year(F.date_add(ws, 3)))  # ISO year = year of Thursday
              .withColumn(f"{prefix}epi_week", F.weekofyear(ws)))


def refresh_reference(spark: SparkSession) -> DataFrame:
    """Facilities, districts, population, weather: small tables, rebuilt from all bronze batches."""
    w = Window.partitionBy("facility_id").orderBy(F.col("_load_ts").desc())
    fac = (spark.read.parquet(str(config.BRONZE / "facilities"))
           .withColumn("_r", F.row_number().over(w)).where("_r = 1").drop("_r")
           .select("facility_id", "facility_name", "facility_type", "district_code", "district", "division",
                   F.col("lat").cast("double").alias("lat"), F.col("lon").cast("double").alias("lon"),
                   F.col("beds").cast("int").alias("beds"), F.col("icu_beds").cast("int").alias("icu_beds"),
                   "batch_id"))
    fac.write.mode("overwrite").parquet(str(config.SILVER / "facilities"))
    register_table(spark, "silver", "facilities", config.SILVER / "facilities")

    latest = lambda src: spark.read.parquet(str(config.BRONZE / src)).where(
        F.col("batch_id") == spark.read.parquet(str(config.BRONZE / src)).agg(F.max("batch_id")).first()[0])
    dist = latest("districts").select("district_code", "district", "division",
                                      F.col("lat").cast("double").alias("lat"), F.col("lon").cast("double").alias("lon"),
                                      F.col("population").cast("long").alias("population"), "malaria_zone",
                                      F.col("urban_index").cast("double").alias("urban_index"))
    dist.write.mode("overwrite").parquet(str(config.SILVER / "districts"))
    pop = latest("population").select("district_code", "age_band", "sex", F.col("population").cast("long").alias("population"))
    pop.write.mode("overwrite").parquet(str(config.SILVER / "population"))

    ww = Window.partitionBy("district_code", "date").orderBy(F.col("_load_ts").desc())
    wea = (spark.read.parquet(str(config.BRONZE / "weather"))
           .withColumn("_r", F.row_number().over(ww)).where("_r = 1")
           .select("district_code", F.to_date("date").alias("date"),
                   F.col("precipitation_sum").cast("double").alias("precip_mm"),
                   F.col("temperature_2m_mean").cast("double").alias("temp_c"),
                   F.col("relative_humidity_2m_mean").cast("double").alias("rh_pct"), "weather_source"))
    wea.write.mode("overwrite").parquet(str(config.SILVER / "weather"))
    for t in ("districts", "population", "weather"):
        register_table(spark, "silver", t, config.SILVER / t)
    return fac


def quality_report(df: DataFrame, rule_list, source: str, batch_id: str) -> pd.DataFrame:
    aggs = [F.count("*").alias("rows_in"), F.sum(F.when(F.size("_violations") == 0, 1).otherwise(0)).alias("rows_valid")]
    aggs += [F.sum(F.when(F.array_contains("_violations", code), 1).otherwise(0)).alias(code) for code, _, _ in rule_list]
    r = df.agg(*aggs).first().asDict()
    rows_in = r["rows_in"] or 0
    out = []
    for code, desc, _ in rule_list:
        failed = r[code] or 0
        out.append(dict(batch_id=batch_id, source=source, rule_code=code, description=desc, rows_in=rows_in,
                        rows_valid=r["rows_valid"] or 0, rows_quarantined=rows_in - (r["rows_valid"] or 0),
                        failed=failed, pass_rate=round(1 - failed / rows_in, 6) if rows_in else 1.0))
    return pd.DataFrame(out)


def process_encounters(spark, batch_id: str, fac: DataFrame, salt: str) -> tuple[pd.DataFrame, list[int]]:
    raw = spark.read.parquet(str(config.BRONZE / "encounters")).where(F.col("batch_id") == batch_id)
    load_date = F.to_date(F.col("_load_ts"))
    fac_small = fac.select(F.col("facility_id").alias("_fid"), F.lit(1).alias("_fac_known"),
                           "district_code", "district", "division", "facility_type")
    dup_w = Window.partitionBy("encounter_id").orderBy(F.col("report_date").desc(), F.col("_file_name").desc())
    df = (raw.join(F.broadcast(fac_small), raw.facility_id == F.col("_fid"), "left")
             .withColumn("_dup_rank", F.row_number().over(dup_w)))
    rule_list = rules.encounter_rules(load_date)
    df = rules.apply(df, rule_list).cache()
    report = quality_report(df, rule_list, "encounters", batch_id)

    q = df.where(F.size("_violations") > 0)
    raw_cols = [c for c in raw.columns if not c.startswith("_")]
    (q.select(F.lit("encounters").alias("source"), F.col("_reason").alias("reason_code"),
              F.concat_ws("|", "_violations").alias("all_reasons"),
              F.to_json(F.struct(*[F.col(c) for c in raw_cols])).alias("record_json"),
              "_file_name", "_file_checksum", "_load_ts", "batch_id")
       .write.mode("overwrite").partitionBy("batch_id").parquet(str(config.SILVER / "quarantine")))

    good = df.where(F.size("_violations") == 0)
    code = F.upper(F.trim("icd10_code"))
    clean = (good
             .withColumn("onset_date", F.to_date("onset_date"))
             .withColumn("report_date", F.to_date("report_date"))
             .withColumn("patient_hash", F.sha2(F.concat(F.lit(salt), F.col("patient_id")), 256))   # PRV-1
             .withColumn("age_band", age_band(F.col("age_years").cast("int")))
             .withColumn("icd10_code", code)
             .withColumn("disease", disease_of(code))
             .withColumn("lab_confirmed", F.lower("lab_confirmed") == "true")
             .withColumn("admitted", F.lower("admitted") == "true")
             .withColumn("outcome", F.lower("outcome"))
             .withColumn("delay_days", F.datediff("report_date", "onset_date")))
    clean = with_epiweek(clean, "onset_date")
    clean = with_epiweek(clean, "report_date", prefix="report_")
    clean = clean.select("encounter_id", "patient_hash", "facility_id", "facility_type", "district_code", "district",
                         "division", "onset_date", "report_date", "delay_days", "age_band", "sex", "icd10_code",
                         "disease", "lab_confirmed", "admitted", "outcome", "week_start", "epi_week",
                         "report_week_start", "report_epi_year", "report_epi_week",
                         "_file_name", "_file_checksum", "_load_ts", "epi_year", "batch_id")
    clean.write.mode("overwrite").partitionBy("epi_year", "batch_id").parquet(str(config.SILVER / "encounters"))
    years = sorted({r[0] for r in clean.select("epi_year").distinct().collect()} |
                   {r[0] for r in clean.select("report_epi_year").distinct().collect()})
    df.unpersist()
    return report, years


def process_stock(spark, batch_id: str, fac: DataFrame) -> pd.DataFrame:
    raw = spark.read.parquet(str(config.BRONZE / "stock")).where(F.col("batch_id") == batch_id)
    fac_small = fac.select(F.col("facility_id").alias("_fid"), F.lit(1).alias("_fac_known"), "district_code")
    w = Window.partitionBy("facility_id", "snapshot_date").orderBy(F.col("_file_name").desc())
    df = raw.join(F.broadcast(fac_small), raw.facility_id == F.col("_fid"), "left").withColumn("_dup_rank", F.row_number().over(w))
    rule_list = rules.stock_rules(F.to_date("_load_ts"))
    df = rules.apply(df, rule_list).cache()
    report = quality_report(df, rule_list, "stock", batch_id)
    raw_cols = [c for c in raw.columns if not c.startswith("_")]
    (df.where(F.size("_violations") > 0)
       .select(F.lit("stock").alias("source"), F.col("_reason").alias("reason_code"),
               F.concat_ws("|", "_violations").alias("all_reasons"),
               F.to_json(F.struct(*[F.col(c) for c in raw_cols])).alias("record_json"),
               "_file_name", "_file_checksum", "_load_ts", "batch_id")
       .write.mode("overwrite").partitionBy("batch_id").parquet(str(config.SILVER / "quarantine_stock")))
    good = df.where(F.size("_violations") == 0).select(
        F.to_date("snapshot_date").alias("snapshot_date"), "facility_id", "district_code",
        *[F.col(c).cast("int").alias(c) for c in ["iv_saline", "ns1_kits", "ors", "antimalarials", "occupied_beds"]],
        "_file_name", "_load_ts", "batch_id")
    good.write.mode("overwrite").partitionBy("batch_id").parquet(str(config.SILVER / "stock"))
    df.unpersist()
    return report


def run() -> None:
    spark = get_spark("episcope-silver")
    salt = config.get_salt()
    state = load_state()
    man = read_manifest()
    loaded = man[man.status == "loaded"]
    pending = sorted(set(loaded.batch_id) - set(state["processed"]))
    if not pending:
        print("[silver] no new batches")
        return
    fac = refresh_reference(spark).cache()
    reports = []
    years = set(state.get("pending_gold_years", []))
    for b in pending:
        srcs = set(loaded.loc[loaded.batch_id == b, "source"])
        print(f"[silver] batch {b}: {sorted(srcs)}")
        if "encounters" in srcs:
            rep, ys = process_encounters(spark, b, fac, salt)
            reports.append(rep)
            years |= set(ys)
        if "stock" in srcs:
            reports.append(process_stock(spark, b, fac))
        if srcs & {"weather", "facilities", "districts", "population"}:
            years |= {"__all__"}
        state["processed"].append(b)
    if reports:
        dq = pd.concat(reports, ignore_index=True)
        dq_dir = config.GOLD / "dq_report"
        for b, g in dq.groupby("batch_id"):  # one partition per batch -> idempotent
            (dq_dir / f"batch_id={b}").mkdir(parents=True, exist_ok=True)
            g.drop(columns="batch_id").to_parquet(dq_dir / f"batch_id={b}" / "part-0.parquet", index=False)
        print(dq.groupby(["batch_id", "source"])[["rows_in", "rows_quarantined"]].first().to_string())
    state["pending_gold_years"] = sorted(years, key=str)
    save_state(state)
    for t, part in (("encounters", True), ("quarantine", True), ("stock", True), ("quarantine_stock", True)):
        if (config.SILVER / t).exists():
            register_table(spark, "silver", t, config.SILVER / t, partitioned=part)


if __name__ == "__main__":
    with stage("silver_transform"):
        run()
