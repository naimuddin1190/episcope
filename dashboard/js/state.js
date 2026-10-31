// Shared state + event bus. Every view listens to "change" and redraws itself (VIS-3 linking).
export const state = {
  disease: "dengue",
  district: null,          // district_code or null for all Bangladesh
  range: [0, 0],           // [start, end] week indices (brush on the time-series context strip)
  week: 0,                 // selected week index (= end of range unless a cell/row was clicked)
  threshold: 4,
  budgetIdx: 2,
  alphaIdx: 3,
  resource: "iv_saline",
};
export const data = {};    // filled by main.js
export const bus = d3.dispatch("change");

export function set(patch, source) {
  Object.assign(state, patch);
  bus.call("change", null, { source, patch });
}

// ---- helpers shared by views ----
export const SUPPRESSED = -1;
export const fmt = d3.format(",.0f");
export const fmt1 = d3.format(",.1f");
export const fmtDate = d3.utcFormat("%d %b %Y");
export const parseDate = d3.utcParse("%Y-%m-%d");

export function css(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function districtIndex(code) { return data.weekly.district_order.indexOf(code); }

export function districtName(code) { return data.districtByCode.get(code)?.district ?? code; }

/** Alert = statistic above the threshold AND enough cases (recomputed for the threshold slider). */
export function isAlert(disease, i, j) {
  const d = data.weekly.diseases[disease];
  const s = d.stat[i][j];
  return s != null && s > state.threshold && d.alertable[i][j] === 1;
}

const tip = () => d3.select("#tooltip");
export function showTip(event, html) {
  const t = tip().html(html).style("opacity", 1);
  const node = t.node();
  const w = node.offsetWidth, h = node.offsetHeight;
  let x = event.clientX + 14, y = event.clientY + 14;
  if (x + w > window.innerWidth - 8) x = event.clientX - w - 14;
  if (y + h > window.innerHeight - 8) y = event.clientY - h - 14;
  t.style("left", `${x}px`).style("top", `${y}px`);
}
export function hideTip() { tip().style("opacity", 0); }

export function freshness() {
  const m = data.meta;
  return `Data up to ${fmtDate(parseDate(m.data_cutoff))} · built ${m.generated_at.replace("T", " ").slice(0, 16)} UTC`;
}

export function countLabel(v) {
  if (v === SUPPRESSED) return '<span class="supp">1–4 (suppressed)</span>';
  if (v == null) return "–";
  return fmt(v);
}
