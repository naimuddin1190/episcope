#!/usr/bin/env bash
# ENG-2 scalability experiment: generator + full pipeline at SF 0.25, 0.5 and 1.
# Per-stage runtimes -> docs/experiments/stage_timings.jsonl, sizes -> output_sizes.tsv,
# summary table -> docs/experiments/scaling_summary.md
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH=$PWD
for SF in ${SFS:-0.25 0.5 1}; do
  echo "################ SF=$SF  $(date '+%H:%M:%S') ################"
  export EPISCOPE_SF=$SF EPISCOPE_RUN_LABEL="scaling_sf_$SF" EPISCOPE_OPT=1
  rm -rf data/lake
  python3 -m generator.generate --sf "$SF" --seed 42
  python3 - <<PY
import json
from common import config
d = json.load(open(config.GROUND_TRUTH / "generator_run.json"))
with open(config.EXPERIMENTS / "stage_timings.jsonl", "a") as fh:
    fh.write(json.dumps({"stage": "generator", "seconds": d["seconds"], "status": "ok",
                         "run_label": "scaling_sf_$SF", "sf": "$SF", "rows": d["encounters"]}) + "\n")
PY
  python3 -m orchestration.run_pipeline
  du -sb data/landing data/lake/bronze data/lake/silver data/lake/gold dashboard/data \
    | awk -v sf="$SF" '{print sf"\t"$2"\t"$1}' >> docs/experiments/output_sizes.tsv
done
python3 scripts/summarise_experiments.py
