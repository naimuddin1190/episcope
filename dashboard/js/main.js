// Entry point: load the aggregated JSON exports, wire the controls, and keep all views linked.
import { state, data, bus, set, freshness, districtName } from "./state.js";
import { initMap, updateMap } from "./map.js";
import { initTimeseries, updateTimeseries } from "./timeseries.js";
import { initHeatmap, updateHeatmap } from "./heatmap.js";
import { updateAllocation, levels } from "./allocation.js";
import { updateTable } from "./table.js";
import { updateCalendar, initDQ, initEval } from "./panels.js";

const FILES = ["meta", "weekly", "districts", "alerts", "forecasts", "allocation", "calendar", "dq", "evaluation"];

async function load() {
  const [topo, ...rest] = await Promise.all([d3.json("data/bd_districts.topo.json"),
    ...FILES.map(f => d3.json(`data/${f}.json`))]);
  data.topo = topo;
  FILES.forEach((f, k) => { data[f] = rest[k]; });
  data.districtByCode = new Map(data.districts.map(d => [d.district_code, d]));
}

function initControls() {
  const n = data.weekly.weeks.length;
  const end = n - 1;
  Object.assign(state, {
    // default: the last two years, with the last COMPLETE (mature) week selected
    range: [Math.max(0, end - 103), end], week: Math.max(0, Math.min(end, data.weekly.first_immature_index - 1)),
    threshold: data.meta.detection?.threshold ?? 3,
  });
  const { budgets, alphas } = levels();
  state.budgetIdx = Math.max(0, budgets.indexOf(data.allocation.summary.default_budget_share));
  state.alphaIdx = Math.max(0, alphas.indexOf(data.allocation.summary.recommended_alpha));
  const initial = { ...state };

  const dsel = d3.select("#sel-district");
  const byDiv = d3.group(data.districts, d => d.division);
  for (const [div, ds] of [...byDiv].sort()) {
    const og = dsel.append("optgroup").attr("label", div);
    ds.slice().sort((a, b) => a.district.localeCompare(b.district))
      .forEach(d => og.append("option").attr("value", d.district_code).text(d.district));
  }
  d3.select("#sel-disease").on("change", e => set({ disease: e.target.value }, "control"));
  dsel.on("change", e => set({ district: e.target.value || null }, "control"));
  d3.select("#sel-resource").on("change", e => set({ resource: e.target.value }, "control"));
  d3.select("#rng-threshold").property("value", state.threshold).on("input", e => set({ threshold: +e.target.value }, "control"));
  d3.select("#rng-budget").property("value", state.budgetIdx).on("input", e => set({ budgetIdx: +e.target.value }, "control"));
  d3.select("#rng-alpha").property("value", state.alphaIdx).on("input", e => set({ alphaIdx: +e.target.value }, "control"));
  d3.select("#btn-reset").on("click", () => set({ ...initial }, "reset"));
}

function syncControls() {
  const { budgets, alphas } = levels();
  d3.select("#sel-disease").property("value", state.disease);
  d3.select("#sel-district").property("value", state.district ?? "");
  d3.select("#sel-resource").property("value", state.resource);
  d3.select("#rng-threshold").property("value", state.threshold);
  d3.select("#rng-budget").property("value", state.budgetIdx);
  d3.select("#rng-alpha").property("value", state.alphaIdx);
  d3.select("#out-threshold").text(state.threshold.toFixed(1));
  d3.select("#out-budget").text(`${Math.round(budgets[state.budgetIdx] * 100)}% of need`);
  d3.select("#out-alpha").text(alphas[state.alphaIdx]);
  document.title = `EpiScope · ${state.district ? districtName(state.district) : "Bangladesh"}`;
}

function render() {
  syncControls();
  updateMap();
  updateTimeseries();
  updateHeatmap();
  updateAllocation();
  updateTable();
  updateCalendar();
}

async function main() {
  try {
    await load();
  } catch (err) {
    document.querySelector("main").innerHTML = `<p style="padding:20px">Could not load dashboard data (${err}).
      Run <code>make all</code> first, then serve this folder with <code>make serve</code>.</p>`;
    return;
  }
  d3.select("#banner").text(data.meta.disclaimer);
  d3.selectAll(".fresh").text(freshness());
  d3.select("#foot").html(`Privacy: ${data.meta.suppression} ${data.meta.suppressed_cells.toLocaleString()} cells suppressed. ` +
    `Weather source: ${data.meta.weather_sources.join(", ")}. Only aggregated data is loaded in the browser.`);
  initControls();
  initMap();
  initTimeseries();
  initHeatmap();
  initDQ();
  initEval();
  bus.on("change", render);
  render();
}

main();
