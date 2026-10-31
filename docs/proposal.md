# EpiScope – Proposal (M1)

**Group:** MD Naim Uddin Mozumdar (Data Engineer, lead) · Shamraj Deb Nath (Analytics Engineer) · Syed Nasibur Rahaman Ratul (Visualisation Engineer)

## 1. Problem restatement
The Ministry needs a prototype that turns routine health-facility reports, laboratory results, weather and
stock data into (i) early outbreak warnings per district for dengue, diarrhoea/cholera, influenza-like illness
and malaria, (ii) 1–4-week forecasts of cases and hospital demand, (iii) an allocation of a fixed national
supply budget, and (iv) a preparedness calendar, shown in a trustworthy dashboard that never exposes
identifiable patients and copes with late, incomplete and dirty data. Patient data is synthetic; geography,
population and weather are real public data.

## 2. Stakeholders and conflicts
| Conflict | Stakeholders pulling each way | Our resolution (to be evidenced) |
|---|---|---|
| C1 Sensitivity vs specificity | District officers want early alerts; epidemiologists fear alert fatigue | Threshold trade-off curve for two methods; choose the most sensitive operating point with ≤ 1 false alert per district-year; slider in dashboard |
| C2 Granularity vs privacy | Vector-control units want fine maps; regulator/patients want no re-identification | District level only; small-cell suppression (1–4) with complementary suppression; line-level data never leaves the lake |
| C3 Efficiency vs equity | Ministry wants least unmet demand; low-risk districts want a minimum share | LP with an equity floor α; efficiency–equity curve over 5 budgets × 5 α; recommend the α that buys most equity for ≤ 10% efficiency loss |
| C4 Freshness vs cost | Officers want real-time; Ministry has modest infrastructure | Daily incremental batch (decisions are weekly); recomputes only affected epi-years |
| C5 Accuracy vs interpretability | Analysts want accuracy; officials want explanations | Poisson GLM with named covariates instead of a black box; must beat seasonal naive in backtest |

## 3. Architecture and tools
Medallion lakehouse with PySpark 3.5 (local mode) and Parquet; Spark SQL/Hive catalog; Makefile + Python DAG
with retries for orchestration; PuLP/CBC for the LP; statsmodels STL for seasonality; D3.js v7 dashboard reading
pre-aggregated JSON. Chosen because they run on a 16 GB laptop, are open source, and match the course tools.
Alternatives considered: Delta Lake (ACID/time-travel, deferred: optional), Airflow (heavier than needed for a
single machine), Prophet/LSTM forecasts (less interpretable, C5).

## 4. Diseases and methods
Detection: EARS C2 and seasonal historical limits on onset-week counts (nowcast for immature weeks). Forecast:
dengue and diarrhoea, 1–6 weeks, lagged rainfall/temperature, rolling-origin backtest vs seasonal naive (MAE,
80% coverage, WIS). Demand: data-driven admission rates × stated consumption assumptions. Allocation: LP of
Section 6.3. Calendar: STL decomposition per division × disease.

## 5. Roles
Naim – ING-*, DQ-*, PRV-1, ENG-1..3 · Shamraj – AN-1..9 · Ratul – VIS-*, PRV-2. Everyone commits outside their role.

## 6. Risk register
| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | SF = 1 exceeds 45 min on our laptops | M | H | broadcast join, AQE, partition pruning, incremental gold; measure early at SF 0.25 |
| 2 | Open-Meteo rate limits / no internet | M | M | cache raw responses in bronze; flagged synthetic fallback |
| 3 | Hidden test drop has unexpected file names or bad rows | H | H | recognise files by schema, checksum idempotency, quarantine instead of crash |
| 4 | Detection drowned in seasonal false alarms | M | H | seasonal baseline method + threshold curve + nowcasting |
| 5 | Re-identification from small counts | M | H | primary + complementary suppression, tested |
| 6 | Team member unavailable | M | M | code organised by role with written guides; pair reviews |
| 7 | Late or missing commits from a member | M | M | small daily commits, shared checklist |
