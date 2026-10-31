// View 5: ranked early-warning table. Shows every alert in the brushed period for the selected
// disease (or all diseases when "all" is ticked), strongest signal first. Click a row to select it.
import { state, data, set, isAlert, fmt, fmt1, fmtDate, parseDate, SUPPRESSED, districtName } from "./state.js";

const DIS = { dengue: "Dengue", diarrhoea: "Diarrhoea", ili: "ILI", malaria: "Malaria" };

export function updateTable() {
  const [i0, i1] = state.range;
  const w = data.weekly;
  const rows = [];
  for (const dis of Object.keys(w.diseases)) {
    if (dis !== state.disease) continue;
    const dz = w.diseases[dis];
    w.district_order.forEach((code, i) => {
      if (state.district && code !== state.district) return;
      for (let j = i0; j <= i1; j++) {
        if (!isAlert(dis, i, j)) continue;
        rows.push({ code, dis, j, v: dz.counts[i][j], e: dz.expected[i][j], s: dz.stat[i][j],
          prov: j >= w.first_immature_index });
      }
    });
  }
  rows.sort((a, b) => d3.descending(a.j, b.j) || d3.descending(a.s, b.s));
  const tbl = d3.select("#tbl").html("");
  tbl.append("thead").append("tr").selectAll("th")
    .data(["#", "District", "Division", "Week of", "Cases", "Expected", "Signal", ""]).join("th")
    .attr("class", (d, k) => (k >= 4 && k <= 6 ? "num" : null)).text(d => d);
  const tb = tbl.append("tbody");
  const tr = tb.selectAll("tr").data(rows.slice(0, 300)).join("tr")
    .classed("selected", r => r.code === state.district && r.j === state.week)
    .on("click", (e, r) => set({ district: r.code, week: r.j }, "table"));
  tr.append("td").attr("class", "num").text((r, k) => k + 1);
  tr.append("td").text(r => districtName(r.code));
  tr.append("td").text(r => data.districtByCode.get(r.code).division);
  tr.append("td").text(r => fmtDate(parseDate(w.weeks[r.j])));
  tr.append("td").attr("class", "num").html(r => (r.v === SUPPRESSED ? '<span class="supp">&lt;5</span>' : fmt(r.v)));
  tr.append("td").attr("class", "num").text(r => (r.e == null ? "–" : fmt1(r.e)));
  tr.append("td").attr("class", "num").text(r => fmt1(r.s));
  tr.append("td").html(r => `<span class="badge alert">▲ ${DIS[r.dis]}</span>` + (r.prov ? ' <span class="badge">provisional</span>' : ""));
  if (!rows.length) tb.append("tr").append("td").attr("colspan", 8).text("No alerts in this period at the current threshold.");
  d3.select("#table-caption").text(`${rows.length} alert-weeks for ${DIS[state.disease]} ` +
    `${state.district ? "in " + districtName(state.district) : "across all districts"} between ` +
    `${fmtDate(parseDate(w.weeks[i0]))} and ${fmtDate(parseDate(w.weeks[i1]))}. Signal = standard deviations above the ` +
    `expected count (${w.method === "historical_limits" ? "seasonal historical-limits" : "EARS C2"} method).`);
}
