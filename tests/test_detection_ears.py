"""Testing & QA (Puja Dey): EARS C2 outbreak detection in Spark (AN-1)."""
import datetime as dt

from pyspark.sql import Row

from analytics.detection.detect import ears_c2


def _weeks(n):
    start = dt.date(2024, 1, 1)
    return [start + dt.timedelta(days=7 * i) for i in range(n)]


def _run(spark, series):
    rows = [Row(district_code=d, disease="dengue", week_start=w, x=float(v))
            for d, values in series.items() for w, v in zip(_weeks(len(values)), values)]
    out = ears_c2(spark.createDataFrame(rows)).orderBy("district_code", "week_start").toPandas()
    return {d: g.reset_index(drop=True) for d, g in out.groupby("district_code")}


def test_no_statistic_without_enough_history(spark):
    out = _run(spark, {"D1": [10] * 12})["D1"]
    assert out.ears_stat.iloc[:7].isna().all()      # fewer than 5 baseline weeks
    assert out.ears_stat.iloc[7:].notna().all()


def test_flat_series_gives_no_signal(spark):
    out = _run(spark, {"D1": [10] * 20})["D1"]
    assert (out.ears_stat.dropna().abs() < 1e-9).all()


def test_sudden_spike_is_flagged(spark):
    out = _run(spark, {"D1": [10] * 15 + [60]})["D1"]
    assert out.ears_stat.iloc[-1] > 3


def test_guard_band_keeps_a_three_week_outbreak_visible(spark):
    # the baseline skips the two most recent weeks, so the outbreak does not hide itself
    out = _run(spark, {"D1": [10] * 15 + [60, 60, 60]})["D1"]
    assert (out.ears_stat.iloc[15:18] > 3).all()


def test_districts_do_not_affect_each_other(spark):
    out = _run(spark, {"D1": [10] * 15 + [60], "D2": [10] * 16})
    assert out["D1"].ears_stat.iloc[-1] > 3
    assert abs(out["D2"].ears_stat.iloc[-1]) < 1e-9
