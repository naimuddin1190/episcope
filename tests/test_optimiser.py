"""AN-7: the allocation respects budget, equity floor and transport constraints."""
import numpy as np
import pandas as pd

from analytics.optimise import assumptions as A
from analytics.optimise.allocate import R, solve


def problem():
    D = ["d1", "d2", "d3", "d4"]
    need = pd.DataFrame({"iv_saline": [100, 10, 0, 40], "ns1_kits": [50, 0, 5, 10], "ors": [400, 100, 50, 0]}, index=D)
    stock = pd.DataFrame({"iv_saline": [20, 10, 0, 0], "ns1_kits": [0, 0, 0, 0], "ors": [100, 0, 0, 0]}, index=D)
    pop = {"d1": 0.4, "d2": 0.3, "d3": 0.2, "d4": 0.1}
    weight = pd.Series([3.0, 1, 1, 1], index=D)
    division = {"d1": "A", "d2": "A", "d3": "B", "d4": "B"}
    return need, stock, pop, weight, division


def test_constraints_hold():
    need, stock, pop, weight, division = problem()
    budget, alpha = 10_000, 0.3
    cap = {"A": 1e9, "B": 30.0}
    x, status = solve(need, stock, pop, weight, division, budget, alpha, cap)
    assert status == "Optimal"
    cost = sum(x[r].sum() * A.UNIT_COST_BDT[r] for r in R)
    assert cost <= budget + 1e-6
    for r in R:
        tot = x[r].sum()
        for d in x.index:
            assert x.at[d, r] >= alpha * pop[d] * tot - 1e-6
    vol_b = sum(A.UNIT_VOLUME_L[r] * x.loc[["d3", "d4"], r].sum() for r in R)
    assert vol_b <= 30.0 + 1e-6
    assert (x >= -1e-9).all().all()


def test_no_budget_means_no_allocation():
    need, stock, pop, weight, division = problem()
    x, status = solve(need, stock, pop, weight, division, 0, 0.0, {"A": 1e9, "B": 1e9})
    assert np.isclose(x.values.sum(), 0)
