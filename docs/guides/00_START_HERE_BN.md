# শুরু এখান থেকে (তিনজনের জন্য)

## ১. GitHub-এ কীভাবে push করবে (প্রত্যেকে নিজের account থেকে)
Commit message-এ requirement ID লিখতে হবে (assignment-এর শর্ত)। নিচের ক্রমে, **ছোট ছোট commit**-এ:

**Naim (প্রথমে, repo বানিয়ে):**
```bash
git init && git add README.md Makefile requirements.txt .gitignore .env.example common/ orchestration/
git commit -m "ENG-1: repo skeleton, pinned requirements, Makefile, orchestration DAG"
git add reference/ generator/ && git commit -m "ING-1: synthetic generator S4-S6, weather fetch S3, reference data S1-S2"
git add pipeline/contracts.py pipeline/bronze/ && git commit -m "ING-1, ING-4: bronze ingestion with checksum idempotency"
git add pipeline/quality/ pipeline/silver/ && git commit -m "DQ-1, DQ-2, PRV-1: quality rules, quarantine, de-identification"
git add pipeline/gold/ pipeline/__init__.py && git commit -m "ING-3, DQ-3: gold marts with lineage and incremental rebuild"
git add scripts/ Dockerfile docker-compose.yml && git commit -m "ENG-2, ENG-3: scaling and optimisation experiments"
git branch -M main && git remote add origin <repo-url> && git push -u origin main
```
**Shamraj** (repo clone করে, নিজের account-এ): `analytics/detection` → `analytics/forecast` → `analytics/optimise` → `analytics/calendar` আলাদা আলাদা commit (`AN-1, AN-2, AN-3: ...` ইত্যাদি)।
**Ratul** (GitHub website → Add file → Upload files, বা GitHub Desktop): `serving/` (`PRV-2, VIS-4: ...`), তারপর `dashboard/` (`VIS-1..VIS-6: ...`), পরে `tests/test_suppression.py`।
তারপর সবাই নিজের guide-এর পরিবর্তন/অন্যের অংশে ছোট commit (role-এর বাইরে)।

> ⚠️ `.env`, `data/` কখনো push করবে না (`.gitignore`-এ আছে)। শেষে `git tag v1.0 && git push --tags`।
> ⚠️ commit-এর তারিখ পরিবর্তন বা অন্যের নামে commit করবে না। ইতিহাস যা, তাই সৎভাবে রাখো; reflection-এ লিখতে পারো যে সময় কম ছিল।

## ২. প্রথমবার চালানো (Naim-এর PC)
```bash
cd ~/episcope && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
make all            # প্রথমবার: .env তৈরি, weather download, generate (SF=0.05), pipeline
make test           # 29টা test pass হওয়া উচিত
make serve          # http://localhost:8000
```
সমস্যা হলে: `JAVA_HOME` ঠিক আছে কিনা (`java -version` → 17), RAM কম হলে `.env`-এ `SPARK_DRIVER_MEMORY=4g`।

## ৩. Report আর video-র জন্য সংখ্যা কোথা থেকে নেবে
| দরকার | ফাইল |
|---|---|
| Detection trade-off curve (C1) | `docs/experiments/detection_tradeoff_curve.csv` |
| Forecast backtest (MAE, coverage, WIS) | `docs/experiments/forecast_backtest_metrics.csv` |
| Efficiency–equity (C3) | `docs/experiments/efficiency_equity_curve.csv` |
| Optimizer vs baseline, artefact | `data/lake/gold/evaluation/*.json` |
| Scaling ও optimization সময় | `docs/experiments/scaling_summary.md` |
| Data quality | dashboard-এর "Data quality" panel |

## ৪. এখনো যা বাকি (তোমাদের নিজেদের কাজ)
- [ ] Naim: SF=1 run + scaling + Spark UI screenshot; README-তে video link
- [ ] Ratul: ২ জন non-CS user test, ফিডব্যাক লেখা
- [ ] সবাই: report-এর নিজের section, ½ পেজ reflection, contribution matrix সই
- [ ] Shamraj: policy brief, video জোড়া লাগানো ও YouTube Unlisted upload
- [ ] `AI_USAGE.md`-এ নিজেদের পরিবর্তনগুলো সৎভাবে লেখা
- [ ] `git tag v1.0`
