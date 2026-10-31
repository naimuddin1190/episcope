# Schema contract (landing zone)

Files can be dropped anywhere under `data/landing/` with **any name**. Bronze recognises each file by its
columns (order does not matter). A file whose columns are close to, but not exactly, a contract is rejected as
`schema_mismatch`, copied to `data/lake/silver/quarantine_files/<batch_id>/` and logged in the manifest.
All values are ingested as strings in bronze; typing happens in silver.

## S4 Encounters (CSV, header row)

| column | type in silver | rules |
|---|---|---|
| encounter_id | string | R01 not null; R16 unique within batch (resubmissions quarantined); de-duplicated across batches in gold |
| patient_id | string → `patient_hash` | R02 not null; salted SHA-256; raw value never leaves bronze |
| facility_id | string | R03 not null; R04 must exist in facility registry |
| onset_date | date `yyyy-MM-dd` | R05 parseable; R07 ≤ report_date; R10 ≥ 2015-01-01 |
| report_date | date `yyyy-MM-dd` | R06 parseable; R08 report − onset ≤ 60 days; R09 not after load date |
| age_years | int → `age_band` | R11 integer 0–110 |
| sex | M/F | R12 |
| icd10_code | ICD-10 | R13 pattern `^[A-Z][0-9]{2}(\.[0-9A-Z]{1,2})?$`; A90/A91 dengue, A00/A09 diarrhoea, J10/J11 ILI, B50–B54 malaria, others "other" |
| lab_confirmed, admitted | true/false | R14 |
| outcome | recovered / referred / died / unknown | R15 |

## S5 Facility registry (CSV)
`facility_id, facility_name, facility_type, district_code, district, division, lat, lon, beds, icu_beds`

## S6 Stock and beds (JSON lines, one object per facility per day)
`snapshot_date, facility_id, iv_saline, ns1_kits, ors, antimalarials, occupied_beds`
Rules S01 facility known, S02 valid date, S03 non-negative numbers, S04 unique facility × date per batch.

## S3 Weather (JSON, Open-Meteo archive response)
`{"daily": {"time": [...], "precipitation_sum": [...], "temperature_2m_mean": [...], "relative_humidity_2m_mean": [...]},
  "episcope": {"district_code": "BD01", "source": "open-meteo", "synthetic": false}}`

## Reference
`districts.csv`: `district_code, district, division, lat, lon, population, malaria_zone, urban_index`
`population_age_sex.csv`: `district_code, age_band, sex, population`

## Ground truth (generator only, outside the landing zone)
`data/ground_truth/ground_truth_outbreaks*.csv`: `outbreak_id, kind, district_code, district, disease, start_date, end_date, peak_multiplier`
`data/ground_truth/artefacts*.csv`. Only `analytics/detection/evaluate.py` reads these, after detection.
