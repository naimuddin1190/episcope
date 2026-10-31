# Data sources and provenance

| ID | Dataset | Status in this repo | Licence / note |
|---|---|---|---|
| S1 | District boundaries (ADM2) | `reference/bd_districts.topo.json`: geoBoundaries gbOpen BGD ADM3 (simplified, via the bangladesh-geojson project), upazilas dissolved to 64 districts, simplified with mapshaper (8%) | geoBoundaries CC BY 4.0; bangladesh-geojson MIT |
| S2 | Population by district | `reference/districts.csv`: district totals, approximately BBS Population & Housing Census 2022. `population_age_sex.csv` applies an approximate national age/sex structure to each district. **Replace with the exact BBS / WorldPop table before final submission if time allows.** | BBS (public) |
| S3 | Daily weather 2021–2025 | Downloaded by `make weather` from the Open-Meteo archive API at district centroids, cached raw in `data/landing/weather/`. If the API is unreachable a synthetic climatology is used and every output is flagged `synthetic-fallback`. | Open-Meteo CC BY 4.0 |
| S4–S6 | Encounters, facility registry, stock/beds | Synthetic, `generator/` (seeded, SF-scaled) | Synthetic teaching data |
| S7 | OpenDengue | Not used (optional) | |

District centroids for the weather queries come from the bangladesh-geojson district list.
