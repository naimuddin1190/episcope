// View 3: seasonal heatmap, district x epi-week, for the brushed period.
import { state, data, set, css, isAlert, showTip, hideTip, countLabel, fmt1, fmtDate, parseDate, SUPPRESSED } from "./state.js";

const ROW = 9, LABEL = 170, TOP = 34;
let svg, dates;

export function initHeatmap() {
  dates = data.weekly.weeks.map(parseDate);
  svg = d3.select("#heat").append("svg").attr("role", "img").attr("aria-label", "Heatmap of weekly incidence by district");
}

export function updateHeatmap() {
  const [i0, i1] = state.range;
  const n = i1 - i0 + 1;
  const W = Math.max(900, LABEL + n * 4 + 20);
  const cw = (W - LABEL - 10) / n;
  const order = data.weekly.district_order;
  const H = TOP + order.length * ROW + 10;
  svg.attr("viewBox", `0 0 ${W} ${H}`);
  svg.selectAll("*").remove();
  const dz = data.weekly.diseases[state.disease];
  const pops = order.map(c => data.districtByCode.get(c).population);
  const inc = [];
  order.forEach((c, i) => { for (let j = i0; j <= i1; j++) { const v = dz.counts[i][j]; if (v > 0) inc.push(v / pops[i] * 1e5); } });
  const max = Math.max(d3.quantile(inc.sort(d3.ascending), 0.98) || 1, 0.5);
  const color = d3.scaleSequential([0, max], d3.interpolateRgb(css("--seq-lo"), css("--seq-hi"))).clamp(true);
  const xs = j => LABEL + (j - i0) * cw;

  // month / year labels
  const xt = d3.scaleUtc([dates[i0], dates[i1]], [LABEL, LABEL + (n - 1) * cw]);
  svg.append("g").attr("class", "axis").attr("transform", `translate(0,${TOP - 4})`)
    .call(d3.axisTop(xt).ticks(Math.min(12, n / 4)).tickSizeOuter(0));

  const rows = svg.append("g");
  order.forEach((code, i) => {
    const g = rows.append("g").attr("transform", `translate(0,${TOP + i * ROW})`);
    const sel = code === state.district;
    g.append("text").attr("class", "rowlabel" + (sel ? " selected" : "")).attr("x", LABEL - 6).attr("y", ROW - 1.5)
      .attr("text-anchor", "end").text(data.districtByCode.get(code).district)
      .on("click", () => set({ district: sel ? null : code }, "heat"));
    const cells = d3.range(i0, i1 + 1).map(j => ({ j, v: dz.counts[i][j] }));
    g.selectAll("rect").data(cells).join("rect").attr("class", "cell")
      .attr("x", c => xs(c.j)).attr("y", 0).attr("width", Math.max(cw - 0.5, 0.5)).attr("height", ROW - 1)
      .attr("fill", c => c.v === SUPPRESSED ? "url(#hatch)" : (c.v === 0 || c.v == null) ? "var(--muted-fill)" : color(c.v / pops[i] * 1e5))
      .on("mousemove", (e, c) => showTip(e, `<b>${data.districtByCode.get(code).district}</b><br>Week of ${fmtDate(dates[c.j])}<br>
         Cases: ${countLabel(c.v)}${c.v > 0 ? `<br>Per 100,000: ${fmt1(c.v / pops[i] * 1e5)}` : ""}
         ${isAlert(state.disease, i, c.j) ? '<br><span style="color:var(--critical)">▲ Alert</span>' : ""}`))
      .on("mouseleave", hideTip)
      .on("click", (e, c) => set({ district: code, week: c.j }, "heat"));
    if (sel) g.append("rect").attr("x", LABEL - 2).attr("y", -1).attr("width", n * cw + 4).attr("height", ROW + 1)
      .attr("fill", "none").attr("stroke", "var(--select)").attr("stroke-width", 1.2);
    // alert ticks
    g.selectAll("circle").data(d3.range(i0, i1 + 1).filter(j => isAlert(state.disease, i, j))).join("circle")
      .attr("cx", j => xs(j) + cw / 2).attr("cy", ROW / 2 - 0.5).attr("r", Math.min(2.4, cw / 2))
      .attr("fill", "var(--critical)").attr("pointer-events", "none");
  });
  // selected week column
  if (state.week >= i0 && state.week <= i1) {
    svg.append("rect").attr("x", xs(state.week) - 0.5).attr("y", TOP - 2).attr("width", cw + 1)
      .attr("height", order.length * ROW + 3).attr("fill", "none").attr("stroke", "var(--select)").attr("stroke-width", 1.2);
  }
  // division separators
  let prev = null;
  order.forEach((code, i) => {
    const div = data.districtByCode.get(code).division;
    if (div !== prev) {
      svg.append("text").attr("x", 2).attr("y", TOP + i * ROW + ROW - 1.5).attr("font-size", 9).attr("font-weight", 700)
        .attr("fill", "var(--ink-3)").text(div.toUpperCase());
      if (prev) svg.append("line").attr("x1", 0).attr("x2", W).attr("y1", TOP + i * ROW - 0.5).attr("y2", TOP + i * ROW - 0.5)
        .attr("stroke", "var(--line)");
    }
    prev = div;
  });
}
