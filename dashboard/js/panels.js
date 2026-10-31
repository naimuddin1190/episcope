// Supporting panels: preparedness calendar (AN-9), data-quality report (DQ-2), model evaluation.
import { state, data, set, fmt, fmt1 } from "./state.js";

const DIS = { dengue: "Dengue", diarrhoea: "Diarrhoea", ili: "ILI", malaria: "Malaria" };
const shortDate = d => d3.utcFormat("%d %b")(d3.utcParse("%Y-%m-%d")(d));

export function updateCalendar() {
  const rows = data.calendar.calendar.filter(r => r.disease === state.disease);
  const div = state.district ? data.districtByCode.get(state.district).division : null;
  const t = d3.select("#cal").html("");
  t.append("thead").append("tr").selectAll("th")
    .data(["Division", "Start prevention", "Pre-position supplies", "Season starts", "Peak week", "Actions"]).join("th").text(d => d);
  const tr = t.append("tbody").selectAll("tr").data(rows).join("tr").classed("selected", r => r.division === div);
  tr.append("td").html(r => r.division + (r.reliable ? "" : ' <span class="badge" title="too few cases for a reliable pattern">low data</span>'));
  tr.append("td").text(r => shortDate(r.start_prevention_campaign));
  tr.append("td").text(r => shortDate(r.preposition_supplies_by));
  tr.append("td").text(r => shortDate(r.season_start));
  tr.append("td").text(r => shortDate(r.peak_date));
  tr.append("td").style("white-space", "normal").style("min-width", "220px").text(r => r.recommended_actions);
}

export function initDQ() {
  const dq = data.dq;
  const batches = [...new Set(dq.rules.map(r => r.batch_id))].sort();
  const el = d3.select("#dq").html("");
  const sel = el.append("div").attr("class", "row").append("label").text("Load (batch) ").append("select");
  sel.selectAll("option").data(batches.slice().reverse()).join("option").attr("value", d => d).text(d => d);
  const box = el.append("div");
  const draw = (b) => {
    box.html("");
    for (const src of ["encounters", "stock"]) {
      const rules = dq.rules.filter(r => r.batch_id === b && r.source === src);
      if (!rules.length) continue;
      const r0 = rules[0];
      box.append("h3").text(`${src}: ${fmt(r0.rows_in)} rows in · ${fmt(r0.rows_valid)} accepted · ${fmt(r0.rows_quarantined)} quarantined (${(r0.rows_quarantined / Math.max(r0.rows_in, 1) * 100).toFixed(2)}%)`);
      const t = box.append("div").attr("class", "table-wrap").style("max-height", "220px").append("table");
      t.append("thead").append("tr").selectAll("th").data(["Rule", "Check", "Failed", "Pass rate"]).join("th")
        .attr("class", (d, k) => (k >= 2 ? "num" : null)).text(d => d);
      const tr = t.append("tbody").selectAll("tr").data(rules).join("tr");
      tr.append("td").text(r => r.rule_code);
      tr.append("td").style("white-space", "normal").text(r => r.description);
      tr.append("td").attr("class", "num").text(r => fmt(r.failed));
      tr.append("td").attr("class", "num").text(r => (r.pass_rate * 100).toFixed(2) + "%");
    }
    const files = data.dq.batches.filter(x => x.batch_id === b);
    box.append("p").attr("class", "hint").text("Files in this load: " + files.map(f => `${f.source} ${f.files} file(s), ${fmt(f.rows)} rows`).join(" · "));
  };
  sel.on("change", e => draw(e.target.value));
  draw(batches[batches.length - 1]);
}

export function initEval() {
  const el = d3.select("#eval").html("");
  const det = data.evaluation.detection || {};
  const op = det.operating_point || {};
  const dcur = (det.curve || []).find(c => c.method === op.method && c.threshold === op.threshold);
  const bt = data.forecasts.backtest || [];
  const a = data.allocation.summary.comparison || [];
  const o = a.find(c => c.method === "optimiser"), p = a.find(c => c.method === "population_proportional");
  const card = (title, kpi, label, extra) => {
    const c = el.append("div");
    c.append("h3").text(title);
    c.append("div").attr("class", "kpi").text(kpi);
    c.append("div").attr("class", "kpi-label").text(label);
    if (extra) c.append("p").attr("class", "hint").html(extra);
  };
  if (dcur) card("Outbreak detection", `${Math.round(dcur.sensitivity * 100)}%`,
    `of ${dcur.outbreaks} injected outbreak episodes detected`,
    `${op.method === "historical_limits" ? "Seasonal historical limits" : "EARS C2"}, threshold ${op.threshold}: ` +
    `${dcur.false_per_district_year} false alerts per district-year, median ${dcur.median_days_to_detection} days to detection.`);
  const h1 = bt.filter(b => b.horizon === 1);
  if (h1.length) card("Forecasting (1 week ahead)", `${Math.round(d3.mean(h1, b => b.mae_skill_vs_naive) * 100)}%`,
    "lower error than 'same week last year'",
    h1.map(b => `${DIS[b.disease]}: MAE ${fmt1(b.mae_model)} vs ${fmt1(b.mae_seasonal_naive)}, 80% interval coverage ${Math.round(b.coverage80_model * 100)}%`).join("<br>"));
  if (o && p) card("Supply allocation", `${((p.unmet_share - o.unmet_share) * 100).toFixed(1)} pts`,
    "less unmet demand than population-share allocation (same budget)",
    `Unmet: ${(o.unmet_share * 100).toFixed(1)}% vs ${(p.unmet_share * 100).toFixed(1)}%. Worst-served district coverage ` +
    `${Math.round(o.min_district_coverage * 100)}% vs ${Math.round(p.min_district_coverage * 100)}%.`);
}
