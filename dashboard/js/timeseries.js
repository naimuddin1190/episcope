// View 2: weekly time series with brush/zoom, forecast median + prediction bands, alert threshold.
import { state, data, set, isAlert, showTip, hideTip, countLabel, fmt, fmt1, fmtDate, parseDate, SUPPRESSED, districtName } from "./state.js";

const W = 620, H = 330, CH = 70;
const M = { t: 12, r: 16, b: 26, l: 48 };
let svg, gFocus, gCtx, x, xCtx, brush, dates, ignoreBrush = false;

export function initTimeseries() {
  dates = data.weekly.weeks.map(parseDate);
  svg = d3.select("#ts").append("svg").attr("viewBox", `0 0 ${W} ${H + CH + 26}`)
    .attr("role", "img").attr("aria-label", "Weekly cases over time");
  svg.append("defs").append("clipPath").attr("id", "clip")
    .append("rect").attr("x", M.l).attr("y", 0).attr("width", W - M.l - M.r).attr("height", H);
  gFocus = svg.append("g");
  gCtx = svg.append("g").attr("transform", `translate(0,${H + 14})`);
  x = d3.scaleUtc().range([M.l, W - M.r]);
  xCtx = d3.scaleUtc().range([M.l, W - M.r]);
  brush = d3.brushX().extent([[M.l, 0], [W - M.r, CH - 18]]).on("end", brushed);
}

function brushed(event) {
  if (ignoreBrush || !event.sourceEvent) return;
  if (!event.selection) return;
  const [a, b] = event.selection.map(xCtx.invert);
  const i0 = Math.max(0, d3.bisectLeft(dates, a));
  const i1 = Math.min(dates.length - 1, Math.max(i0, d3.bisectLeft(dates, b) - 1));
  set({ range: [i0, i1], week: i1 }, "brush");
}

function series() {
  const dz = data.weekly.diseases[state.disease];
  if (!state.district) {
    return { obs: dz.national.map((v, j) => ({ d: dates[j], v, j })), thr: null, fc: null, i: -1 };
  }
  const i = data.weekly.district_order.indexOf(state.district);
  const obs = dz.counts[i].map((v, j) => ({ d: dates[j], v, j }));
  const thr = dz.expected[i].map((e, j) => (e == null || dz.sigma[i][j] == null ? null :
    { d: dates[j], e, t: e + state.threshold * dz.sigma[i][j] }));
  const fcd = data.forecasts.forecasts[state.district]?.[state.disease];
  const fc = fcd ? fcd.weeks.map((w, k) => ({ d: parseDate(w), q025: fcd.q025[k], q100: fcd.q100[k], q250: fcd.q250[k],
    q500: fcd.q500[k], q750: fcd.q750[k], q900: fcd.q900[k], q975: fcd.q975[k] })) : null;
  return { obs, thr, fc, i };
}

export function updateTimeseries() {
  const { obs, thr, fc, i } = series();
  const [i0, i1] = state.range;
  const end = fc && i1 === dates.length - 1 ? d3.max(fc, f => f.d) : dates[i1];
  x.domain([dates[i0], end]);
  xCtx.domain([dates[0], fc ? d3.max([dates[dates.length - 1], d3.max(fc, f => f.d)]) : dates[dates.length - 1]]);
  const inRange = obs.filter(o => o.j >= i0 && o.j <= i1);
  const ymax = d3.max([
    d3.max(inRange, o => (o.v > 0 ? o.v : 0)) || 1,
    thr ? d3.max(thr.filter((t, j) => t && j >= i0 && j <= i1), t => t.t) || 0 : 0,
    fc && i1 === dates.length - 1 ? d3.max(fc, f => f.q975) : 0,
  ]);
  const y = d3.scaleLinear([0, ymax * 1.08], [H - M.b, M.t]).nice();
  gFocus.selectAll("*").remove();

  gFocus.append("g").attr("class", "gridline").attr("transform", `translate(${M.l},0)`)
    .call(d3.axisLeft(y).ticks(5).tickSize(-(W - M.l - M.r)).tickFormat(""));
  gFocus.append("g").attr("class", "axis").attr("transform", `translate(0,${H - M.b})`).call(d3.axisBottom(x).ticks(6));
  gFocus.append("g").attr("class", "axis").attr("transform", `translate(${M.l},0)`).call(d3.axisLeft(y).ticks(5, "~s"));
  gFocus.append("text").attr("x", M.l).attr("y", M.t - 2).attr("font-size", 11).attr("fill", "var(--ink-2)")
    .text("cases per week");
  const body = gFocus.append("g").attr("clip-path", "url(#clip)");

  // provisional (not yet mature) weeks: reported counts are still rising
  const fi = data.weekly.first_immature_index;
  if (fi < dates.length) {
    body.append("rect").attr("x", x(dates[fi])).attr("y", M.t).attr("width", Math.max(0, x(end) - x(dates[fi]) + 8))
      .attr("height", H - M.b - M.t).attr("fill", "var(--grid)");
    body.append("text").attr("x", x(dates[fi]) + 4).attr("y", M.t + 12).attr("font-size", 10).attr("fill", "var(--ink-2)")
      .text("provisional / forecast");
  }
  // forecast bands
  if (fc) {
    const band = (lo, hi, fill) => body.append("path").datum(fc).attr("fill", fill)
      .attr("d", d3.area().x(f => x(f.d)).y0(f => y(f[lo])).y1(f => y(f[hi])));
    band("q025", "q975", "var(--band)");
    band("q100", "q900", "var(--band)");
    band("q250", "q750", "var(--band-2)");
    body.append("path").datum(fc).attr("fill", "none").attr("stroke", "var(--s1)").attr("stroke-width", 2)
      .attr("stroke-dasharray", "5 3").attr("d", d3.line().x(f => x(f.d)).y(f => y(f.q500)));
  }
  // alert threshold = expected + h * sigma
  if (thr) {
    body.append("path").datum(thr).attr("fill", "none").attr("stroke", "var(--ink-3)").attr("stroke-width", 1.5)
      .attr("stroke-dasharray", "2 3")
      .attr("d", d3.line().defined(t => t).x((t, j) => x(dates[j])).y(t => y(t.t)));
  }
  // observed
  body.append("path").datum(obs).attr("fill", "none").attr("stroke", "var(--s1)").attr("stroke-width", 2)
    .attr("d", d3.line().defined(o => o.v !== SUPPRESSED && o.v != null).x(o => x(o.d)).y(o => y(o.v)));
  // suppressed weeks shown as hollow markers on the baseline (value hidden)
  body.selectAll("rect.supp").data(obs.filter(o => o.v === SUPPRESSED)).join("rect").attr("class", "supp")
    .attr("x", o => x(o.d) - 2).attr("y", y(0) - 8).attr("width", 4).attr("height", 8).attr("fill", "url(#hatch)");
  // alerts
  if (i >= 0) {
    const al = obs.filter(o => isAlert(state.disease, i, o.j));
    body.selectAll("path.alert-mark").data(al).join("path").attr("class", "alert-mark")
      .attr("d", d3.symbol(d3.symbolTriangle, 60))
      .attr("transform", o => `translate(${x(o.d)},${y(Math.max(o.v, 0)) - 10})`);
  }
  // selected week
  body.append("line").attr("x1", x(dates[state.week])).attr("x2", x(dates[state.week]))
    .attr("y1", M.t).attr("y2", H - M.b).attr("stroke", "var(--ink)").attr("stroke-width", 1).attr("opacity", 0.5);

  // hover crosshair
  const hover = gFocus.append("g").style("display", "none");
  hover.append("line").attr("y1", M.t).attr("y2", H - M.b).attr("stroke", "var(--ink-3)");
  hover.append("circle").attr("r", 4).attr("fill", "var(--s1)").attr("stroke", "var(--surface)").attr("stroke-width", 2);
  gFocus.append("rect").attr("x", M.l).attr("y", M.t).attr("width", W - M.l - M.r).attr("height", H - M.b - M.t)
    .attr("fill", "transparent")
    .on("mousemove", (e) => {
      const [px] = d3.pointer(e);
      const d = x.invert(px);
      const j = Math.min(dates.length - 1, Math.max(0, d3.bisectCenter(dates, d)));
      const o = obs[j];
      const f = fc?.find(f => Math.abs(f.d - d) < 3.5 * 864e5);
      const xx = x(f && d > dates[dates.length - 1] ? f.d : o.d);
      hover.style("display", null).attr("transform", `translate(${xx},0)`);
      hover.select("circle").attr("cy", y(f && d > dates[dates.length - 1] ? f.q500 : Math.max(o.v, 0)));
      let html = `<b>${state.district ? districtName(state.district) : "All Bangladesh"}</b><br>`;
      if (f && d > dates[dates.length - 1]) {
        html += `Week of ${fmtDate(f.d)} (forecast)<br>Median ${fmt1(f.q500)}<br>80% range ${fmt(f.q100)}–${fmt(f.q900)}`;
      } else {
        html += `Week of ${fmtDate(o.d)}<br>Cases: ${countLabel(o.v)}`;
        const t = thr?.[j];
        if (t) html += `<br>Expected ${fmt1(t.e)} · threshold ${fmt1(t.t)}`;
        if (j >= data.weekly.first_immature_index) html += "<br><i>provisional: late reports still arriving</i>";
        if (i >= 0 && isAlert(state.disease, i, j)) html += '<br><span style="color:var(--critical)">▲ Alert</span>';
        if (f) html += `<br>Forecast median ${fmt1(f.q500)} (80%: ${fmt(f.q100)}–${fmt(f.q900)})`;
      }
      showTip(e, html);
    })
    .on("mouseleave", () => { hover.style("display", "none"); hideTip(); })
    .on("click", (e) => {
      const j = Math.min(i1, Math.max(i0, d3.bisectCenter(dates, x.invert(d3.pointer(e)[0]))));
      set({ week: j }, "ts");
    });

  // context strip with brush
  gCtx.selectAll("*").remove();
  const yc = d3.scaleLinear([0, d3.max(obs, o => Math.max(o.v, 0)) || 1], [CH - 18, 0]);
  gCtx.append("path").datum(obs).attr("fill", "var(--band)").attr("stroke", "var(--s1)").attr("stroke-width", 1)
    .attr("d", d3.area().defined(o => o.v !== SUPPRESSED).x(o => xCtx(o.d)).y0(CH - 18).y1(o => yc(Math.max(o.v, 0))));
  gCtx.append("g").attr("class", "axis").attr("transform", `translate(0,${CH - 18})`).call(d3.axisBottom(xCtx).ticks(6));
  const gb = gCtx.append("g").attr("class", "brush").call(brush);
  ignoreBrush = true;
  gb.call(brush.move, [xCtx(dates[i0]), xCtx(dates[i1])]);
  ignoreBrush = false;

  const name = state.district ? districtName(state.district) : "All Bangladesh (national total)";
  d3.select("#ts-caption").text(`${name}. ` + (state.district ? (fc ? "Forecast for the next weeks shown with 50/80/95% bands." :
    "No forecast for this disease (forecasts: dengue and diarrhoea).") : "Select a district to see its forecast and alert threshold."));
  const lg = d3.select("#ts-legend").html("");
  lg.append("span").attr("class", "key").html('<span class="ln" style="border-color:var(--s1)"></span>observed');
  if (fc) lg.append("span").attr("class", "key").html('<span class="ln" style="border-color:var(--s1);border-top-style:dashed"></span>forecast median');
  if (fc) lg.append("span").attr("class", "key").html('<span class="sw" style="background:var(--band-2)"></span>50% / 80% / 95% prediction bands');
  if (thr) lg.append("span").attr("class", "key").html(`<span class="ln" style="border-color:var(--ink-3);border-top-style:dotted"></span>alert threshold (h = ${state.threshold})`);
  lg.append("span").attr("class", "key").html('<span style="color:var(--critical)">▲</span> alert');
}
