# Ratul – Visualisation Engineer গাইড (হালকা কিন্তু গুরুত্বপূর্ণ)

তোমার কোনো Spark/WSL লাগবে না। Naim-এর কাছ থেকে `dashboard/data/` ফোল্ডারের JSON ফাইলগুলো নিলেই Windows-এ চালাতে পারবে:
```
cd dashboard
python -m http.server 8000      → browser-এ http://localhost:8000
```

## তোমার ফাইলগুলো
| ফাইল | কী করে |
|---|---|
| `serving/export.py` | gold টেবিল থেকে ছোট JSON বানায় (মোট < 10 MB, কোনো রোগীর row নেই) – VIS-4 |
| `serving/suppression.py` | ১–৪ count লুকায় + complementary suppression – PRV-2, C2 |
| `dashboard/index.html`, `css/style.css` | layout, রং (colour-blind-safe), dark mode |
| `dashboard/js/state.js` | সব view-এর শেয়ার করা state (রোগ, জেলা, সময়, threshold…) আর event bus → linking |
| `js/map.js` | View 1: জেলার মানচিত্র, প্রতি লাখে incidence, ▲ alert |
| `js/timeseries.js` | View 2: সাপ্তাহিক রেখা, forecast median + 50/80/95% band, alert threshold, নিচে brush দিয়ে সময় বাছাই |
| `js/heatmap.js` | View 3: জেলা × সপ্তাহ heatmap |
| `js/allocation.js` | View 4: চাহিদা vs stock vs প্রস্তাবিত বরাদ্দ, efficiency–equity curve |
| `js/table.js` | View 5: early-warning টেবিল |
| `js/panels.js` | ক্যালেন্ডার, data quality, model evaluation প্যানেল |
| `js/main.js` | ডেটা load, control, সব view জোড়া |

## Linking কীভাবে কাজ করে (VIS-3)
যেকোনো view-এ click করলে `set({...})` ডাকে → `state` বদলায় → `bus` "change" event পাঠায় → `main.js`-এর `render()` সব view আবার আঁকে। যেমন map-এ ঢাকা click → time series ঢাকার, heatmap-এ ঢাকার সারি হাইলাইট, টেবিলে শুধু ঢাকার alert, allocation-এ ঢাকা।

## What-if panel (VIS-5)
- **Alert threshold slider:** browser-এ প্রতিটা সপ্তাহের signal আছে; slider বদলালে নতুন threshold দিয়ে alert আবার গোনে (map, table, chart সব বদলায়)
- **Budget আর equity floor α:** আগে থেকে হিসাব করা ২৫টা scenario-র মধ্যে থেকে বেছে নেয়

## Privacy (তোমার video-র মূল অংশ)
1. ১–৪ রোগী থাকলে সংখ্যা দেখাই না, ডোরাকাটা (hatched) ঘর দেখাই
2. **Complementary suppression:** বিভাগের মোট সংখ্যা দেখাই। যদি একটা জেলাই লুকানো থাকে, তাহলে "মোট − বাকিরা" করে বের করা যেত। তাই আরেকটা ছোট জেলাও লুকাই। `tests/test_suppression.py` এটা প্রমাণ করে।
3. Browser শুধু aggregated JSON পায়, কখনো রোগী-স্তরের ডেটা নয়

## তোমার কাজের তালিকা
1. Dashboard খুলে প্রতিটা view, tooltip, slider চেষ্টা করো, যা বুঝবে না Naim-কে জিজ্ঞেস করো
2. **২ জন non-CS মানুষ** (পরিবার/বন্ধু) দিয়ে test: ৩টা কাজ দাও ("কোন জেলায় এখন alert?", "ঢাকার আগামী মাসে কত রোগী?", "কোন জেলা সবচেয়ে বেশি স্যালাইন পাবে?")। কত সময় লাগল, কোথায় আটকাল লিখে রাখো → report §7
3. ফিডব্যাক থেকে ছোট একটা পরিবর্তন করো (যেমন কোনো লেখা সহজ করা) এবং নিজের account থেকে commit করো
4. README-র traceability টেবিলে চোখ বুলাও (role-এর বাইরের commit)

## Video (৪+ মিনিট) – যা দেখাবে
1. Disease বাছাই → map, alert ▲ (৩০ সেকেন্ড)
2. Map-এ একটা জেলা click → সব view বদলায় (linking) (১ মিনিট)
3. Time series: forecast band, threshold, brush দিয়ে সময় বদলানো (১ মিনিট)
4. What-if: threshold slider (alert কমে/বাড়ে = C1), budget/α slider (C3) (১ মিনিট)
5. Privacy: hatched ঘর, কেন complementary suppression; colour-blind palette, প্রতিটা view-এ data-freshness তারিখ (১ মিনিট)

## স্যার যা জিজ্ঞেস করতে পারেন
- *Plotly ব্যবহার করোনি তো?* → না, শুধু D3 v7 আর topojson-client (`dashboard/vendor/`)
- *জেলা স্তর কেন, উপজেলা নয়?* → উপজেলায় সংখ্যা ছোট, suppression-এ বেশিরভাগ ঘর লুকাতে হতো (C2)
- *Data কত বড়?* → মোট ~২ MB, সীমা ১০ MB
- *Uncertainty কোথায় দেখাও?* → forecast band, allocation-এ demand-এর 80% range

## Report-এ তোমার অংশ
§1 Introduction, §7 Dashboard design + usability findings, §8 Ethics (ছোট: privacy, stigma, ভুল alert-এর ক্ষতি)।
