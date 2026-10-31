"""Testing & QA (Puja Dey): forecast intervals, WIS score and feature leakage (AN-4, AN-5)."""
import numpy as np
import pandas as pd

from analytics.forecast.forecast import QUANTILES, features, nb_quantiles, wis


def test_quantiles_have_right_shape_are_nonnegative_and_ordered():
    q = nb_quantiles(np.array([0.0, 5.0, 50.0]), 10.0)
    assert q.shape == (3, len(QUANTILES))
    assert (q >= 0).all()                       # never a negative case count
    assert (np.diff(q, axis=1) >= 0).all()      # 2.5% <= 10% <= ... <= 97.5%


def test_median_is_close_to_the_expected_value():
    q = nb_quantiles(np.array([50.0]), 10.0)[0]
    assert abs(q[QUANTILES.index(0.5)] - 50) <= 5


def test_more_dispersion_gives_wider_intervals():
    narrow = nb_quantiles(np.array([20.0]), 500.0)[0]
    wide = nb_quantiles(np.array([20.0]), 1.0)[0]
    assert (wide[-1] - wide[0]) > (narrow[-1] - narrow[0])


def test_wis_is_zero_for_a_perfect_forecast():
    y = np.array([7.0, 12.0])
    q = np.repeat(y[:, None], len(QUANTILES), axis=1)
    assert np.allclose(wis(y, q, y), 0.0)


def test_wis_penalises_a_wrong_forecast():
    y = np.array([10.0])
    good = np.array([[6, 7, 9, 10, 11, 13, 14]], dtype=float)
    bad = good + 20
    assert wis(y, bad, bad[:, 3])[0] > wis(y, good, good[:, 3])[0]


def _series(n=60):
    rng = np.random.default_rng(0)
    return pd.DataFrame({
        "week_start": pd.date_range("2023-01-02", periods=n, freq="7D"),
        "cases": rng.poisson(20, n).astype(float),
        "rain_mm": rng.gamma(2, 10, n),
        "temp_c": rng.normal(28, 2, n),
    })


def test_features_do_not_look_into_the_future():
    df = _series()
    before = features(df, h=2)
    df.loc[df.index[-1], ["cases", "rain_mm", "temp_c"]] = [999.0, 999.0, 99.0]
    after = features(df, h=2)
    # changing the newest week must not change any feature of an earlier week
    pd.testing.assert_frame_equal(before.iloc[:-1], after.iloc[:-1])


def test_seasonal_terms_lie_on_the_unit_circle():
    X = features(_series(), h=1)
    assert np.allclose(X["sin"] ** 2 + X["cos"] ** 2, 1.0)


def test_last_year_feature_needs_a_year_of_history():
    X = features(_series(), h=1)
    assert X["ly52"].iloc[:51].isna().all()
    assert X["ly52"].iloc[51:].notna().all()
