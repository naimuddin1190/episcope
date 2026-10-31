"""Demand conversion (AN-6), allocation optimiser (AN-7) and efficiency-equity curve (AN-8, C3).

Linear programme (Section 6.3), solved with PuLP/CBC:

    min   sum_{d,r} w_d * u_{d,r} / Y_r                      (weighted unmet demand, normalised per
                                                             resource so bags and sachets are comparable)
    s.t.  u_{d,r} >= yhat_{d,r} - s_{d,r} - x_{d,r}          (unmet demand)
          sum_{d,r} c_r x_{d,r} <= B                         (budget)
          x_{d,r} >= alpha * p_d * sum_{d'} x_{d',r}         (equity floor)
          sum_{d in div k} sum_r v_r x_{d,r} <= T_k          (transport capacity per division)
          x, u >= 0

yhat = upper (90%) forecast quantile of resource demand over the next 4 weeks; s = latest stock.
Baseline for comparison: the same budget split by population share.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pulp

from analytics.optimise import assumptions as A
from common import config
from common.spark import get_spark

R = A.RESOURCES


def load_inputs(spark):
    meta = json.loads((config.META / "gold_meta.json").read_text())
    cutoff = pd.Timestamp(meta["data_cutoff"])
    fc = spark.read.parquet(str(config.GOLD / "forecasts")).where("kind = 'forecast'").toPandas()
    fc["target_week"] = pd.to_datetime(fc.target_week)
    cutoff_week = cutoff - pd.Timedelta(days=cutoff.dayofweek)
    weeks = sorted(fc.loc[fc.target_week > cutoff_week, "target_week"].unique())[: A.PLANNING_WEEKS]
    fc = fc[fc.target_week.isin(weeks)]
    wk = pd.read_parquet(config.GOLD / "weekly_cases")
    wk["week_start"] = pd.to_datetime(wk.week_start)
    wk = wk[wk.mature]
    recent = wk[wk.week_start > wk.week_start.max() - pd.Timedelta(weeks=52)]
    rates = recent.groupby(["district_code", "disease"])[["admitted", "cases"]].sum()
    national = recent.groupby("disease")[["admitted", "cases"]].sum()
    rates["adm_rate"] = np.where(rates.cases >= 20, rates.admitted / rates.cases.clip(lower=1),
                                 (national.admitted / national.cases).reindex(rates.index.get_level_values(1)).to_numpy())
    dist = pd.read_parquet(config.SILVER / "districts")
    stock = pd.read_parquet(config.GOLD / "stock_latest") if (config.GOLD / "stock_latest").exists() else pd.DataFrame()
    sig = pd.read_parquet(config.GOLD / "detection_signals")
    sig["week_start"] = pd.to_datetime(sig.week_start)
    last = sig.week_start.max()
    active = sig[(sig.week_start > last - pd.Timedelta(weeks=3)) & sig.alert].groupby("district_code").size()
    return cutoff, weeks, fc, rates.reset_index(), dist, stock, active


def demand_table(fc, rates, dist) -> pd.DataFrame:
    tot = fc.groupby(["district_code", "disease"])[["q100", "q500", "q900"]].sum().reset_index()
    tot = tot.merge(rates[["district_code", "disease", "adm_rate"]], on=["district_code", "disease"], how="left")
    tot["adm_rate"] = tot.adm_rate.fillna(tot.groupby("disease").adm_rate.transform("mean"))
    rows = []
    for d in dist.district_code:
        g = tot[tot.district_code == d].set_index("disease")
        rec = {"district_code": d}
        for q in ("q100", "q500", "q900"):
            cases = {k: float(g.loc[k, q]) if k in g.index else 0.0 for k in config.FORECAST_DISEASES}
            adm = {k: cases[k] * (float(g.loc[k, "adm_rate"]) if k in g.index else 0.0) for k in cases}
            rec[f"dengue_cases_{q}"] = cases["dengue"]
            rec[f"diarrhoea_cases_{q}"] = cases["diarrhoea"]
            rec[f"admissions_{q}"] = sum(adm.values())
            rec[f"beds_needed_{q}"] = sum(adm[k] * A.LENGTH_OF_STAY_DAYS[k] for k in adm) / (7 * A.PLANNING_WEEKS)
            rec[f"iv_saline_{q}"] = sum(adm[k] * A.IV_SALINE_PER_ADMISSION[k] for k in adm)
            rec[f"ns1_kits_{q}"] = cases["dengue"] * A.NS1_KITS_PER_DENGUE_CASE
            rec[f"ors_{q}"] = cases["diarrhoea"] * A.ORS_PER_DIARRHOEA_CASE
        rows.append(rec)
    return pd.DataFrame(rows).round(1)


def solve(need, stock, pop_share, weight, division, budget, alpha, transport_cap):
    D = list(need.index)
    prob = pulp.LpProblem("episcope_allocation", pulp.LpMinimize)
    x = pulp.LpVariable.dicts("x", (D, R), lowBound=0)
    u = pulp.LpVariable.dicts("u", (D, R), lowBound=0)
    Y = {r: max(float(need[r].sum()), 1.0) for r in R}
    prob += pulp.lpSum(weight[d] * u[d][r] / Y[r] for d in D for r in R)
    for d in D:
        for r in R:
            prob += u[d][r] >= float(need.at[d, r]) - float(stock.at[d, r]) - x[d][r]
            if alpha > 0:
                prob += x[d][r] >= alpha * pop_share[d] * pulp.lpSum(x[e][r] for e in D)
    prob += pulp.lpSum(A.UNIT_COST_BDT[r] * x[d][r] for d in D for r in R) <= budget
    for k, cap in transport_cap.items():
        prob += pulp.lpSum(A.UNIT_VOLUME_L[r] * x[d][r] for d in D if division[d] == k for r in R) <= cap
    prob.solve(pulp.PULP_CBC_CMD(msg=False))
    status = pulp.LpStatus[prob.status]
    alloc = pd.DataFrame({r: [max(0.0, x[d][r].value() or 0.0) for d in D] for r in R}, index=D)
    return alloc, status


def evaluate(alloc, need, stock, weight):
    unmet = (need - stock - alloc).clip(lower=0)
    Y = need.sum().clip(lower=1)
    cover = ((stock + alloc) / need.where(need > 0)).clip(upper=1)
    district_cover = cover.mean(axis=1, skipna=True)
    has_need = (need > 0).any(axis=1)
    c = district_cover[has_need].sort_values().to_numpy()
    n = len(c)
    gini = float((2 * np.arange(1, n + 1) - n - 1).dot(c) / (n * c.sum())) if n and c.sum() > 0 else 0.0
    return dict(weighted_unmet=round(float((unmet.div(Y, axis=1).mul(weight, axis=0)).sum().sum()), 4),
                unmet_share=round(float(unmet.sum().sum() / need.sum().sum()), 4) if need.sum().sum() else 0.0,
                min_district_coverage=round(float(district_cover[has_need].min()), 4) if has_need.any() else 1.0,
                districts_with_nothing=int(((alloc.sum(axis=1) <= 0.5) & has_need).sum()),
                coverage_gini=round(gini, 4),
                cost_bdt=round(float(sum(alloc[r].sum() * A.UNIT_COST_BDT[r] for r in R)), 0))


def run() -> None:
    spark = get_spark("episcope-allocation")
    cutoff, weeks, fc, rates, dist, stock_tbl, active = load_inputs(spark)
    demand = demand_table(fc, rates, dist)
    D = dist.district_code.tolist()
    need = demand.set_index("district_code")[[f"{r}_{A.PLANNING_QUANTILE}" for r in R]].set_axis(R, axis=1).reindex(D).fillna(0)
    if len(stock_tbl):
        st = stock_tbl.set_index("district_code")
        stock = st[R].reindex(D).fillna(0).astype(float)
        occ = (st.occupied_beds / st.beds.clip(lower=1)).reindex(D).fillna(0)
    else:
        stock = pd.DataFrame(0.0, index=D, columns=R)
        occ = pd.Series(0.0, index=D)
    pop = dist.set_index("district_code").population.reindex(D)
    pop_share = (pop / pop.sum()).to_dict()
    division = dist.set_index("district_code").division.to_dict()
    weight = (1 + A.ALERT_WEIGHT * pd.Series(D, index=D).map(lambda d: d in active.index).astype(float)
              + A.OCCUPANCY_WEIGHT * (occ > 0.85).astype(float))
    gap = (need - stock).clip(lower=0)
    full_cost = float(sum(gap[r].sum() * A.UNIT_COST_BDT[r] for r in R))
    vol = (gap * pd.Series(A.UNIT_VOLUME_L)).sum(axis=1)
    div_need = vol.groupby(pd.Series(division)).sum()
    div_pop = pop.groupby(pd.Series(division)).sum()
    share = 0.5 * div_need / max(div_need.sum(), 1e-9) + 0.5 * div_pop / div_pop.sum()

    def transport(budget_share):
        return (A.TRANSPORT_SLACK * share * max(vol.sum(), 1.0) * max(budget_share, 0.05)).to_dict()

    def baseline(budget):
        cost_share = {r: gap[r].sum() * A.UNIT_COST_BDT[r] / max(full_cost, 1e-9) for r in R}
        return pd.DataFrame({r: [budget * cost_share[r] / A.UNIT_COST_BDT[r] * pop_share[d] for d in D] for r in R}, index=D)

    scen, curve = [], []
    for b in A.BUDGET_LEVELS:
        budget = b * full_cost
        for alpha in A.ALPHA_LEVELS:
            alloc, status = solve(need, stock, pop_share, weight, division, budget, alpha, transport(b))
            ev = evaluate(alloc, need, stock, weight)
            curve.append(dict(budget_share=b, budget_bdt=round(budget), alpha=alpha, method="optimiser", status=status, **ev))
            for d in D:
                scen.append(dict(budget_share=b, alpha=alpha, district_code=d,
                                 **{r: round(float(alloc.at[d, r]), 1) for r in R}))
        bl = baseline(budget)
        curve.append(dict(budget_share=b, budget_bdt=round(budget), alpha=None, method="population_proportional",
                          status="n/a", **evaluate(bl, need, stock, weight)))
        for d in D:
            scen.append(dict(budget_share=b, alpha=-1.0, district_code=d, **{r: round(float(bl.at[d, r]), 1) for r in R}))
    curve = pd.DataFrame(curve)
    scen = pd.DataFrame(scen)

    # recommended policy: the default budget; smallest alpha whose min coverage is within 5 points of the
    # best achievable equity, while weighted unmet demand rises by at most 10% vs. alpha = 0
    cb = curve[(curve.method == "optimiser") & np.isclose(curve.budget_share, A.DEFAULT_BUDGET_SHARE)]
    base_obj = float(cb.loc[cb.alpha == 0, "weighted_unmet"].iloc[0])
    ok = cb[cb.weighted_unmet <= base_obj * 1.10 + 1e-9]
    rec_alpha = float(ok.sort_values(["min_district_coverage", "alpha"], ascending=[False, True]).alpha.iloc[0]) if len(ok) else A.DEFAULT_ALPHA

    sel = scen[np.isclose(scen.budget_share, A.DEFAULT_BUDGET_SHARE) & np.isclose(scen.alpha, rec_alpha)].set_index("district_code")[R]
    bl = scen[np.isclose(scen.budget_share, A.DEFAULT_BUDGET_SHARE) & (scen.alpha == -1)].set_index("district_code")[R]
    alloc_tbl = demand.set_index("district_code").join(stock.add_prefix("stock_")).join(sel.add_prefix("alloc_")) \
        .join(bl.add_prefix("baseline_")).join(weight.rename("weight")).join(occ.rename("bed_occupancy")).reset_index()
    alloc_tbl = alloc_tbl.merge(dist[["district_code", "district", "division", "population"]], on="district_code")

    out = config.GOLD
    alloc_tbl.to_parquet(out / "allocation.parquet", index=False)
    scen.to_parquet(out / "allocation_scenarios.parquet", index=False)
    summary = dict(planning_weeks=[str(pd.Timestamp(w).date()) for w in weeks], data_cutoff=str(cutoff.date()),
                   full_need_cost_bdt=round(full_cost), default_budget_share=A.DEFAULT_BUDGET_SHARE,
                   recommended_alpha=rec_alpha,
                   comparison=curve[np.isclose(curve.budget_share, A.DEFAULT_BUDGET_SHARE)
                                    & (curve.alpha.isna() | np.isclose(curve.alpha.fillna(-1), rec_alpha))].to_dict("records"),
                   curve=curve.to_dict("records"),
                   assumptions={k: getattr(A, k) for k in dir(A) if k.isupper()})
    (out / "evaluation").mkdir(parents=True, exist_ok=True)
    (out / "evaluation" / "allocation.json").write_text(json.dumps(summary, indent=1, default=str))
    curve.to_csv(config.EXPERIMENTS / "efficiency_equity_curve.csv", index=False)
    print(curve[np.isclose(curve.budget_share, A.DEFAULT_BUDGET_SHARE)].to_string(index=False))
    print(f"[allocation] recommended alpha = {rec_alpha}")


if __name__ == "__main__":
    run()
