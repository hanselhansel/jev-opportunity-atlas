// Tool funnel: x = distinct threads naming the tool (log), y = share named
// as a fix, with 95% funnel bounds around the overall share.
import { toolColor } from "../lib/palette.js";

const MIN_THREADS = 10;

export function prepare(story) {
  const tools = (story.tools || []).filter((t) => t.threads >= MIN_THREADS);
  const fixTot = tools.reduce((a, t) => a + t.fix_threads, 0);
  const allTot = tools.reduce((a, t) => a + t.threads, 0) || 1;
  const overall = fixTot / allTot;
  const rows = tools.map((t) => {
    const sd = Math.sqrt((overall * (1 - overall)) / Math.max(1, t.threads));
    const lo = Math.max(0, overall - 1.96 * sd), hi = Math.min(1, overall + 1.96 * sd);
    const est = t.fix_share?.est ?? t.fix_threads / Math.max(1, t.threads);
    return {
      name: t.name, category: t.category, threads: t.threads,
      fixShare: t.fix_share || { est, lo95: lo, hi95: hi },
      est,
      outside: est > hi ? "above" : est < lo ? "below" : null,
    };
  });
  const boundAt = (threads) => {
    const sd = Math.sqrt((overall * (1 - overall)) / Math.max(1, threads));
    return [Math.max(0, overall - 1.96 * sd), Math.min(1, overall + 1.96 * sd)];
  };
  return { rows, overall, boundAt };
}

export function mount(el, story, api) {
  const d3 = api.d3;
  const { rows, overall, boundAt } = prepare(story);
  el.innerHTML = "";
  const W = 700, H = 340, m = { l: 50, r: 16, t: 24, b: 36 };
  const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`);
  const x = d3.scaleLog().domain([Math.max(5, d3.min(rows, (d) => d.threads) * 0.8), d3.max(rows, (d) => d.threads) * 1.2]).range([m.l, W - m.r]);
  const y = d3.scaleLinear().domain([0, 1]).range([H - m.b, m.t]);
  const cats = [...new Set(rows.map((r) => r.category))];

  // funnel bounds
  const ts = d3.range(10, d3.max(rows, (d) => d.threads) * 1.2, 2);
  const area = d3.area().x((t) => x(t)).y0((t) => y(boundAt(t)[0])).y1((t) => y(boundAt(t)[1]));
  svg.append("path").attr("d", area(ts)).attr("fill", "var(--line)").attr("opacity", 0.4);
  svg.append("line").attr("x1", m.l).attr("x2", W - m.r).attr("y1", y(overall)).attr("y2", y(overall)).attr("stroke", "var(--muted)").attr("stroke-dasharray", "3 3");

  svg
    .selectAll("circle.t")
    .data(rows)
    .join("circle")
    .attr("cx", (d) => x(d.threads))
    .attr("cy", (d) => y(d.est))
    .attr("r", 3.2)
    .attr("fill", (d) => toolColor(d.category, cats))
    .attr("opacity", 0.8)
    .append("title")
    .text((d) => `${d.name}: ${d.threads} threads, ${api.fmt.pct(d.est, 0)} as fix`);

  rows.filter((d) => d.outside).forEach((d) => {
    svg.append("text").attr("class", "cell-label").attr("x", x(d.threads) + 5).attr("y", y(d.est) - 4).text(d.name);
  });
  svg.append("text").attr("class", "axis").attr("x", m.l).attr("y", 12).text("named as a fix");
  svg.append("text").attr("class", "axis").attr("x", m.l).attr("y", H - 4).text("named in complaints \u2193 fewer fixes");
  svg.append("text").attr("class", "axis").attr("x", W - m.r).attr("y", H - 4).attr("text-anchor", "end").text("distinct threads (log)");

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = "Being named in a complaint does not mean the tool caused it. Band: 95% funnel.";
  el.appendChild(cap);
}
