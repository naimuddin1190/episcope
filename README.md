# EpiScope

**A big-data surveillance, forecasting and response-planning platform for seasonal, tropical and epidemic diseases in Bangladesh.**
CSE 4345 Big Data Analytics, Complex Engineering Problem, Premier University Chittagong.

> 🎥 **Video presentation:** `<PASTE YOUR YOUTUBE (UNLISTED) LINK HERE>`  (chapters/timestamps below)
> 📄 **Report:** `docs/EpiScope_report.pdf`
> ⚠️ All patient-level data is **synthetic** (teaching case). Real public data: district boundaries (geoBoundaries via bangladesh-geojson), census population, Open-Meteo weather.

Group: MD Naim Uddin Mozumdar (Data Engineer) · Shamraj Deb Nath (Analytics Engineer) · Syed Nasibur Rahaman Ratul (Visualisation Engineer)

---

## 1. Prerequisites

| | Version |
|---|---|
| OS | Linux, macOS, or Windows 10/11 with **WSL2 (Ubuntu 22.04)** |
| Java | **17** (`sudo apt install openjdk-17-jdk`; set `JAVA_HOME`) |
| Python | **3.10 or 3.11** |
| RAM | 16 GB recommended for SF = 1 (8 GB works up to SF ≈ 0.25; set `SPARK_DRIVER_MEMORY=4g`) |
| Internet | only for the first weather download (Open-Meteo) |

```bash
git clone <repo-url> episcope && cd episcope
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt            # pinned versions
```

## 2. One-command run (ENG-1)

```bash
make all          # clean rebuild: weather -> generator -> bronze/silver/gold -> analytics -> dashboard data
make serve        # dashboard at http://localhost:8000
```

`make all` creates `.env` with a fresh random salt on first use (never committed), downloads weather once
(cached), generates the synthetic feeds, and runs the orchestrated DAG with retries:

```
bronze_ingest -> silver_transform -> gold_build -> detection -> detection_evaluation
              -> forecast -> demand_and_allocation -> calendar -> serving_export
```

Settings live in `.env` (copy of `.env.example`): `EPISCOPE_SF` (scale factor, 1.0 = 25 M+ encounters),
`EPISCOPE_SEED`, `SPARK_DRIVER_MEMORY`, `EPISCOPE_OPT`. Override on the command line, e.g. `make all SF=1`.

Other targets: `make test` (pytest), `make update` (incremental load), `make drop` (make a 14-day test drop),
`make rerun-demo` (idempotency demo), `make scaling` (ENG-2), `make optimisation-experiment` (ENG-3).

## 3. Running the hidden 14-day test drop

1. Copy the drop's files **anywhere under `data/landing/`** (any file names; files are recognised by their columns, see `docs/schema.md`).
2. Run:
   ```bash
   make update
   make serve
   ```
`make update` ingests only files whose SHA-256 checksum is new, quarantines bad rows with reason codes,
updates every epi-week touched by late records (up to 21 days), regenerates alerts, forecasts, the
allocation plan and the dashboard JSON. Nothing in the code depends on dates, file names or row counts.
Re-running it is safe (idempotent).

## 4. Architecture summary

```
landing/ (CSV, JSONL, JSON)  ──►  BRONZE  raw strings + batch_id, _source, _load_ts, _file_name, _file_checksum
   S1-S6 + reference              (Parquet, partitioned by batch_id; manifest = lineage)
                               ──►  SILVER  16 quality rules -> quarantine(reason_code); salted SHA-256 patient hash,
                                    age bands; facility registry broadcast-joined; ISO epi-week
                                    (Parquet, partitioned by epi_year / batch_id, dynamic overwrite = idempotent)
                               ──►  GOLD    weekly_cases (district x disease x week, zero-filled, incidence,
                                    completeness, bronze_batch_ids), weekly_by_report, delay_distribution,
                                    weekly_weather, stock_latest, dq_report, batches
                                    (only epi-years touched by new/late records are rebuilt)
analytics (Spark window functions / applyInPandas) ─► detection_signals, forecasts, allocation, calendar
serving/export.py ─► dashboard/data/*.json  (aggregated, small-cell suppressed, < 10 MB)  ─► D3.js v7 dashboard
```
All tables are registered in the Spark SQL/Hive catalog (`episcope_bronze.*`, `episcope_silver.*`, `episcope_gold.*`).

## 5. Repository layout

```
common/          config (paths from env), Spark session (optimisation switches), stage timer
generator/       fetch_weather.py (S3), generate.py + epi_model.py + outbreaks.py + facilities.py (S4-S6)
pipeline/        bronze/ingest.py, silver/transform.py, quality/rules.py, gold/build.py, contracts.py
analytics/       detection/ (detect.py, evaluate.py), forecast/, optimise/ (allocate.py, assumptions.py), calendar/
serving/         export.py, suppression.py
dashboard/       index.html, css/, js/ (one module per view), vendor/ (d3 v7, topojson-client)
orchestration/   run_pipeline.py (DAG with retries)
reference/       districts.csv, population_age_sex.csv, bd_districts.topo.json
scripts/         ensure_env.py, scaling_experiment.sh, optimisation_experiment.sh, summarise_experiments.py
tests/           quality rules, de-identification, suppression, optimiser, schema contracts
docs/            proposal.md, schema.md, data_sources.md, experiments/, guides/ (team guides)
```

## 6. Requirement traceability

| ID | Where | Report § |
|---|---|---|
| ING-1 | `generator/*`, `pipeline/bronze/ingest.py` (metadata: batch_id, _source, _load_ts, _file_checksum) | 4 |
| ING-2 | all heavy steps in PySpark (`pipeline/*`, `analytics/*`); pandas only for small gold outputs | 3 |
| ING-3 | Parquet partitioned by `batch_id` / `epi_year`; catalog in `common/spark.py::register_table` | 3 |
| ING-4 | checksum manifest (`pipeline/bronze/ingest.py`), dynamic partition overwrite, gold year rebuild (`pipeline/gold/build.py`) | 4 |
| DQ-1 | `pipeline/quality/rules.py` (16 encounter + 4 stock rules), quarantine tables | 4 |
| DQ-2 | `gold/dq_report` (per batch), dashboard "Data quality" panel | 4, 7 |
| DQ-3 | `bronze_batch_ids` on every gold row, `gold/batches` + `data/lake/_meta/manifest.csv` | 4 |
| PRV-1 | salted SHA-256 in `pipeline/silver/transform.py`, salt only in `.env` | 4, 8 |
| PRV-2 | `serving/suppression.py` (primary + complementary), checked before export | 4, 8 |
| AN-1 | `analytics/detection/detect.py` (EARS C2 with window functions; historical limits with applyInPandas) | 5 |
| AN-2 | `analytics/detection/evaluate.py`, `docs/experiments/detection_tradeoff_curve.csv` | 6 |
| AN-3 | two methods compared + naive report-week detector vs onset-week detector on the injected artefact | 6 |
| AN-4 | `analytics/forecast/forecast.py` (per-district Poisson GLM with lagged weather, applyInPandas) | 5 |
| AN-5 | 52-week rolling-origin backtest vs seasonal naive: MAE, 80% coverage, WIS | 6 |
| AN-6 | `analytics/optimise/assumptions.py` + `allocate.py::demand_table` | 5 |
| AN-7 | `analytics/optimise/allocate.py::solve` (PuLP/CBC LP) vs population baseline | 5, 6 |
| AN-8 | efficiency-equity curve, 5 budgets x 5 alpha (`docs/experiments/efficiency_equity_curve.csv`) | 6 |
| AN-9 | `analytics/calendar/calendar.py` (STL per division x disease) | 5 |
| VIS-1..4 | `dashboard/` (D3 v7 only; 5 linked views; < 10 MB aggregated JSON) | 7 |
| VIS-5 | what-if sliders: threshold, budget, equity floor (precomputed scenario grid) | 7 |
| VIS-6 | colour-blind-safe palette, uncertainty bands, hatched suppressed cells, freshness stamp on every view | 7 |
| ENG-1 | `Makefile` (`make all`), pinned `requirements.txt` | 3 |
| ENG-2 | `scripts/scaling_experiment.sh`, `docs/experiments/scaling_summary.md` | 6 |
| ENG-3 | `common/spark.py` (broadcast join, AQE skew handling), `scripts/optimisation_experiment.sh` | 6 |
| ENG-4 | `tests/` (pytest), `orchestration/run_pipeline.py` (retries) | 3 |

Not implemented (honest scope): ING-5/6/7 (HDFS/MinIO, streaming, Delta), DQ-4, PRV-3/4, AN-10, VIS-7.

## 7. Video chapters

| Time | Chapter | Presenter |
|---|---|---|
| 00:00 | 1. Problem, stakeholders, conflicts C1-C5 | |
| | 2. Architecture walkthrough | Naim |
| | 3. Pipeline run: clean run, incremental day, idempotent re-run, quarantine | Naim |
| | 4. Analytics vs baselines | Shamraj |
| | 5. Dashboard walkthrough (linked views, what-if) | Ratul |
| | 6. Recommendations, ethics, limitations | |

## 8. Credits

D3.js v7 and topojson-client (ISC licence, `dashboard/vendor/`); district boundaries derived from geoBoundaries
(CC BY 4.0) via the bangladesh-geojson project (MIT); weather from Open-Meteo (CC BY 4.0). See `AI_USAGE.md`.
