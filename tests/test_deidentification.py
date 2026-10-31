"""PRV-1: identifiers are salted-hashed, the raw ID never reaches silver, age becomes a band."""
from pyspark.sql import functions as F

from pipeline.silver.transform import age_band, disease_of


def test_salted_hash_is_deterministic_and_salt_dependent(spark):
    df = spark.createDataFrame([("1234567890",)], ["patient_id"])
    h1 = df.select(F.sha2(F.concat(F.lit("salt-A"), "patient_id"), 256)).first()[0]
    h2 = df.select(F.sha2(F.concat(F.lit("salt-A"), "patient_id"), 256)).first()[0]
    h3 = df.select(F.sha2(F.concat(F.lit("salt-B"), "patient_id"), 256)).first()[0]
    assert h1 == h2 and h1 != h3 and "1234567890" not in h1 and len(h1) == 64


def test_silver_schema_has_no_direct_identifiers():
    src = open("pipeline/silver/transform.py").read()
    select_block = src[src.index('clean = clean.select('):src.index('clean.write')]
    assert '"patient_id"' not in select_block and '"age_years"' not in select_block
    assert '"patient_hash"' in select_block and '"age_band"' in select_block


def test_age_bands_and_disease_mapping(spark):
    df = spark.createDataFrame([(3, "A90"), (14, "A09"), (30, "J11.1"), (70, "B50.9"), (50, "I10")], ["age", "code"])
    out = df.select(age_band(F.col("age")).alias("b"), disease_of(F.col("code")).alias("d")).collect()
    assert [r.b for r in out] == ["00-04", "05-14", "25-44", "65+", "45-64"]
    assert [r.d for r in out] == ["dengue", "diarrhoea", "ili", "malaria", "other"]
