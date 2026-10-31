"""Testing & QA (Puja Dey): scoring detection against injected outbreaks (AN-2, conflict C1)."""
import numpy as np
import pandas as pd

from analytics.detection.evaluate import score

WEEKS = pd.date_range("2024-01-01", periods=20, freq="7D")  # Mondays

TRUTH = pd.DataFrame({
    "district_code": ["D1"], "disease": ["dengue"],
    "start_date": [WEEKS[10]], "end_date": [WEEKS[12] + pd.Timedelta(days=6)],
})


def _signals(alert_weeks):
    stat = np.zeros(len(WEEKS))
    stat[list(alert_weeks)] = 10.0
    return pd.DataFrame({"district_code": "D1", "disease": "dengue", "week_start": WEEKS,
                         "ears_stat": stat, "x": 20.0})


def test_detected_outbreak_and_one_false_alert():
    r = score(_signals([3, 10]), TRUTH, "ears_stat", h=3.0, min_cases=5)
    assert r["outbreaks"] == 1
    assert r["detected"] == 1
    assert r["sensitivity"] == 1.0
    assert r["false_alerts"] == 1                  # week 3 is outside the outbreak window
    assert r["median_days_to_detection"] == 6.0    # end of the first alerting week


def test_missed_outbreak():
    r = score(_signals([3]), TRUTH, "ears_stat", h=3.0, min_cases=5)
    assert r["detected"] == 0
    assert r["sensitivity"] == 0.0
    assert r["median_days_to_detection"] is None


def test_higher_threshold_never_gives_more_alerts():
    sig = _signals([3, 10, 11])
    sig.loc[11, "ears_stat"] = 4.0
    counts = [score(sig, TRUTH, "ears_stat", h, 5)["alerts"] for h in (1.0, 3.0, 5.0, 20.0)]
    assert counts == sorted(counts, reverse=True)
    assert counts[-1] == 0


def test_small_counts_never_alert():
    sig = _signals([10])
    sig["x"] = 2.0
    r = score(sig, TRUTH, "ears_stat", h=3.0, min_cases=5)
    assert r["alerts"] == 0
