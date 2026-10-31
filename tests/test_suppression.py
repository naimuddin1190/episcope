"""PRV-2: no count 1-4 is published and no suppressed cell is recoverable from published totals."""
import numpy as np

from serving.suppression import SUPPRESSED, check, suppress


def test_primary_and_complementary_suppression():
    m = np.array([[3, 10, 0], [20, 2, 0], [7, 8, 4], [50, 60, 9]])
    groups = [np.array([0, 1]), np.array([2, 3]), np.arange(4)]
    pub = suppress(m, groups)
    check(pub, m, groups)
    vis = pub[pub != SUPPRESSED]
    assert not ((vis >= 1) & (vis <= 4)).any()
    # column 0: one small cell in group 0 -> its partner is hidden too
    assert pub[0, 0] == SUPPRESSED and pub[1, 0] == SUPPRESSED


def test_random_matrices():
    rng = np.random.default_rng(1)
    for _ in range(50):
        m = rng.poisson(rng.uniform(0.5, 20), size=(12, 30))
        groups = [np.arange(0, 5), np.arange(5, 12), np.arange(12)]
        check(suppress(m, groups), m, groups)
