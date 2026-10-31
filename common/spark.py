"""Spark session factory shared by all pipeline and analytics stages (ING-2, ENG-3)."""
from __future__ import annotations

import os

from pyspark.sql import SparkSession

from common import config


JAVA_OPTS = ("-Dio.netty.tryReflectionSetAccessible=true "
             "--add-opens=java.base/java.nio=ALL-UNNAMED --add-opens=java.base/sun.nio.ch=ALL-UNNAMED "
             "--add-opens=java.base/java.lang=ALL-UNNAMED --add-opens=java.base/java.util=ALL-UNNAMED")


def optimisations_enabled() -> bool:
    """ENG-3 before/after switch. EPISCOPE_OPT=0 disables broadcast joins and AQE."""
    return os.environ.get("EPISCOPE_OPT", "1") != "0"


def get_spark(app: str = "episcope") -> SparkSession:
    config.ensure_dirs()
    opt = optimisations_enabled()
    builder = (
        SparkSession.builder.appName(app)
        .master(os.environ.get("SPARK_MASTER", "local[*]"))
        .config("spark.driver.memory", os.environ.get("SPARK_DRIVER_MEMORY", "6g"))
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", os.environ.get("SPARK_SHUFFLE_PARTITIONS", "16"))
        # Dynamic partition overwrite: re-running a batch replaces exactly its partitions (ING-4).
        .config("spark.sql.sources.partitionOverwriteMode", "dynamic")
        .config("spark.sql.parquet.compression.codec", "snappy")
        .config("spark.sql.warehouse.dir", str(config.CATALOG_DIR / "warehouse"))
        # JVM flags: Derby metastore location + Arrow (pandas UDFs) on Java 17/21
        .config("spark.driver.extraJavaOptions", f"-Dderby.system.home={config.CATALOG_DIR} " + JAVA_OPTS)
        .config("spark.executor.extraJavaOptions", JAVA_OPTS)
        .config("spark.sql.execution.arrow.pyspark.enabled", "true")
        .config("spark.ui.showConsoleProgress", "false")
        # ENG-3 optimisation 1: Adaptive Query Execution incl. skew-join handling (Dhaka skew).
        .config("spark.sql.adaptive.enabled", str(opt).lower())
        .config("spark.sql.adaptive.skewJoin.enabled", str(opt).lower())
        .config("spark.sql.adaptive.coalescePartitions.enabled", str(opt).lower())
        # ENG-3 optimisation 2: broadcast the small facility registry instead of a shuffle join.
        .config("spark.sql.autoBroadcastJoinThreshold", "10485760" if opt else "-1")
    )
    if os.environ.get("EPISCOPE_NO_HIVE") != "1":
        builder = builder.enableHiveSupport()
    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("ERROR")
    return spark


def register_table(spark: SparkSession, layer: str, name: str, path, partitioned: bool = False) -> None:
    """Register a Parquet directory in the Spark SQL / Hive catalog (ING-3)."""
    try:
        spark.sql(f"CREATE DATABASE IF NOT EXISTS episcope_{layer}")
        spark.sql(f"DROP TABLE IF EXISTS episcope_{layer}.{name}")
        spark.sql(f"CREATE TABLE episcope_{layer}.{name} USING parquet LOCATION '{path}'")
        if partitioned:
            spark.sql(f"ALTER TABLE episcope_{layer}.{name} RECOVER PARTITIONS")
    except Exception as exc:  # catalog is a convenience; never fail the pipeline on it
        print(f"[catalog] could not register {layer}.{name}: {exc}")
