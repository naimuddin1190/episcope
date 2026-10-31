"""Summarise docs/experiments/stage_timings.jsonl into docs/experiments/scaling_summary.md (ENG-2/3)."""
import json
import platform
from pathlib import Path

import pandas as pd

EXP = Path(__file__).resolve().parents[1] / "docs" / "experiments"
def md(df):
    cols = [str(df.index.name or "")] + [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for idx, r in df.iterrows():
        lines.append("| " + " | ".join([str(idx)] + ["" if pd.isna(v) else str(v) for v in r]) + " |")
    return "\n".join(lines)


rows = [json.loads(l) for l in open(EXP / "stage_timings.jsonl")] if (EXP / "stage_timings.jsonl").exists() else []
df = pd.DataFrame(rows)
out = ["# Experiment summary", "", f"Machine: {platform.platform()}, {pd.Series([r.get('cpus') for r in rows]).max()} CPUs", ""]
if len(df):
    df = df[df.status.fillna("ok") == "ok"] if "status" in df else df
    last = df.groupby(["run_label", "stage"]).seconds.last().unstack(0).round(1)
    last.loc["TOTAL"] = last.sum().round(1)
    out += ["## Runtime per stage (seconds, last run of each label)", "", md(last), ""]
sizes = EXP / "output_sizes.tsv"
if sizes.exists():
    s = pd.read_csv(sizes, sep="\t", names=["sf", "path", "bytes"])
    s["MB"] = (s.bytes / 1e6).round(1)
    out += ["## Output sizes (MB)", "", md(s.pivot_table(index="path", columns="sf", values="MB", aggfunc="last")), ""]
(EXP / "scaling_summary.md").write_text("\n".join(out))
print("\n".join(out))
