import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def spark(tmp_path_factory):
    os.environ["EPISCOPE_NO_HIVE"] = "1"
    os.environ["EPISCOPE_DATA_DIR"] = str(tmp_path_factory.mktemp("data"))
    os.environ.setdefault("SPARK_DRIVER_MEMORY", "1g")
    from pyspark.sql import SparkSession
    s = (SparkSession.builder.master("local[1]").appName("episcope-tests")
         .config("spark.sql.shuffle.partitions", "2").config("spark.ui.enabled", "false").getOrCreate())
    yield s
    s.stop()
