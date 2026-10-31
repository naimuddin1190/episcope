# EpiScope - one-command build (ENG-1).
#   make all        clean rebuild: weather -> generator -> lake -> analytics -> dashboard data
#   make serve      open the dashboard at http://localhost:8000
#   make update     ingest whatever new files are in data/landing (daily load / hidden test drop)
# Settings come from .env (see .env.example): EPISCOPE_SF, EPISCOPE_SEED, SPARK_DRIVER_MEMORY ...

SHELL := /bin/bash
PY    ?= python3
-include .env
export
SF    ?= $(or $(EPISCOPE_SF),0.05)
SEED  ?= $(or $(EPISCOPE_SEED),42)
START ?= 2021-01-01
END   ?= 2025-12-31
PORT  ?= 8000
export PYTHONPATH := $(CURDIR)
export EPISCOPE_SF := $(SF)

.PHONY: all env install weather weather-synthetic generate pipeline update drop rerun-demo test serve \
        scaling optimisation-experiment clean clean-lake help

help:
	@grep -E '^#   make' Makefile | sed 's/^#   //'

all: env clean-lake weather generate pipeline   ## full clean rebuild
	@echo "Done. Run 'make serve' and open http://localhost:$(PORT)"

env:
	@$(PY) scripts/ensure_env.py

install:
	$(PY) -m pip install -r requirements.txt

weather:            ## S3: real Open-Meteo data (cached in data/landing/weather; skipped if present)
	@$(PY) -m generator.fetch_weather --start $(START) --end $(END) || { \
	  echo "!!! Open-Meteo not reachable - using the SYNTHETIC weather fallback (flagged in all outputs)."; \
	  $(PY) -m generator.fetch_weather --synthetic --start $(START) --end $(END); }

weather-synthetic:  ## offline fallback, flagged as synthetic in every output
	$(PY) -m generator.fetch_weather --synthetic --start $(START) --end $(END)

generate:           ## S4-S6 synthetic feeds + ground truth
	$(PY) -m generator.generate --sf $(SF) --seed $(SEED) --start $(START) --end $(END)

pipeline:           ## bronze -> silver -> gold -> analytics -> dashboard JSON (orchestrated, with retries)
	$(PY) -m orchestration.run_pipeline

update: env pipeline   ## incremental, idempotent load of any new files in data/landing

drop:               ## make a 14-day incremental drop after END for testing (DROP_START/DROP_END)
	$(PY) -m generator.generate --sf $(SF) --seed $$(( $(SEED) + 1 )) --drop \
	  --start $${DROP_START:-2026-01-01} --end $${DROP_END:-2026-01-14}

rerun-demo:         ## idempotency demo: deliver an already-loaded file again under a new name
	@f=$$(ls data/landing/encounters/*.csv | tail -1); cp $$f data/landing/encounters/resent_$$(basename $$f); \
	echo "re-delivered $$f"; $(PY) -m orchestration.run_pipeline --only bronze_ingest silver_transform gold_build

test:
	$(PY) -m pytest -q tests

serve:
	@echo "EpiScope dashboard: http://localhost:$(PORT)"
	cd dashboard && $(PY) -m http.server $(PORT)

scaling:            ## ENG-2: run the full pipeline at SF 0.25, 0.5 and 1
	bash scripts/scaling_experiment.sh

optimisation-experiment:  ## ENG-3: before/after Spark optimisations
	bash scripts/optimisation_experiment.sh

clean-lake:
	rm -rf data/lake

clean:
	rm -rf data dashboard/data/*.json
