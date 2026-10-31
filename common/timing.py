"""Stage timer: every stage appends its runtime to docs/experiments/stage_timings.jsonl (ENG-2)."""
from __future__ import annotations

import json
import os
import platform
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from common import config


@contextmanager
def stage(name: str, **extra):
    t0 = time.time()
    print(f"\n=== [{name}] start {datetime.now().strftime('%H:%M:%S')}", flush=True)
    status = "ok"
    try:
        yield
    except Exception:
        status = "failed"
        raise
    finally:
        dt = time.time() - t0
        print(f"=== [{name}] {status} in {dt:,.1f}s", flush=True)
        config.EXPERIMENTS.mkdir(parents=True, exist_ok=True)
        rec = {
            "stage": name,
            "seconds": round(dt, 2),
            "status": status,
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "run_label": os.environ.get("EPISCOPE_RUN_LABEL", "default"),
            "sf": os.environ.get("EPISCOPE_SF"),
            "opt": os.environ.get("EPISCOPE_OPT", "1"),
            "host": platform.node(),
            "cpus": os.cpu_count(),
            **extra,
        }
        with open(config.EXPERIMENTS / "stage_timings.jsonl", "a") as fh:
            fh.write(json.dumps(rec) + "\n")
