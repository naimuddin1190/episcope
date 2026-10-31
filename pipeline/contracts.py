"""Schema contract for every landing feed (see docs/schema.md). Files are recognised by their
columns, never by their file names or dates, so new drops are ingested without code changes."""

ENCOUNTER_COLS = ["encounter_id", "patient_id", "facility_id", "onset_date", "report_date", "age_years", "sex",
                  "icd10_code", "lab_confirmed", "admitted", "outcome"]
FACILITY_COLS = ["facility_id", "facility_name", "facility_type", "district_code", "district", "division", "lat",
                 "lon", "beds", "icu_beds"]
STOCK_COLS = ["snapshot_date", "facility_id", "iv_saline", "ns1_kits", "ors", "antimalarials", "occupied_beds"]
DISTRICT_COLS = ["district_code", "district", "division", "lat", "lon", "population", "malaria_zone", "urban_index"]
POPULATION_COLS = ["district_code", "age_band", "sex", "population"]
WEATHER_COLS = ["district_code", "date", "precipitation_sum", "temperature_2m_mean", "relative_humidity_2m_mean"]

SOURCES = {
    "encounters": ENCOUNTER_COLS,
    "facilities": FACILITY_COLS,
    "stock": STOCK_COLS,
    "districts": DISTRICT_COLS,
    "population": POPULATION_COLS,
}


def classify(columns: list[str]) -> str | None:
    """Return the source whose contract matches these columns (order-insensitive)."""
    cols = set(c.strip() for c in columns)
    for name, contract in SOURCES.items():
        if cols == set(contract):
            return name
    # Near-matches are reported as schema violations of the closest source
    for name, contract in SOURCES.items():
        if len(cols & set(contract)) >= len(contract) - 2:
            return f"{name}:schema_mismatch"
    return None
