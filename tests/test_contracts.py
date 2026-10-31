"""Files are recognised by their schema, never by their name (hidden test drop)."""
from pipeline import contracts


def test_classify_by_columns_in_any_order():
    cols = list(reversed(contracts.ENCOUNTER_COLS))
    assert contracts.classify(cols) == "encounters"
    assert contracts.classify(contracts.STOCK_COLS) == "stock"


def test_near_miss_is_flagged_as_schema_mismatch():
    cols = contracts.ENCOUNTER_COLS[:-1] + ["unexpected"]
    assert contracts.classify(cols) == "encounters:schema_mismatch"


def test_unknown_file():
    assert contracts.classify(["a", "b"]) is None
