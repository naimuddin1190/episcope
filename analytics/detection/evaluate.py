"""Evaluation of outbreak detection against the injected ground truth (AN-2, AN-3, conflict C1).

This is the ONLY analytics module that reads data/ground_truth/, and it runs after detection.

Metrics (evaluated on mature weeks from the second year onwards, so both methods have history):
  * sensitivity           share of injected outbreak episodes (per district) with >= 1 alert
                          between start and end
  * false alerts          alert weeks outside every outbreak window (+2 weeks grace), per district-year
  * median days to detect days from outbreak start to the end of the first alerting week
The threshold trade-off curve (C1) is produced for both methods, and the operating point with the
highest sensitivity subject to <= MAX_FALSE false alerts per district-year is written to
gold/detection_settings.json for the next run.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from common import config
from common.spark import get_spark

THRESHOLDS = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0]
MAX_FALSE = 1.0  # tolerated false alerts per district-year (all four diseases together)
EVAL_OUT = config.GOLD / "evaluation"


def load_truth() -> pd.DataFrame:
    files = sorted(config.GROUND_TRUTH.glob("ground_truth_outbreaks*.csv"))
    truth = pd.concat([pd.read_csv(f) for f in files], ignore_index=True) if files else pd.DataFrame()
    if len(truth):
        truth["start_date"] = pd.to_datetime(truth.start_date)
        truth["end_date"] = pd.to_datetime(truth.end_date)
    return truth


def score(sig: pd.DataFrame, truth: pd.DataFrame, stat: str, h: float, min_cases: float) -> dict:
    s = sig.copy()
    s["alert"] = (s[stat] > h) & (s["x"] >= min_cases)
    s["week_end"] = s.week_start + pd.Timedelta(days=6)
    alerts = s[s.alert]
    # match alerts to outbreak windows
    in_window = np.zeros(len(alerts), dtype=bool)
    detected, delays = 0, []
    eval_start, eval_end = s.week_start.min(), s.week_end.max()
    tr = truth[(truth.start_date >= eval_start) & (truth.start_date <= eval_end - pd.Timedelta(days=14))]
    a_d, a_k = alerts.district_code.to_numpy(), alerts.disease.to_numpy()
    a_ws, a_we = alerts.week_start.to_numpy(), alerts.week_end.to_numpy()
    for o in tr.itertuples():
        m = (a_d == o.district_code) & (a_k == o.disease) & (a_we >= np.datetime64(o.start_date)) & \
            (a_ws <= np.datetime64(o.end_date + pd.Timedelta(days=14)))
        in_window |= m
        hits = m & (a_ws <= np.datetime64(o.end_date))
        if hits.any():
            detected += 1
            delays.append(max(0, (pd.Timestamp(a_we[hits].min()) - o.start_date).days))
    n_district_years = s.district_code.nunique() * ((eval_end - eval_start).days / 365.25)
    false = int((~in_window).sum())
    return dict(threshold=h, sensitivity=round(detected / len(tr), 4) if len(tr) else None,
                outbreaks=int(len(tr)), detected=int(detected),
                false_alerts=false, false_per_district_year=round(false / n_district_years, 3),
                median_days_to_detection=float(np.median(delays)) if delays else None, alerts=int(len(alerts)))


def run() -> None:
    spark = get_spark("episcope-evaluation")
    truth = load_truth()
    if truth.empty:
        print("[evaluation] no ground truth found - skipped")
        return
    EVAL_OUT.mkdir(parents=True, exist_ok=True)
    from analytics.detection.detect import settings
    st = settings()
    sig = spark.read.parquet(str(config.GOLD / "detection_signals")).toPandas()
    sig["week_start"] = pd.to_datetime(sig.week_start)
    first_year = sig.week_start.min() + pd.Timedelta(days=365)
    sig = sig[(sig.mature) & (sig.week_start >= first_year)]

    curve = []
    for method, stat in (("ears_c2", "ears_stat"), ("historical_limits", "hl_stat")):
        for h in THRESHOLDS:
            curve.append({"method": method, **score(sig, truth, stat, h, st["min_cases"])})
    curve = pd.DataFrame(curve)
    ok = curve[curve.false_per_district_year <= MAX_FALSE]
    best = (ok.sort_values(["sensitivity", "false_per_district_year"], ascending=[False, True]).iloc[0]
            if len(ok) else curve.sort_values("false_per_district_year").iloc[0])
    rec = {"method": best.method, "threshold": float(best.threshold), "min_cases": st["min_cases"],
           "chosen_by": f"max sensitivity with <= {MAX_FALSE} false alerts per district-year"}
    (config.GOLD / "detection_settings.json").write_text(json.dumps(rec, indent=1))
    # re-flag the stored signals with the chosen operating point
    allsig = spark.read.parquet(str(config.GOLD / "detection_signals")).toPandas()
    st_col = "ears_stat" if rec["method"] == "ears_c2" else "hl_stat"
    allsig["alert"] = ((allsig[st_col] > rec["threshold"]) & (allsig["x"] >= rec["min_cases"])).fillna(False)
    allsig["method"], allsig["threshold"] = rec["method"], rec["threshold"]
    spark.createDataFrame(allsig).write.mode("overwrite").parquet(str(config.GOLD / "detection_signals"))

    # per-disease breakdown at the chosen operating point
    stat = "ears_stat" if rec["method"] == "ears_c2" else "hl_stat"
    per_dis = [{"disease": d, **score(sig[sig.disease == d], truth[truth.disease == d], stat, rec["threshold"],
                                      rec["min_cases"])} for d in config.DISEASES]
    # per outbreak type: only sensitivity and delay are meaningful (false alerts need all outbreaks)
    keep = ("sensitivity", "outbreaks", "detected", "median_days_to_detection")
    per_kind = [{"kind": k, **{x: v for x, v in score(sig, truth[truth.kind == k], stat, rec["threshold"],
                                                       rec["min_cases"]).items() if x in keep}}
                for k in truth.kind.unique()]

    # AN-3: the reporting artefact - naive detector on REPORT weeks vs ours on ONSET weeks
    art_rows = []
    for f in sorted(config.GROUND_TRUTH.glob("artefacts*.csv")):
        art = pd.read_csv(f)
        naive = spark.read.parquet(str(config.GOLD / "detection_signals_naive")).toPandas()
        naive["week_start"] = pd.to_datetime(naive.week_start)
        allsig = spark.read.parquet(str(config.GOLD / "detection_signals")).toPandas()
        allsig["week_start"] = pd.to_datetime(allsig.week_start)
        dist = pd.read_parquet(config.SILVER / "districts")
        for a in art.itertuples():
            code = dist.loc[dist.district == a.district, "district_code"].iloc[0]
            lo, hi = pd.Timestamp(a.silence_start), pd.Timestamp(a.backfill_date) + pd.Timedelta(days=7)
            bf_week = pd.Timestamp(a.backfill_date) - pd.Timedelta(days=pd.Timestamp(a.backfill_date).dayofweek)
            for name, frame in (("naive_report_week", naive), ("episcope_onset_week", allsig)):
                w = frame[(frame.district_code == code) & frame.week_start.between(lo, hi)]
                w = w.assign(alert=(w[stat] > rec["threshold"]) & (w.x >= rec["min_cases"]))
                # an alert is only a false alarm if no real outbreak covers it
                tw = truth[(truth.district_code == code)]
                fa = 0
                for r in w[w.alert].itertuples():
                    if not ((tw.disease == r.disease) & (tw.start_date <= r.week_start + pd.Timedelta(days=6))
                            & (tw.end_date + pd.Timedelta(days=14) >= r.week_start)).any():
                        fa += 1
                art_rows.append(dict(detector=name, district=a.district, facility_id=a.facility_id,
                                     backfill_date=a.backfill_date, alerts_in_window=int(w.alert.sum()),
                                     false_alerts_in_window=fa,
                                     max_stat=round(float(w[stat].max()), 2) if len(w) else None,
                                     max_stat_in_backfill_week=round(float(w.loc[w.week_start == bf_week, stat].max()), 2)
                                     if (w.week_start == bf_week).any() else None,
                                     # would a typical default threshold of 3 have raised a false alarm?
                                     false_alarm_at_threshold_3=bool((w.loc[w.week_start == bf_week, stat] > 3).any())))
    result = dict(operating_point=rec, curve=curve.to_dict("records"), per_disease=per_dis, per_kind=per_kind,
                  artefact=art_rows)
    (EVAL_OUT / "detection_evaluation.json").write_text(json.dumps(result, indent=1, default=str))
    curve.to_csv(config.EXPERIMENTS / "detection_tradeoff_curve.csv", index=False)
    print(curve.to_string(index=False))
    print("[evaluation] operating point:", rec)
    print(pd.DataFrame(art_rows).to_string(index=False))


if __name__ == "__main__":
    run()
