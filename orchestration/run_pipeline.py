"""Orchestrated DAG with retries (ENG-1, ENG-4).

    bronze_ingest -> silver_transform -> gold_build -> detection -> detection_evaluation
                  -> forecast -> demand_and_allocation -> calendar -> serving_export

All stages share one Spark session. Each stage is retried (default 2 retries) before the run
fails. Every stage is idempotent, so re-running the whole DAG is always safe.

    python -m orchestration.run_pipeline              # everything after the generator
    python -m orchestration.run_pipeline --only bronze_ingest silver_transform gold_build
"""
from __future__ import annotations

import argparse
import importlib
import time
import traceback

from common.timing import stage

DAG = [
    ("bronze_ingest", "pipeline.bronze.ingest"),
    ("silver_transform", "pipeline.silver.transform"),
    ("gold_build", "pipeline.gold.build"),
    ("detection", "analytics.detection.detect"),
    ("detection_evaluation", "analytics.detection.evaluate"),
    ("forecast", "analytics.forecast.forecast"),
    ("demand_and_allocation", "analytics.optimise.allocate"),
    ("calendar", "analytics.calendar.calendar"),
    ("serving_export", "serving.export"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="run only these stages")
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--hold-ui", action="store_true",
                    help="keep the Spark UI (http://localhost:4040) open at the end for screenshots (ENG-3)")
    a = ap.parse_args()
    for name, module in DAG:
        if a.only and name not in a.only:
            continue
        for attempt in range(a.retries + 1):
            try:
                with stage(name, attempt=attempt):
                    importlib.import_module(module).run()
                break
            except Exception:
                traceback.print_exc()
                if attempt == a.retries:
                    raise SystemExit(f"stage {name} failed after {a.retries + 1} attempts")
                print(f"[dag] retrying {name} in 5s ...")
                time.sleep(5)
    if a.hold_ui:
        input("Spark UI is at http://localhost:4040 - take your screenshots, then press Enter to finish ")


if __name__ == "__main__":
    main()
