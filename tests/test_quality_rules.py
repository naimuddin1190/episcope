"""DQ-1: every rule catches the defect it is written for and passes a clean record."""
import pytest
from pyspark.sql import functions as F

from pipeline.quality import rules

GOOD = dict(encounter_id="E1", patient_id="1234567890", facility_id="F01001", onset_date="2024-07-01",
            report_date="2024-07-04", age_years="34", sex="F", icd10_code="A90", lab_confirmed="true",
            admitted="false", outcome="recovered", _fac_known=1, _dup_rank=1, _load_ts="2024-07-10T00:00:00")

CASES = [
    ("R01_ENCOUNTER_ID_NULL", dict(encounter_id="")),
    ("R02_PATIENT_ID_NULL", dict(patient_id=None)),
    ("R03_FACILITY_NULL", dict(facility_id="", _fac_known=None)),
    ("R04_FACILITY_UNKNOWN", dict(facility_id="F99999", _fac_known=None)),
    ("R05_ONSET_INVALID", dict(onset_date="2023/13/45")),
    ("R06_REPORT_INVALID", dict(report_date="N/A")),
    ("R07_ONSET_AFTER_REPORT", dict(onset_date="2024-07-05", report_date="2024-07-01")),
    ("R08_DELAY_IMPLAUSIBLE", dict(onset_date="2024-01-01", report_date="2024-07-01")),
    ("R09_FUTURE_DATE", dict(report_date="2024-08-01", onset_date="2024-07-30")),
    ("R10_DATE_TOO_OLD", dict(onset_date="2010-01-01", report_date="2010-01-03")),
    ("R11_AGE_INVALID", dict(age_years="212")),
    ("R11_AGE_INVALID", dict(age_years="abc")),
    ("R12_SEX_INVALID", dict(sex="X")),
    ("R13_ICD10_INVALID", dict(icd10_code="A9O")),
    ("R14_FLAG_INVALID", dict(admitted="maybe")),
    ("R15_OUTCOME_INVALID", dict(outcome="cured?")),
    ("R16_DUPLICATE_IN_BATCH", dict(_dup_rank=2)),
]


def evaluate(spark, rec):
    schema = ", ".join(f"{k} {'int' if k in ('_fac_known', '_dup_rank') else 'string'}" for k in GOOD)
    df = spark.createDataFrame([tuple(rec[k] for k in GOOD)], schema)
    df = rules.apply(df, rules.encounter_rules(F.to_date("_load_ts")))
    return df.select("_violations").first()[0]


def test_clean_record_passes(spark):
    assert evaluate(spark, GOOD) == []


@pytest.mark.parametrize("code,change", CASES)
def test_rule_fires(spark, code, change):
    assert code in evaluate(spark, {**GOOD, **change})


def test_at_least_12_rules():
    assert len(rules.encounter_rules(F.current_date())) >= 12
