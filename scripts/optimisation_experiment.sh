#!/usr/bin/env bash
# ENG-3 before/after: silver + gold with the optimisations OFF (no broadcast join, no AQE) and ON.
# Uses whatever data is already in data/landing (generate it first, e.g. make generate SF=0.5).
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH=$PWD
for OPT in 0 1; do
  echo "################ EPISCOPE_OPT=$OPT ################"
  rm -rf data/lake
  export EPISCOPE_OPT=$OPT EPISCOPE_RUN_LABEL="optimisation_opt_$OPT"
  python3 -m orchestration.run_pipeline --only bronze_ingest silver_transform gold_build ${HOLD:+--hold-ui}
done
python3 scripts/summarise_experiments.py
echo "Tip: HOLD=1 bash scripts/optimisation_experiment.sh keeps the Spark UI open for screenshots."
