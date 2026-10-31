// View 4: forecast demand vs current stock vs recommended allocation, plus the efficiency-equity curve.
import { state, data, set, showTip, hideTip, fmt, districtName } from "./state.js";

const W = 620, ROWH = 20, M = { t: 24, r: 20, b: 26, l: 130 };
const RES_LABEL = { iv_saline: "IV saline bags", ns1_kits: "NS1 kits", ors: "ORS sachets" };

export function levels() {
  const a = data.allocation.summary.assumptions;
  return { budgets: a.BUDGET_LEVELS, alphas: a.ALPHA_LEVELS };
}

function scenario() {
  const { budgets, alphas } = levels();
  const b = budgets[state.budgetIdx], al = alphas[state.alphaIdx];
  const pick = (alpha) => new Map(data.allocation.scenarios
    .filter(s => Math.abs(s.budget_share - b) < 1e-9 && Math.abs(s.alpha - alpha) < 1e-9).map(s => [s.district_code, s]));
  return { b, al, opt: pick(al), base: pick(-1) };
}

export function updateAllocation() {
  const r = state.resource;
  const { b, al, opt, base } = scenario();
  const rows = data.allocation.districts.map(d => ({
    code: d.district_code, name: d.district,
    q100: d[`${r}_q100`], q500: d[`${r}_q500`], q900: d[`${r}_q900`],
    stock: d[`stock_${r}`] ?? 0, alloc: opt.get(d.district_code)?.[r] ?? 0, base: base.get(d.district_code)?.[r] ?? 0,
  }));
  rows.forEach(d => { d.gap = Math.max(0, d.q900 - d.stock); });
  let show = rows.slice().sort((a, b2) => d3.descending(a.gap, b2.gap) || d3.descending(a.q900, b2.q900)).slice(0, 15);
  if (state.district && !show.find(d => d.code === state.district)) show.push(rows.find(d => d.code === state.district));
  const H = M.t + show.length * ROWH + M.b;
  const svg = d3.select("#alloc").selectAll("svg").data([0]).join("svg").attr("viewBox", `0 0 ${W} ${H}`);
  svg.selectAll("*").remove();
  const xmax = d3.max(show, d => Math.max(d.q900, d.stock + d.alloc, d.stock + d.base)) || 1;
  const x = d3.scaleLinear([0, xmax * 1.05], [M.l, W - M.r]).nice();
  const y = d3.scaleBand(show.map(d => d.code), [M.t, H - M.b]).padding(0.25);
  svg.append("g").attr("class", "gridline").attr("transform", `translate(0,${H - M.b})`)
    .call(d3.axisBottom(x).ticks(5).tickSize(-(H - M.b - M.t)).tickFormat(""));
  svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - M.b})`).call(d3.axisBottom(x).ticks(5, "~s"));
  svg.append("g").attr("class", "axis").attr("transform", `translate(${M.l},0)`)
    .call(d3.axisLeft(y).tickFormat(c => districtName(c)).tickSize(0)).call(g => g.select(".domain").remove())
    .selectAll("text").style("font-weight", c => (c === state.district ? 700 : 400)).style("cursor", "pointer")
    .on("click", (e, c) => set({ district: state.district === c ? null : c }, "alloc"));
  const g = svg.append("g").selectAll("g").data(show).join("g").attr("transform", d => `translate(0,${y(d.code)})`);
  const bh = y.bandwidth();
  g.append("rect").attr("x", x(0)).attr("height", bh).attr("width", d => x(d.stock) - x(0)).attr("fill", "var(--s3)").attr("rx", 2);
  g.append("rect").attr("x", d => x(d.stock) + (d.alloc > 0 ? 1 : 0)).attr("height", bh)
    .attr("width", d => Math.max(0, x(d.stock + d.alloc) - x(d.stock) - 1)).attr("fill", "var(--s2)").attr("rx", 2);
  // demand: median tick + 80% whisker
  g.append("line").attr("x1", d => x(d.q100)).attr("x2", d => x(d.q900)).attr("y1", bh / 2).attr("y2", bh / 2)
    .attr("stroke", "var(--ink)").attr("stroke-width", 1.5);
  g.append("line").attr("x1", d => x(d.q500)).attr("x2", d => x(d.q500)).attr("y1", -2).attr("y2", bh + 2)
    .attr("stroke", "var(--ink)").attr("stroke-width", 2.5);
  g.append("path").attr("d", d3.symbol(d3.symbolDiamond, 34)).attr("fill", "none").attr("stroke", "var(--ink-2)")
    .attr("stroke-width", 1.2).attr("transform", d => `translate(${x(d.stock + d.base)},${bh / 2})`);
  g.append("rect").attr("x", M.l).attr("width", W - M.l - M.r).attr("height", bh).attr("fill", "transparent")
    .on("mousemove", (e, d) => showTip(e, `<b>${d.name}</b> · ${RES_LABEL[r]}, next 4 weeks<br>
      Forecast demand: ${fmt(d.q500)} (80%: ${fmt(d.q100)}–${fmt(d.q900)})<br>Current stock: ${fmt(d.stock)}<br>
      Recommended allocation: <b>${fmt(d.alloc)}</b><br>Population-share allocation: ${fmt(d.base)}<br>
      Planned coverage of upper forecast: ${d.q900 > 0 ? Math.round(Math.min(1, (d.stock + d.alloc) / d.q900) * 100) + "%" : "no need"}`))
    .on("mouseleave", hideTip).on("click", (e, d) => set({ district: d.code }, "alloc"));

  const cmp = data.allocation.curve.filter(c => Math.abs(c.budget_share - b) < 1e-9);
  const o = cmp.find(c => c.method === "optimiser" && Math.abs(c.alpha - al) < 1e-9);
  const p = cmp.find(c => c.method === "population_proportional");
  d3.select("#alloc-caption").html(`Budget ${Math.round(b * 100)}% of full need, equity floor α = ${al}. ` +
    (o && p ? `Unmet demand: <b>${(o.unmet_share * 100).toFixed(1)}%</b> with the optimiser vs ${(p.unmet_share * 100).toFixed(1)}% with population shares.` : "") +
    " Showing the 15 districts with the largest gap between upper forecast and stock.");
  d3.select("#alloc-legend").html(
    '<span class="key"><span class="sw" style="background:var(--s3)"></span>current stock</span>' +
    '<span class="key"><span class="sw" style="background:var(--s2)"></span>recommended allocation</span>' +
    '<span class="key"><span class="ln" style="border-color:var(--ink)"></span>forecast demand: median | 80% range</span>' +
    '<span class="key">◇ stock + population-share allocation</span>');
  updateCurve();
}

function updateCurve() {
  const Wc = 620, Hc = 220, m = { t: 14, r: 90, b: 34, l: 52 };
  const curve = data.allocation.curve.filter(c => c.method === "optimiser");
  const { budgets, alphas } = levels();
  const svg = d3.select("#curve").selectAll("svg").data([0]).join("svg").attr("viewBox", `0 0 ${Wc} ${Hc}`);
  svg.selectAll("*").remove();
  const x = d3.scaleLinear([d3.min(curve, c => c.min_district_coverage) * 0.98, 1], [m.l, Wc - m.r]).nice();
  const y = d3.scaleLinear([d3.min(curve, c => 1 - c.unmet_share) * 0.98, 1], [Hc - m.b, m.t]).nice();
  svg.append("g").attr("class", "axis").attr("transform", `translate(0,${Hc - m.b})`).call(d3.axisBottom(x).ticks(5, "%"));
  svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(5, "%"));
  svg.append("text").attr("x", (m.l + Wc - m.r) / 2).attr("y", Hc - 4).attr("text-anchor", "middle").attr("font-size", 11)
    .attr("fill", "var(--ink-2)").text("Equity: coverage of the worst-served district →");
  svg.append("text").attr("x", m.l - 40).attr("y", m.t - 4).attr("font-size", 11).attr("fill", "var(--ink-2)")
    .text("Efficiency: demand met");
  budgets.forEach((bv, bi) => {
    const pts = curve.filter(c => Math.abs(c.budget_share - bv) < 1e-9).sort((a, b) => a.alpha - b.alpha);
    const sel = bi === state.budgetIdx;
    svg.append("path").datum(pts).attr("fill", "none").attr("stroke", sel ? "var(--s1)" : "var(--ink-3)")
      .attr("stroke-width", sel ? 2 : 1).attr("opacity", sel ? 1 : 0.6)
      .attr("d", d3.line().x(c => x(c.min_district_coverage)).y(c => y(1 - c.unmet_share)));
    svg.selectAll(null).data(pts).join("circle").attr("r", c => (sel && Math.abs(c.alpha - alphas[state.alphaIdx]) < 1e-9 ? 6 : 3.5))
      .attr("cx", c => x(c.min_district_coverage)).attr("cy", c => y(1 - c.unmet_share))
      .attr("fill", sel ? "var(--s1)" : "var(--ink-3)").attr("stroke", "var(--surface)").attr("stroke-width", 2)
      .style("cursor", "pointer")
      .on("mousemove", (e, c) => showTip(e, `Budget ${Math.round(c.budget_share * 100)}% · α = ${c.alpha}<br>
         Demand met: ${((1 - c.unmet_share) * 100).toFixed(1)}%<br>Worst district coverage: ${(c.min_district_coverage * 100).toFixed(1)}%`))
      .on("mouseleave", hideTip)
      .on("click", (e, c) => set({ budgetIdx: budgets.indexOf(c.budget_share), alphaIdx: alphas.indexOf(c.alpha) }, "curve"));
    const last = pts[pts.length - 1];
    if (last) svg.append("text").attr("x", x(last.min_district_coverage) + 8).attr("y", y(1 - last.unmet_share) + 4)
      .attr("font-size", 11).attr("fill", sel ? "var(--ink)" : "var(--ink-2)").attr("font-weight", sel ? 700 : 400)
      .text(`budget ${Math.round(bv * 100)}%`);
  });
}
