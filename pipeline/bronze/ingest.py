"""Bronze layer (ING-1, ING-4, DQ-3): land every new file unchanged, plus ingestion metadata.

* Discovers files anywhere under data/landing/ (and the reference/ folder) and recognises them
  by schema, so the hidden test drop can be dropped in with any file names.
* Idempotent: a file is identified by its SHA-256 checksum. A file that was already loaded is
  skipped, so re-running a day never creates duplicates.
* Each run gets one batch_id; every bronze row carries batch_id, _source, _load_ts,
  _file_name and _file_checksum (lineage, DQ-3).
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

from common import config
from common.spark import get_spark, register_table
from common.timing import stage
from pipeline import contracts

MANIFEST = config.META / "manifest.csv"
MANIFEST_COLS = ["batch_id", "source", "file_name", "file_path", "checksum", "size_bytes", "rows", "status", "loaded_at"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_manifest() -> pd.DataFrame:
    if MANIFEST.exists():
        return pd.read_csv(MANIFEST, dtype=str)
    return pd.DataFrame(columns=MANIFEST_COLS)


def sniff(path: Path) -> str | None:
    """Recognise a file by its content (never by its name)."""
    try:
        if path.suffix == ".csv":
            with open(path, newline="") as fh:
                header = next(csv.reader(fh), [])
            return contracts.classify(header)
        if path.suffix == ".jsonl":
            with open(path) as fh:
                first = fh.readline()
            return contracts.classify(list(json.loads(first).keys())) if first.strip() else None
        if path.suffix == ".json":
            with open(path) as fh:
                head = fh.read(4096)
            if '"type": "Topology"' in head or '"type":"Topology"' in head:
                return "geometry"
            if '"daily"' in head or '"daily"' in open(path).read():
                return "weather"
    except Exception:
        return None
    return None


def discover() -> list[Path]:
    files = [p for p in config.LANDING.rglob("*") if p.is_file() and p.suffix in (".csv", ".json", ".jsonl")]
    files += [p for p in config.REFERENCE_DIR.glob("*") if p.suffix in (".csv", ".json")]
    return sorted(files)


def string_schema(cols):
    return StructType([StructField(c, StringType(), True) for c in cols])


def weather_rows(paths: list[Path]) -> pd.DataFrame:
    frames = []
    for p in paths:
        js = json.loads(p.read_text())
        d = js["daily"]
        df = pd.DataFrame({k: d.get(k) for k in ["time", "precipitation_sum", "temperature_2m_mean",
                                                 "relative_humidity_2m_mean"]}).rename(columns={"time": "date"})
        df.insert(0, "district_code", js.get("episcope", {}).get("district_code"))
        df["weather_source"] = js.get("episcope", {}).get("source", "open-meteo")
        df["_file_name"] = p.name
        frames.append(df.astype(str))
    return pd.concat(frames, ignore_index=True)


def run() -> str | None:
    spark = get_spark("episcope-bronze")
    manifest = read_manifest()
    known = set(manifest.loc[manifest.status.isin(["loaded", "rejected_schema", "unrecognised"]), "checksum"])
    now = datetime.now(timezone.utc)
    new, rows_by_file = [], {}
    for p in discover():
        cs = sha256(p)
        if cs in known:
            continue
        known.add(cs)
        new.append(dict(path=p, checksum=cs, source=sniff(p), size=p.stat().st_size))
    if not new:
        print("[bronze] no new files - nothing to do (idempotent re-run)")
        return None

    batch_id = "B" + now.strftime("%Y%m%dT%H%M%S") + "_" + hashlib.sha1("".join(n["checksum"] for n in new).encode()).hexdigest()[:6]
    load_ts = now.isoformat(timespec="seconds")
    print(f"[bronze] batch {batch_id}: {len(new)} new file(s)")
    by_source: dict[str, list[dict]] = {}
    for n in new:
        by_source.setdefault(n["source"] or "unrecognised", []).append(n)

    status = {}
    for source, items in by_source.items():
        paths = [i["path"] for i in items]
        csmap = spark.createDataFrame([(i["path"].name, i["checksum"]) for i in items], ["_file_name", "_file_checksum"])
        out = config.BRONZE / source
        if source in ("encounters", "facilities", "stock", "districts", "population"):
            cols = contracts.SOURCES[source]
            if source == "stock":
                df = spark.read.schema(string_schema(cols)).json([str(p) for p in paths])
            else:
                # group by header order so that columns are mapped by name, not by position
                groups: dict[tuple, list[str]] = {}
                for p in paths:
                    with open(p, newline="") as fh:
                        groups.setdefault(tuple(next(csv.reader(fh))), []).append(str(p))
                parts = [spark.read.option("header", True).schema(string_schema(list(h))).csv(ps).select(*cols)
                         for h, ps in groups.items()]
                df = parts[0]
                for extra in parts[1:]:
                    df = df.unionByName(extra)
            df = df.withColumn("_file_name", F.element_at(F.split(F.input_file_name(), "/"), -1))
        elif source == "weather":
            df = spark.createDataFrame(weather_rows(paths))
        elif source == "geometry":
            (out / batch_id).mkdir(parents=True, exist_ok=True)
            for p in paths:
                shutil.copy2(p, out / batch_id / p.name)
            for i in items:
                status[i["checksum"]] = ("loaded", 1)
            continue
        else:
            for i in items:
                status[i["checksum"]] = ("rejected_schema" if source and "schema_mismatch" in source else "unrecognised", 0)
                print(f"[bronze] {i['path'].name}: {status[i['checksum']][0]} ({source})")
            if source and "schema_mismatch" in source:  # keep the rejected file for inspection
                qdir = config.SILVER / "quarantine_files" / batch_id
                qdir.mkdir(parents=True, exist_ok=True)
                for p in paths:
                    shutil.copy2(p, qdir / p.name)
            continue

        df = (df.join(F.broadcast(csmap), "_file_name", "left")
                .withColumn("_source", F.lit(source))
                .withColumn("_load_ts", F.lit(load_ts))
                .withColumn("batch_id", F.lit(batch_id)))
        df.write.mode("overwrite").partitionBy("batch_id").parquet(str(out))
        counts = {r["_file_name"]: r["n"] for r in
                  spark.read.parquet(str(out)).where(F.col("batch_id") == batch_id)
                  .groupBy("_file_name").agg(F.count("*").alias("n")).collect()}
        for i in items:
            status[i["checksum"]] = ("loaded", counts.get(i["path"].name, 0))
        register_table(spark, "bronze", source, out, partitioned=True)
        print(f"[bronze] {source}: {len(items)} file(s), {sum(counts.values()):,} rows")

    rows = [dict(batch_id=batch_id, source=n["source"], file_name=n["path"].name,
                 file_path=str(n["path"].relative_to(config.REPO_ROOT) if n["path"].is_relative_to(config.REPO_ROOT) else n["path"]),
                 checksum=n["checksum"], size_bytes=n["size"], rows=status[n["checksum"]][1],
                 status=status[n["checksum"]][0], loaded_at=load_ts) for n in new]
    manifest = pd.concat([manifest, pd.DataFrame(rows).astype(str)], ignore_index=True)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    manifest.to_csv(MANIFEST, index=False)
    return batch_id


if __name__ == "__main__":
    with stage("bronze_ingest"):
        run()
