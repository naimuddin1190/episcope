"""Serving layer: gold -> small, aggregated, suppressed JSON files for the D3 dashboard (VIS-4, PRV-2).

The browser only ever receives these aggregated files (checked to be < 10 MB in total); no
line-level record and no count between 1 and 4 is ever exported.
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from common import config
from serving.suppression import SUPPRESSED, check, suppress

MAX_BYTES = 10 * 1024 * 1024


def _r(x, nd=1):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return None
    return round(float(x), nd)


def write(name: str, obj) -> int:
    path = config.SERVING_OUT / name
    txt = json.dumps(obj, separators=(",", ":"), default=str, allow_nan=False)
    path.write_text(txt)
    return len(txt.encode())


def clean(v):
    """Replace NaN/inf with None recursively (JSON has no NaN)."""
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, list):
        return [clean(x) for x in v]
    if isinstance(v, float) and not np.isfinite(v):
        return None
    if isinstance(v, (np.floating,)):
        return clean(float(v))
    if isinstance(v, (np.integer,)):
        return int(v)
    return v


def run() -> None:
    out = config.SERVING_OUT
    out.mkdir(parents=True, exist_ok=True)
    meta_g = json.loads((config.META / "gold_meta.json").read_text())
    det = json.loads((config.GOLD / "detection_settings.json").read_text()) if (config.GOLD / "detection_settings.json").exists() else {}
    dist = pd.read_parquet(config.SILVER / "districts").sort_values(["division", "district"]).reset_index(drop=True)
    codes = dist.district_code.tolist()
    divisions = sorted(dist.division.unique())
    groups = [dist.index[dist.division == d].to_numpy() for d in divisions] + [dist.index.to_numpy()]

    wk = pd.read_parquet(config.GOLD / "weekly_cases")
    wk["week_start"] = pd.to_datetime(wk.week_start)
    weeks = sorted(wk.week_start.unique())
    wstr = [pd.Timestamp(w).strftime("%Y-%m-%d") for w in weeks]
    sig = pd.read_parquet(config.GOLD / "detection_signals")
    sig["week_start"] = pd.to_datetime(sig.week_start)
    stat_col = "hl" if det.get("method") == "historical_limits" else "ears"
    first_immature = next((i for i, w in enumerate(weeks)
                           if not wk.loc[wk.week_start == w, "mature"].all()), len(weeks))

    sizes = {}
    total_sizes = 0
    weekly = {"weeks": wstr, "first_immature_index": first_immature, "district_order": codes,
              "divisions": divisions, "method": det.get("method", "ears_c2"), "diseases": {}}
    hidden_cells = 0
    for dis in config.DISEASES:
        piv = wk[wk.disease == dis].pivot_table(index="district_code", columns="week_start", values="cases",
                                                 aggfunc="sum").reindex(index=codes, columns=weeks).fillna(0)
        orig = piv.to_numpy()
        pub = suppress(orig, groups)
        check(pub, orig, groups)
        hidden_cells += int((pub == SUPPRESSED).sum())
        s = sig[sig.disease == dis]
        exp = s.pivot_table(index="district_code", columns="week_start", values=f"{stat_col}_expected").reindex(index=codes, columns=weeks)
        sg = s.pivot_table(index="district_code", columns="week_start", values=f"{stat_col}_sigma").reindex(index=codes, columns=weeks)
        st = s.pivot_table(index="district_code", columns="week_start", values=f"{stat_col}_stat").reindex(index=codes, columns=weeks)
        xx = s.pivot_table(index="district_code", columns="week_start", values="x").reindex(index=codes, columns=weeks)
        exp_v, sg_v, st_v, x_v = exp.to_numpy(), sg.to_numpy(), st.to_numpy(), xx.to_numpy()
        # model baselines below 5 are not shown (they are derived from small counts)
        small = ~(exp_v >= 5)
        nat = orig.sum(axis=0)
        weekly["diseases"][dis] = {
            "counts": [[None if not np.isfinite(v) else int(v) for v in row] for row in pub],
            "expected": [[None if small[i, j] else _r(exp_v[i, j]) for j in range(len(weeks))] for i in range(len(codes))],
            "sigma": [[None if small[i, j] else _r(sg_v[i, j], 2) for j in range(len(weeks))] for i in range(len(codes))],
            "stat": [[_r(v, 2) for v in row] for row in st_v],
            # "alertable": nowcast value >= min_cases, so the threshold slider can recompute alerts
            "alertable": [[1 if (np.isfinite(v) and v >= det.get("min_cases", 5)) else 0 for v in row] for row in x_v],
            "national": [int(v) for v in nat],
            "division": {d: [int(v) for v in orig[g].sum(axis=0)] for d, g in zip(divisions, groups[:-1])},
        }
    comp = wk[wk.disease == config.DISEASES[0]].pivot_table(index="district_code", columns="week_start",
                                                             values="completeness").reindex(index=codes, columns=weeks)
    weekly["completeness"] = [[_r(v, 2) for v in row] for row in comp.to_numpy()]
    sizes["weekly.json"] = write("weekly.json", clean(weekly))

    # districts + geometry
    sizes["districts.json"] = write("districts.json", dist[["district_code", "district", "division", "population"]].to_dict("records"))
    shutil.copy2(config.REFERENCE_DIR / "bd_districts.topo.json", out / "bd_districts.topo.json")
    sizes["bd_districts.topo.json"] = (out / "bd_districts.topo.json").stat().st_size

    # alerts (all alert weeks; observed counts suppressed where needed)
    a = sig[sig.alert].merge(dist[["district_code", "district", "division"]], on="district_code", how="left")
    a = a.sort_values(["week_start", f"{stat_col}_stat"], ascending=[False, False])
    alerts = [dict(district_code=r.district_code, district=r.district, division=r.division, disease=r.disease,
                   week=r.week_start.strftime("%Y-%m-%d"), observed=(int(r.cases) if r.cases >= 5 or r.cases == 0 else None),
                   nowcast=_r(r.x), expected=_r(getattr(r, f"{stat_col}_expected")), stat=_r(getattr(r, f"{stat_col}_stat"), 2),
                   provisional=not bool(r.mature)) for r in a.itertuples()]
    sizes["alerts.json"] = write("alerts.json", clean({"settings": det, "alerts": alerts}))

    # forecasts
    fc = pd.read_parquet(config.GOLD / "forecasts")
    fc = fc[fc.kind == "forecast"] if "kind" in fc.columns else fc
    qcols = [c for c in fc.columns if c.startswith("q") and c[1:].isdigit()]
    fc_out = {}
    for (d, dis), g in fc.groupby(["district_code", "disease"]):
        g = g.sort_values("target_week")
        fc_out.setdefault(d, {})[dis] = {
            "origin": str(pd.Timestamp(g.origin_week.iloc[0]).date()),
            "weeks": [str(pd.Timestamp(w).date()) for w in g.target_week],
            **{q: [_r(v) for v in g[q]] for q in qcols}, "point": [_r(v) for v in g.point]}
    bt = json.loads((config.GOLD / "evaluation" / "forecast_backtest.json").read_text())
    sizes["forecasts.json"] = write("forecasts.json", clean({"forecasts": fc_out, "backtest": bt}))

    # allocation
    alloc = pd.read_parquet(config.GOLD / "allocation.parquet")
    scen = pd.read_parquet(config.GOLD / "allocation_scenarios.parquet")
    asum = json.loads((config.GOLD / "evaluation" / "allocation.json").read_text())
    sizes["allocation.json"] = write("allocation.json", clean({
        "summary": {k: v for k, v in asum.items() if k != "curve"}, "curve": asum["curve"],
        "districts": json.loads(alloc.round(1).to_json(orient="records")),
        "scenarios": json.loads(scen.to_json(orient="records"))}))

    # calendar
    cal = pd.read_parquet(config.GOLD / "preparedness_calendar.parquet")
    prof = pd.read_parquet(config.GOLD / "seasonal_profiles.parquet")
    sizes["calendar.json"] = write("calendar.json", clean({
        "calendar": json.loads(cal.to_json(orient="records")),
        "profiles": json.loads(prof[["division", "disease", "epi_week", "seasonal"]].round(3).to_json(orient="records"))}))

    # data quality + lineage
    dq = pd.read_parquet(config.GOLD / "dq_report")
    man = pd.read_csv(config.META / "manifest.csv", dtype=str)
    batches = (man.groupby(["batch_id", "source", "status"]).agg(files=("file_name", "count"),
               rows=("rows", lambda s: int(pd.to_numeric(s).sum())), loaded_at=("loaded_at", "first")).reset_index())
    sizes["dq.json"] = write("dq.json", clean({"rules": json.loads(dq.to_json(orient="records")),
                                               "batches": json.loads(batches.to_json(orient="records"))}))

    det_eval = json.loads((config.GOLD / "evaluation" / "detection_evaluation.json").read_text()) \
        if (config.GOLD / "evaluation" / "detection_evaluation.json").exists() else {}
    sizes["evaluation.json"] = write("evaluation.json", clean({"detection": det_eval}))

    wea_src = pd.read_parquet(config.GOLD / "weekly_weather").weather_source.unique().tolist()
    meta = dict(generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                data_cutoff=meta_g["data_cutoff"], gold_built_at=meta_g["built_at"],
                detection=det, weather_sources=wea_src,
                suppression="Counts 1-4 hidden; complementary suppression so that no hidden cell can be recovered "
                            "from published division or national totals.",
                disclaimer="SYNTHETIC DATA - CSE 4345 teaching case. Not real patient data.",
                scale_factor=os.environ.get("EPISCOPE_SF"), suppressed_cells=hidden_cells)
    sizes["meta.json"] = write("meta.json", meta)
    total_sizes = sum(sizes.values())
    print({k: f"{v / 1024:.0f} KB" for k, v in sizes.items()}, f"total {total_sizes / 1024 / 1024:.2f} MB")
    assert total_sizes < MAX_BYTES, "dashboard data exceeds the 10 MB budget (VIS-4)"


if __name__ == "__main__":
    run()
