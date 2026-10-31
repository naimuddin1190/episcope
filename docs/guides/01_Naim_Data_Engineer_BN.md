# Naim – Data Engineer + Team Lead গাইড

## তোমার ফাইলগুলো
| ফাইল | কী করে |
|---|---|
| `generator/fetch_weather.py` | ৬৪ জেলার কেন্দ্রবিন্দুর জন্য Open-Meteo থেকে ৫ বছরের দৈনিক বৃষ্টি/তাপমাত্রা/আর্দ্রতা নামায়, কাঁচা JSON হুবহু cache করে (S3) |
| `generator/epi_model.py` | রোগের গাণিতিক মডেল: seasonality (von Mises curve), জেলাভেদে পার্থক্য, বৃষ্টির ৪–৮ সপ্তাহ lag, Negative Binomial noise |
| `generator/outbreaks.py` | ৩০+ outbreak ঢোকায় (local, ধীরে বাড়া একটা, দেশব্যাপী নতুন শ্বাসযন্ত্রের রোগ, ২০২৩ ডেঙ্গু), আর একটা artefact (হাসপাতাল ৩ সপ্তাহ চুপ, তারপর backfill) |
| `generator/facilities.py` | ৬০০+ হাসপাতাল/UHC/ক্লিনিক বানায় (S5) |
| `generator/generate.py` | সব মিলিয়ে encounters (দিনে একটা CSV), stock (দিনে একটা JSONL), ground truth লেখে। ২% duplicate, ০.৫% orphan, ১% ভুল মান ইচ্ছা করে |
| `pipeline/contracts.py` | কোন ফাইল কোন source তা **কলাম দেখে** চেনে (নাম দেখে না) |
| `pipeline/bronze/ingest.py` | নতুন ফাইল খুঁজে SHA-256 checksum দিয়ে চেনে; আগে load হয়ে থাকলে skip (idempotent)। batch_id, load time, checksum যোগ করে Parquet-এ লেখে |
| `pipeline/quality/rules.py` | ১৬টা encounter rule + ৪টা stock rule |
| `pipeline/silver/transform.py` | rule চালায়, খারাপ row quarantine-এ, patient_id → salted hash, বয়স → age band, facility broadcast join, epi-week |
| `pipeline/gold/build.py` | district × disease × week টেবিল, শুধু যে বছরগুলোতে নতুন/late ডেটা এসেছে সেগুলো আবার বানায় |
| `common/spark.py` | Spark session; ২টা optimization (broadcast join, AQE) `EPISCOPE_OPT` দিয়ে on/off |
| `orchestration/run_pipeline.py` | পুরো DAG, প্রতিটা ধাপ ২ বার retry |
| `Makefile`, `scripts/*` | `make all`, scaling ও optimisation experiment |

## তোমার কাজের তালিকা (আজ/কাল)
1. WSL + Java 17 + Python setup, `pip install -r requirements.txt`
2. GitHub private repo বানিয়ে প্রথম commit (README, Makefile, common/, generator/)। স্যারকে add করো।
3. `make all` (প্রথমে `.env`-এ `EPISCOPE_SF=0.05`)। চললে → `make serve` দিয়ে dashboard দেখো
4. **Scaling:** `make scaling` (SF 0.25, 0.5, 1)। ফল: `docs/experiments/scaling_summary.md`। SF=1 কত মিনিট লাগল লিখে রাখো (৪৫ মিনিটের কম হতে হবে)
5. **Optimisation:** `make generate SF=0.5` তারপর `HOLD=1 bash scripts/optimisation_experiment.sh`। প্রতিবার শেষে Spark UI (http://localhost:4040) খোলা থাকবে → **SQL tab**-এ join-এর ছবি (OPT=0: SortMergeJoin, OPT=1: BroadcastHashJoin) আর **Stages tab**-এর screenshot নাও
6. Video-র pipeline অংশ record: `make all` → `make drop` → `make update` → `make rerun-demo` (দ্বিতীয়বার "no new files" দেখাবে) → quarantine দেখাও:
   ```bash
   python -c "import pandas as pd; q=pd.read_parquet('data/lake/silver/quarantine'); print(q.reason_code.value_counts()); print(q.head(3).to_string())"
   ```

## Video (৪+ মিনিট) – যা বলবে
1. **Architecture (১ মিনিট):** landing → bronze (কাঁচা, অপরিবর্তিত, metadata) → silver (পরিষ্কার, de-identified) → gold (সাপ্তাহিক aggregate) → analytics → JSON → D3
2. **Idempotency (১ মিনিট):** ফাইলকে নাম দিয়ে না, checksum দিয়ে চিনি। একই ফাইল আবার এলে skip। Silver/gold-এ dynamic partition overwrite, তাই একই batch আবার চালালেও duplicate হয় না
3. **Late data (৩০ সেকেন্ড):** ২১ দিন পরে আসা রিপোর্ট পুরনো সপ্তাহ update করে; শুধু সেই epi-year আবার বানাই (partition pruning)
4. **Quality + privacy (১ মিনিট):** ১৬টা rule, quarantine-এ reason code; patient_id salted SHA-256, salt শুধু `.env`-এ
5. **Performance (১ মিনিট):** SF অনুযায়ী runtime টেবিল, broadcast join আর AQE-এর আগে/পরে সময় ও Spark UI screenshot

## স্যার যা জিজ্ঞেস করতে পারেন
- *Bronze-এ সব string কেন?* → "without modification" শর্ত; টাইপ ভুল হলে ডেটা হারাবে না, silver-এ cast করে rule দিয়ে ধরি।
- *Partition key কেন epi_year/batch_id?* → batch_id দিয়ে একটা load আবার লিখলে শুধু সেটা replace হয় (idempotent); epi_year দিয়ে gold শুধু দরকারি বছর পড়ে (pruning)। সপ্তাহ ধরে partition করলে অনেক ছোট ফাইল হতো।
- *Hidden drop কীভাবে চলবে?* → `data/landing/`-এ যেকোনো নামে রাখলেই কলাম দেখে চিনে নেবে; কোনো তারিখ/নাম hard-code নেই।
- *Duplicate কীভাবে ধরো?* → একই batch-এ একই encounter_id → R16 quarantine; ভিন্ন batch-এ এলে gold-এ `dropDuplicates(encounter_id)`।
- *Salt কেন?* → শুধু hash করলে ১০ অঙ্কের NID brute-force করে উল্টানো যায়; গোপন salt থাকলে যায় না।
- *Skew কোথায়?* → ঢাকার হাসপাতালগুলোতে রোগী বেশি; AQE skew-join আর broadcast join shuffle এড়ায়।

## Report-এ তোমার অংশ
§2 (P1–P7 টেবিল: প্রতিটা attribute আমাদের কোন design decision-এ এসেছে), §3 Architecture + বিকল্প (Delta/Airflow কেন নয়), §4 Data/quality/lineage/privacy, §6-এর scalability + optimisation অংশ, C4। পুরো report জোড়া লাগানো।
