"""Automated data-quality rules (DQ-1). Each rule returns a boolean Column that is TRUE when a
row VIOLATES the rule. Failing rows go to the quarantine table with the rule code as reason."""
from __future__ import annotations

from pyspark.sql import Column
from pyspark.sql import functions as F

ICD_PATTERN = r"^[A-Z][0-9]{2}(\.[0-9A-Z]{1,2})?$"
VALID_SEX = ["M", "F"]
VALID_BOOL = ["true", "false"]
VALID_OUTCOME = ["recovered", "referred", "died", "unknown"]
MAX_PLAUSIBLE_DELAY = 60  # days; normal delays are 0-21, back-filled reports can be longer


def _date(c: str) -> Column:
    return F.to_date(F.col(c), "yyyy-MM-dd")


def _blank(c: str) -> Column:
    return F.col(c).isNull() | (F.trim(F.col(c)) == "")


def encounter_rules(load_date: Column) -> list[tuple[str, str, Column]]:
    """(code, description, violation expression). Requires column `_fac_known` from the RI join."""
    age = F.col("age_years").cast("int")
    onset, report = _date("onset_date"), _date("report_date")
    return [
        ("R01_ENCOUNTER_ID_NULL", "encounter_id is missing", _blank("encounter_id")),
        ("R02_PATIENT_ID_NULL", "patient_id is missing", _blank("patient_id")),
        ("R03_FACILITY_NULL", "facility_id is missing", _blank("facility_id")),
        ("R04_FACILITY_UNKNOWN", "facility_id not in facility registry (referential integrity)",
         ~_blank("facility_id") & F.col("_fac_known").isNull()),
        ("R05_ONSET_INVALID", "onset_date missing or not yyyy-MM-dd", onset.isNull()),
        ("R06_REPORT_INVALID", "report_date missing or not yyyy-MM-dd", report.isNull()),
        ("R07_ONSET_AFTER_REPORT", "onset_date > report_date", onset > report),
        ("R08_DELAY_IMPLAUSIBLE", f"report_date - onset_date > {MAX_PLAUSIBLE_DELAY} days",
         F.datediff(report, onset) > MAX_PLAUSIBLE_DELAY),
        ("R09_FUTURE_DATE", "report_date after the load date", report > load_date),
        ("R10_DATE_TOO_OLD", "onset_date before 2015-01-01", onset < F.lit("2015-01-01").cast("date")),
        ("R11_AGE_INVALID", "age_years not an integer in 0..110",
         age.isNull() | (age < 0) | (age > 110) | ~F.col("age_years").rlike(r"^-?[0-9]+$")),
        ("R12_SEX_INVALID", "sex not in {M, F}", ~F.coalesce(F.col("sex").isin(VALID_SEX), F.lit(False))),
        ("R13_ICD10_INVALID", "icd10_code not a valid ICD-10 code",
         ~F.coalesce(F.col("icd10_code").rlike(ICD_PATTERN), F.lit(False))),
        ("R14_FLAG_INVALID", "lab_confirmed / admitted not true|false",
         ~F.coalesce(F.lower("lab_confirmed").isin(VALID_BOOL) & F.lower("admitted").isin(VALID_BOOL), F.lit(False))),
        ("R15_OUTCOME_INVALID", "outcome not in allowed set",
         ~F.coalesce(F.lower("outcome").isin(VALID_OUTCOME), F.lit(False))),
        ("R16_DUPLICATE_IN_BATCH", "same encounter_id delivered more than once (resubmission)",
         F.col("_dup_rank") > 1),
    ]


def stock_rules(load_date: Column) -> list[tuple[str, str, Column]]:
    nums = ["iv_saline", "ns1_kits", "ors", "antimalarials", "occupied_beds"]
    bad_num = F.lit(False)
    for c in nums:
        v = F.col(c).cast("double")
        bad_num = bad_num | v.isNull() | (v < 0)
    snap = _date("snapshot_date")
    return [
        ("S01_FACILITY_UNKNOWN", "facility_id not in facility registry", F.col("_fac_known").isNull()),
        ("S02_DATE_INVALID", "snapshot_date missing/invalid or in the future", snap.isNull() | (snap > load_date)),
        ("S03_QUANTITY_INVALID", "stock or bed value missing or negative", bad_num),
        ("S04_DUPLICATE_IN_BATCH", "same facility and snapshot_date delivered twice", F.col("_dup_rank") > 1),
    ]


def apply(df, rules):
    """Add `_violations` (array of failed rule codes) and `_reason` (first failed rule)."""
    checks = [F.when(F.coalesce(expr, F.lit(True)) if code.startswith(("R05", "R06")) else F.coalesce(expr, F.lit(False)),
                     F.lit(code)) for code, _, expr in rules]
    df = df.withColumn("_violations", F.filter(F.array(*checks), lambda x: x.isNotNull()))
    return df.withColumn("_reason", F.element_at("_violations", 1))
