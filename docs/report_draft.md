# EpiScope: A Big Data Surveillance, Forecasting and Response-Planning Platform for Bangladesh — REPORT DRAFT

> Draft for the IEEE-format report (≤ 15 pages + appendices). Copy into the IEEE conference template (Word or
> Overleaf), re-run the numbers on your own machine (SF = 1) and replace every value marked ⟦…⟧ before
> submitting. Numbers currently shown come from a test run at **SF = 0.25 on a 2-CPU / 7 GB machine** with the
> synthetic weather fallback; your final numbers will differ.

**Cover page:** Group ⟦no.⟧ · MD Naim Uddin Mozumdar ⟦ID⟧ · Shamraj Deb Nath ⟦ID⟧ · Syed Nasibur Rahaman Ratul ⟦ID⟧ · Repository ⟦URL⟧ · Video ⟦URL⟧

## Abstract
Bangladesh faces strongly seasonal dengue, diarrhoeal disease, influenza-like illness (ILI) and malaria, while
the data needed to respond early is scattered across facility reports, laboratories, weather records and stock
ledgers. EpiScope is a prototype medallion lakehouse built with Apache Spark and Parquet that ingests
heterogeneous batch and incremental feeds, enforces 20 automated quality rules, de-identifies patients, and
produces epi-week marts. On top of these it detects outbreaks per district (EARS C2 and a seasonal
historical-limits method), forecasts cases 1–6 weeks ahead with an interpretable Poisson model, converts
forecasts into supply demand, allocates a fixed budget with a linear programme that trades efficiency against
equity, and derives a seasonal preparedness calendar. A D3.js dashboard with five linked views serves only
aggregated, small-cell-suppressed data. On synthetic data with injected ground truth, the chosen detector found
87 % ⟦check⟧ of outbreak episodes at 0.68 ⟦check⟧ false alerts per district-year, forecasts beat a seasonal-naïve
baseline by 40 % (dengue) and 22 % (diarrhoea) at 1 week ⟦check⟧ in MAE, and the optimiser reduced unmet demand from 23.6 % ⟦check⟧ to 3.5 % ⟦check⟧ compared with
population-proportional allocation at the same budget.

## 1. Introduction and problem analysis  *(Ratul)*
- Burden and seasonality (dengue 2023: > 300,000 hospitalisations, > 1,700 deaths; pre-monsoon diarrhoea; ILI in rainy season; malaria in the Chittagong Hill Tracts).
- The data problem: heterogeneous sources (format, timeliness, quality, granularity); analysis today is after the fact.
- Objectives (i)–(iv) of the client brief, and the non-functional requirements: trustworthy, explainable, works with late/incomplete data, privacy-preserving, modest infrastructure, scalable.
- Contributions (bullet list of what EpiScope delivers).

## 2. CEP attribute analysis and conflict resolution  *(Naim + all)*
| Attribute | How it appeared | Our design decision |
|---|---|---|
| P1 Depth of knowledge | distributed processing, columnar storage, surveillance statistics, optimisation, visual encoding, privacy | Spark + Parquet medallion; EARS/historical limits; GLM; LP; D3; suppression |
| P2 Conflicting requirements | C1–C5 below | each resolved with an experiment or explicit policy |
| P3 Depth of analysis | no single right threshold/model/objective | trade-off curves, rolling-origin backtests, 25-scenario grid |
| P4 Unfamiliar issues | reporting delays, back-fill artefact, duplicates, orphan keys, Dhaka skew | onset-week counting + nowcast, checksum idempotency, R16/R04 rules, AQE |
| P5 Beyond standard codes | no standard for a national allocation plan | combined IDSR thinking, ICD-10 coding, data-protection principles with our own LP |
| P6 Stakeholders | Ministry, epidemiologists, district officers, hospitals, vector control, public, regulator | role-specific views: map/table (officers), forecasts with bands (hospitals), privacy policy (regulator) |
| P7 Interdependence | quality → detection → forecast → optimiser → dashboard | lineage (bronze_batch_ids), DAG with retries, uncertainty propagated (q90 demand, bands) |

**C1 Sensitivity vs specificity.** Fig. ⟦1⟧ plots sensitivity against false alerts per district-year for both
methods over thresholds 1–6. EARS C2 reacts to every seasonal rise and needs h ≈ 5 to reach ≤ 1 false alert per
district-year (sensitivity below 88 % even at h = 6 (2.6 false alerts per district-year) ⟦check⟧). The seasonal historical-limits method reaches 87 % ⟦check⟧ at
0.68 ⟦check⟧ false alerts (h = 5 ⟦check⟧), so we chose it. Officers can move the threshold in the dashboard.

**C2 Granularity vs privacy.** District level, counts 1–4 suppressed, plus complementary suppression so that no
hidden cell can be recovered from published division or national totals (8,508 ⟦check⟧ cells hidden at SF 0.25).
Upazila maps would hide most cells for rarer diseases, so we keep the district level.

**C3 Efficiency vs equity.** Fig. ⟦3⟧: demand met vs coverage of the worst-served district for 5 budgets × 5
equity floors α. Recommended α = 0.5 ⟦check⟧: the largest equity gain for ≤ 10 % more weighted unmet demand.

**C4 Freshness vs cost.** Decisions (supply orders, campaigns) are weekly; reports arrive with a 0–21-day delay.
A daily incremental batch that only rebuilds affected epi-years is fresh enough; streaming would add cost and
complexity without changing any decision.

**C5 Accuracy vs interpretability.** A per-district Poisson GLM with named covariates (last weeks, same week last
year, season, rainfall, temperature) beats the seasonal-naïve baseline by 40 % (dengue) and 22 % (diarrhoea) at 1 week ⟦check⟧ (MAE) and its drivers can be
explained to officials; a black-box model would be harder to trust for a small gain.

## 3. Architecture and design decisions  *(Naim)*
Figure: landing → bronze → silver → gold → analytics → serving JSON → D3 (README §4).
- **Storage/format:** Parquet + Snappy; bronze partitioned by `batch_id`, silver by `epi_year/batch_id`, gold by `epi_year`; tables registered in the Hive catalog.
- **Idempotency:** SHA-256 manifest; dynamic partition overwrite; cross-batch de-duplication by `encounter_id`.
- **Incremental late data:** only epi-years touched by new records are rebuilt (partition pruning).
- **Orchestration:** Makefile + Python DAG with retries; one command `make all`.
- **Alternatives considered:** Delta Lake/Iceberg (time travel would help backtests; deferred), HDFS/MinIO (not needed on one laptop), Airflow (heavy), Kafka/Structured Streaming (C4), Prophet/LSTM (C5).

## 4. Data generation, quality, lineage and privacy  *(Naim)*
- Generator: seeded, SF-scaled; ≈ 28.5 M ⟦check⟧ encounters at SF = 1 (2021–2025, 64 districts, 957 facilities). Seasonality (von Mises curves), spatial patterns, climate drivers from S3 (dengue 4–8-week rainfall lag, diarrhoea after extreme rain), negative-binomial noise, 33 injected outbreak events (local, slow-growing, nationwide novel respiratory surge, 2023 dengue epidemic), one back-fill artefact; 2 % duplicates, 0.5 % orphan keys, 1 % invalid values; delays 0–21 days with fewer reports on Fridays/Saturdays and holidays.
- Quality: 16 encounter rules + 4 stock rules (table in docs/schema.md); quarantine with reason codes; per-load DQ report (gold.dq_report). At SF 0.25: 242,851 ⟦check⟧ of 7,142,635 ⟦check⟧ encounter rows quarantined (3.4 % ⟦check⟧).
- Lineage: every gold row carries `bronze_batch_ids`; manifest links batches → files → checksums → row counts.
- Privacy: salted SHA-256 (salt only in `.env`), age bands, no identifiers beyond bronze; suppression in serving.

## 5. Analytics methods  *(Shamraj)*
5.1 Detection (EARS C2 with Spark window functions; historical limits with grouped applyInPandas; nowcasting via the empirical delay distribution; onset-week counting).
5.2 Forecasting (direct multi-horizon Poisson GLM, NB intervals, applyInPandas per district).
5.3 Demand conversion (data-driven admission rates; assumptions table from `analytics/optimise/assumptions.py`).
5.4 Optimisation (LP of Section 6.3, objective normalised per resource; CBC).
5.5 Preparedness calendar (STL, season start, lead times).

## 6. Evaluation  *(Shamraj + Naim)*
**Detection** (2022 onward, mature weeks). Example at SF 0.25: dengue sensitivity was only 45 % (the broad 2023 epidemic rises like a strong season and is partly absorbed by the level-scaled baseline), diarrhoea and ILI 100 %, malaria 67 %; the slow-growing outbreak was found but only after ~91 days — discuss this honestly as a limitation. Table ⟦⟧ from `detection_tradeoff_curve.csv`; per-disease breakdown; median 18 ⟦check⟧ days to detection.
**Artefact:** naive report-week detector signal 4.46 SD (a false alarm at the usual threshold of 3) ⟦check⟧ (false alert) vs EpiScope onset-week 0.17 SD ⟦check⟧ (no alert).
**Forecasting backtest** (last 52 weeks, rolling origin): Table from `forecast_backtest_metrics.csv` (MAE, 80 % coverage, WIS vs seasonal naïve, horizons 1–4).
**Allocation:** optimiser vs population-proportional at the default budget; efficiency–equity curve.
**Scalability (ENG-2):** runtime per stage at SF 0.25/0.5/1 (`scaling_summary.md`) on ⟦your hardware⟧; SF = 1 total ⟦…⟧ min.
**Spark optimisations (ENG-3):** broadcast join of the facility registry and AQE skew handling: before/after times and Spark UI screenshots (SortMergeJoin → BroadcastHashJoin).

## 7. Dashboard design rationale and usability  *(Ratul)*
Five linked views (map, time series with brush and bands, heatmap, allocation, ranked table) + calendar, data quality and model-evaluation panels; what-if sliders; colour-blind-safe palette; hatched suppressed cells; freshness stamp on every view; ≈ 2.1 ⟦check⟧ MB of aggregated JSON. Usability test with two non-CS users: tasks, time, problems, changes made.

## 8. Ethical, societal and sustainability considerations  *(Ratul)*
Privacy and re-identification; stigma for districts flagged as outbreak areas; harm from false alarms and missed
outbreaks; equity of allocation; transparency of assumptions; synthetic data limits; energy/cost (runs on one laptop).

## 9. Limitations and future work
Synthetic epidemiology; approximate population structure; district (not upazila) level; LP ignores lead times
and multi-period stock; no streaming/Delta time travel; no role-based access control; SEIR scenario module not built.

## References
[1]–[10] from the assignment's recommended reading, plus geoBoundaries, Open-Meteo, PuLP, statsmodels.

## Appendix A – Policy brief (2 pages, non-technical)  *(Shamraj)*
**To:** Director, Disease Control & Preparedness Unit. **From:** EpiScope team. **Data up to:** ⟦date⟧.
1. **Situation now.** ⟦In one paragraph: which districts have alerts, expected cases next 4 weeks, where stock is short.⟧
2. **Top three recommendations.**
   - Pre-position IV saline and NS1 kits in ⟦districts⟧ by ⟦date⟧ (expected to cut unmet need from 23.6 % ⟦check⟧ to 3.5 % ⟦check⟧).
   - Start dengue larval-control campaigns in ⟦divisions⟧ by ⟦calendar date⟧.
   - Adopt the equity floor α = 0.5 ⟦check⟧ so that every district receives a minimum share.
3. **How to read the dashboard.** Red triangles = unusual rise; shaded bands = range of likely cases; striped areas = hidden for privacy.
4. **How sure are we.** Alerts catch about 87 % ⟦check⟧ of outbreaks, with about 0.68 ⟦check⟧ false alarm per district per year; forecasts are ranges, not promises.
5. **Data protection.** No names or ID numbers leave the secure layer; small numbers are hidden.

## Appendix B – Contribution matrix (copy the table from the assignment, fill L/S/–, sign)
## Appendix C – Individual reflections (½ page each)
