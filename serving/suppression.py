"""Small-cell suppression (PRV-2, conflict C2).

Policy
  1. Primary suppression: any count from 1 to 4 is replaced by SUPPRESSED (-1).
  2. Complementary suppression: every published total (each division and the nation, per week)
     must not let a suppressed cell be recovered by subtraction. If a total contains exactly one
     suppressed cell, the smallest other non-zero cell in that total is suppressed as well.
     This is repeated until no total contains exactly one suppressed cell.
Zero is published (a true zero is not identifying). Totals themselves are published exactly.
"""
from __future__ import annotations

import numpy as np

SUPPRESSED = -1
MIN_CELL = 5


def suppress(matrix: np.ndarray, groups: list[np.ndarray]) -> np.ndarray:
    """matrix: districts x weeks of counts. groups: list of row-index arrays whose totals are
    published (divisions + the whole nation). Returns a copy with suppressed cells = -1."""
    m = np.asarray(matrix, dtype=float).copy()
    supp = (m >= 1) & (m < MIN_CELL)
    changed = True
    while changed:
        changed = False
        for rows in groups:
            sub = supp[rows]                          # (rows, weeks)
            single = sub.sum(axis=0) == 1             # weeks where exactly one cell is hidden
            for w in np.where(single)[0]:
                vals = m[rows, w].copy()
                vals[sub[:, w]] = np.inf
                cand = np.where(vals > 0, vals, np.inf)   # prefer a non-zero partner
                if np.isinf(cand).all():
                    cand = vals                           # only zeros left: hide a zero
                if np.isinf(cand).all():
                    continue
                j = rows[int(np.argmin(cand))]
                supp[j, w] = True
                changed = True
    out = m.copy()
    out[supp] = SUPPRESSED
    return out


def check(published: np.ndarray, original: np.ndarray, groups: list[np.ndarray]) -> None:
    """Assertions used by the tests and by the exporter before anything is written."""
    vis = published[published != SUPPRESSED]
    assert not ((vis >= 1) & (vis < MIN_CELL)).any(), "a count between 1 and 4 would be published"
    for rows in groups:
        n_hidden = (published[rows] == SUPPRESSED).sum(axis=0)
        assert not (n_hidden == 1).any(), "a suppressed cell could be recovered from a published total"
