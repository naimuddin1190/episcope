// View 1: district choropleth of incidence per 100,000 for the selected week, with alert markers.
import { state, data, set, css, isAlert, showTip, hideTip, countLabel, fmt1, fmtDate, parseDate, SUPPRESSED } from "./state.js";

const W = 520, H = 560;
let svg, gMap, gMarks, path, features, centroids;

export function initMap() {
  const topo = data.topo;
  const obj = topo.objects[Object.keys(topo.objects)[0]];
  features = topojson.feature(topo, obj).features;
  const proj = d3.geoMercator().fitExtent([[10, 10], [W - 10, H - 30]], { type: "FeatureCollection", features });
  path = d3.geoPath(proj);
  const codeByName = new Map(data.districts.map(d => [d.district, d.district_code]));
  features.forEach(f => { f.code = codeByName.get(f.properties.district); });
  centroids = new Map(features.map(f => [f.code, path.centroid(f)]));

  svg = d3.select("#map").append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img")
    .attr("aria-label", "Map of district incidence per 100,000");
  const defs = svg.append("defs");
  defs.append("pattern").attr("id", "hatch").attr("patternUnits", "userSpaceOnUse").attr("width", 5).attr("height", 5)
    .attr("patternTransform", "rotate(45)")
    .call(p => {
      p.append("rect").attr("width", 5).attr("height", 5).attr("fill", "var(--muted-fill)");
      p.append("line").attr("x1", 0).attr("y1", 0).attr("x2", 0).attr("y2", 5).attr("stroke", "var(--hatch)").attr("stroke-width", 1.6);
    });
  gMap = svg.append("g");
  gMarks = svg.append("g");
  gMap.selectAll("path").data(features).join("path")
    .attr("class", "district").attr("d", path)
    .on("click", (e, f) => set({ district: state.district === f.code ? null : f.code }, "map"))
    .on("mousemove", (e, f) => showTip(e, tipHtml(f.code)))
    .on("mouseleave", hideTip);
}

function value(code) {
  const i = data.weekly.district_order.indexOf(code);
  const v = data.weekly.diseases[state.disease].counts[i][state.week];
  const pop = data.districtByCode.get(code).population;
  return { v, inc: v === SUPPRESSED || v == null ? null : (v / pop) * 1e5 };
}

function tipHtml(code) {
  const d = data.districtByCode.get(code);
  const { v, inc } = value(code);
  const i = data.weekly.district_order.indexOf(code);
  const al = isAlert(state.disease, i, state.week);
  return `<b>${d.district}</b> (${d.division})<br>Week of ${fmtDate(parseDate(data.weekly.weeks[state.week]))}<br>
    Cases: ${countLabel(v)}<br>Per 100,000: ${inc == null ? (v === SUPPRESSED ? "suppressed" : "–") : fmt1(inc)}
    ${al ? '<br><span style="color:var(--critical)">▲ Alert this week</span>' : ""}`;
}

export function updateMap() {
  const vals = features.map(f => value(f.code).inc).filter(v => v != null);
  const max = Math.max(d3.quantile(vals.sort(d3.ascending), 0.98) || 1, 0.5);
  // sequential single-hue blue ramp (light = low)
  const color = d3.scaleSequential([0, max], d3.interpolateRgb(css("--seq-lo"), css("--seq-hi"))).clamp(true);
  gMap.selectAll("path")
    .attr("fill", f => {
      const { v, inc } = value(f.code);
      if (v === SUPPRESSED) return "url(#hatch)";
      if (v === 0) return "var(--muted-fill)";
      return inc == null ? "var(--muted-fill)" : color(inc);
    })
    .classed("selected", f => f.code === state.district);
  gMap.selectAll("path.selected").raise();

  // alerts in the 4 weeks ending at the selected week
  const lo = Math.max(0, state.week - 3);
  const alerts = [];
  data.weekly.district_order.forEach((code, i) => {
    for (let j = lo; j <= state.week; j++) if (isAlert(state.disease, i, j)) { alerts.push(code); break; }
  });
  gMarks.selectAll("path").data(alerts, d => d).join("path")
    .attr("class", "alert-mark").attr("d", d3.symbol(d3.symbolTriangle, 70))
    .attr("transform", c => `translate(${centroids.get(c)})`);

  d3.select("#map-caption").text(`Week of ${fmtDate(parseDate(data.weekly.weeks[state.week]))}. ` +
    `▲ = alert in the last 4 weeks (${alerts.length} districts). Click a district to select it.`);
  legend(color, max);
}

function legend(color, max) {
  const el = d3.select("#map-legend").html("");
  const stops = d3.range(0, 6).map(k => (k / 5) * max);
  stops.forEach(s => el.append("span").attr("class", "key")
    .html(`<span class="sw" style="background:${color(s)}"></span>${fmt1(s)}${s === max ? "+" : ""}`));
  el.append("span").attr("class", "key").html('<span class="sw" style="background:var(--muted-fill)"></span>0');
  el.append("span").attr("class", "key").html('<svg width="14" height="10"><rect width="14" height="10" fill="url(#hatch)"/></svg>suppressed (1–4)');
  el.append("span").attr("class", "key").html('<span style="color:var(--critical)">▲</span> alert');
}
