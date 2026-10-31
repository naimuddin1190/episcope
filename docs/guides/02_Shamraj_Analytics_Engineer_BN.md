# Shamraj – Analytics Engineer গাইড

## তোমার ফাইলগুলো
| ফাইল | কী করে | Requirement |
|---|---|---|
| `analytics/detection/detect.py` | প্রতি জেলা × রোগ × সপ্তাহে outbreak signal বের করে, দুইটা পদ্ধতিতে | AN-1, AN-3 |
| `analytics/detection/evaluate.py` | ground truth-এর সাথে মিলিয়ে sensitivity, false alarm, detection-এর দিন; threshold curve; artefact পরীক্ষা | AN-2, AN-3, C1 |
| `analytics/forecast/forecast.py` | ডেঙ্গু ও ডায়রিয়ার ১–৬ সপ্তাহ forecast + ৫২ সপ্তাহের backtest | AN-4, AN-5, C5 |
| `analytics/optimise/assumptions.py` | সব ধরে নেওয়া সংখ্যা (স্যালাইন/রোগী, দাম ইত্যাদি) এক জায়গায় | AN-6 |
| `analytics/optimise/allocate.py` | cases → demand, LP optimizer, population baseline, efficiency–equity curve | AN-6, AN-7, AN-8, C3 |
| `analytics/calendar/calendar.py` | STL দিয়ে seasonal pattern, পরের বছরের প্রস্তুতি ক্যালেন্ডার | AN-9 |

চালানো: `python -m orchestration.run_pipeline --only detection detection_evaluation forecast demand_and_allocation calendar`
ফলাফল: `data/lake/gold/evaluation/*.json` আর `docs/experiments/*.csv` (report-এর চার্ট এগুলো থেকে বানাবে)

## পদ্ধতিগুলো সহজ ভাষায়
**১. EARS C2** (Spark window function): আগের ৭ সপ্তাহের গড় ও SD (মাঝে ২ সপ্তাহ gap, যাতে outbreak-এর শুরু baseline-এ না ঢোকে)। C2 = (এই সপ্তাহ − গড়) / SD। threshold-এর বেশি হলে alert।
সমস্যা: স্বাভাবিক বর্ষার বৃদ্ধিকেও alert ভাবে।

**২. Historical limits** (Farrington-এর মতো, applyInPandas): গত ১–৩ বছরের **একই সময়ের** (±২ সপ্তাহ) গড়কে baseline ধরে, সাম্প্রতিক level দিয়ে scale করে। তাই মৌসুমী বৃদ্ধিকে outbreak ভাবে না → false alarm অনেক কম।

**Nowcast:** শেষ ২ সপ্তাহের রিপোর্ট এখনো পুরো আসেনি। delay distribution থেকে জানি "এতদিনে কত % রিপোর্ট আসে", তাই count ÷ সেই % দিয়ে সংশোধন।

**Artefact:** একটা হাসপাতাল ৩ সপ্তাহ চুপ থেকে একদিনে সব পাঠালে **report week** অনুযায়ী গুনলে spike দেখায় (naive detector false alert দেয়)। আমরা **onset week** (রোগ শুরুর তারিখ) অনুযায়ী গুনি, তাই spike হয় না। `detection_evaluation.json` → `artefact` অংশে দুইটার তুলনা আছে।

**Forecast:** প্রতি জেলা-রোগ-horizon-এর জন্য আলাদা Poisson regression। Feature: এই সপ্তাহ, গত সপ্তাহ, ৪ সপ্তাহের গড়, গত বছর একই সপ্তাহ, sin/cos (ঋতু), বৃষ্টি (৪ ও ৮ সপ্তাহ), তাপমাত্রা। Interval: Negative Binomial। Baseline: "গত বছর একই সপ্তাহ" (seasonal naive)।
Metrics: MAE (গড় ভুল), 80% coverage (সত্যি মান কতবার 80% interval-এর ভেতরে, আদর্শ ~0.8), WIS (পুরো interval কতটা ভালো, কম ভালো)।

**Optimizer (LP):** লক্ষ্য = জেলার weight × অপূর্ণ চাহিদা কমানো। শর্ত: বাজেট, equity floor (প্রতি জেলা অন্তত α × জনসংখ্যার ভাগ পাবে), বিভাগের transport ক্ষমতা। α = 0 হলে সবচেয়ে efficient কিন্তু কিছু জেলা কিছুই পায় না; α বাড়ালে equity বাড়ে, efficiency সামান্য কমে → এটাই C3 curve।

**Calendar:** STL = trend + seasonal + residual। seasonal অংশ গড়ের ওপরে উঠলে "মৌসুম শুরু"; তার ৪ সপ্তাহ আগে supply, ৬ সপ্তাহ আগে campaign।

## Video (৪+ মিনিট) – যা দেখাবে
1. Threshold curve (sensitivity vs false alerts, দুই পদ্ধতি) → কেন historical limits + threshold বেছেছি (C1)
2. Artefact: naive vs আমাদের detector
3. Backtest টেবিল: আমাদের model vs seasonal naive (MAE, coverage, WIS) → কেন GLM, deep learning নয় (C5: officials বুঝতে পারবে)
4. Allocation: optimizer vs population baseline (unmet demand %), efficiency–equity curve, প্রস্তাবিত α
5. Calendar: ডেঙ্গু কবে প্রস্তুতি শুরু

## স্যার যা জিজ্ঞেস করতে পারেন
- *Guard band কেন?* → outbreak শুরু হলে baseline-এ ঢুকে গেলে নিজেকেই লুকিয়ে ফেলে।
- *sigma-র নিচের সীমা কেন √mean বা 1?* → ছোট সংখ্যায় SD 0 হলে ১ জন বাড়লেই অসীম signal হতো।
- *Ground truth detection code পড়ে?* → না, শুধু `evaluate.py`, detection-এর পরে।
- *Upper quantile (q90) দিয়ে plan কেন?* → কম পাঠালে মানুষ মরে, বেশি পাঠালে খরচ; তাই সতর্ক দিক।
- *Objective-এ Y_r দিয়ে ভাগ কেন?* → নাহলে ORS sachet (সংখ্যায় বেশি) আর স্যালাইন ব্যাগ তুলনীয় হয় না।
- *Backtest in-sample?* → না, rolling origin: প্রতিটা forecast শুধু তার আগের ডেটায় train করা model দিয়ে।

## Report-এ তোমার অংশ
§5 Methods, §6 Evaluation (detection curve, backtest টেবিল, allocation vs baseline, efficiency–equity curve), C1, C3, C5, **Appendix A Policy brief** (২ পেজ, কোনো jargon নয়: বর্তমান অবস্থা, ৩টা সুপারিশ, dashboard কীভাবে পড়বে, কতটা নিশ্চিত, data protection)।
