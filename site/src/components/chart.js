import * as Plot from "npm:@observablehq/plot";

import {responsiveTable} from "./table.js";

const SVG_NS = "http://www.w3.org/2000/svg";

function text(attrs, content) {
  const el = document.createElementNS(SVG_NS, "text");
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  el.textContent = content;
  return el;
}

function hatchDefs() {
  const defs = document.createElementNS(SVG_NS, "defs");
  const p = document.createElementNS(SVG_NS, "pattern");
  p.setAttribute("id", "atlas-hatch");
  p.setAttribute("width", "6");
  p.setAttribute("height", "6");
  p.setAttribute("patternUnits", "userSpaceOnUse");
  p.setAttribute("patternTransform", "rotate(45)");
  const line = document.createElementNS(SVG_NS, "line");
  line.setAttribute("x1", "0");
  line.setAttribute("y1", "0");
  line.setAttribute("x2", "0");
  line.setAttribute("y2", "6");
  line.setAttribute("class", "hatch-line");
  p.append(line);
  defs.append(p);
  return defs;
}

// One outer <svg role="img"> that frames an Observable Plot svg with the
// provenance furniture drawn INSIDE it: title, subtitle + denominator, a
// FICTIONAL DATA line in fixture mode, and a footer. Below it, a
// <details> "Show data table" disclosure.
export function chart({
  title,
  subtitle,
  denominator,
  n,
  lane,
  meta,
  plot,
  ariaLabel,
  rows,
  columns,
  qualifier,
}) {
  const fixture = meta?.mode === "fixture";
  const inner = Plot.plot(plot);
  const plotSvg =
    inner instanceof SVGSVGElement ? inner : inner.querySelector("svg");
  const w = Number(plotSvg.getAttribute("width")) || 640;
  const h = Number(plotSvg.getAttribute("height")) || 400;
  const header = fixture ? 68 : 52;
  const footer = 40;

  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", "atlas-chart-svg");
  svg.setAttribute("role", "img");
  if (ariaLabel) svg.setAttribute("aria-label", ariaLabel);
  svg.setAttribute("viewBox", `0 0 ${w} ${header + h + footer}`);
  svg.setAttribute("width", w);

  svg.append(
    hatchDefs(),
    text({x: 0, y: 16, class: "chart-title"}, title ?? ""),
    text(
      {x: 0, y: 34, class: "chart-subtitle"},
      [subtitle, denominator && `denominator: ${denominator}`]
        .filter(Boolean)
        .join(" · ")
    )
  );
  if (fixture) {
    svg.append(
      text({x: 0, y: 50, class: "chart-fiction"}, "FICTIONAL DATA")
    );
  }
  plotSvg.setAttribute("x", 0);
  plotSvg.setAttribute("y", header);
  svg.append(plotSvg);

  const fy = header + h;
  svg.append(
    text(
      {x: 0, y: fy + 14, class: "chart-footer"},
      `source: ${meta?.source ?? "?"} · window ${meta?.window_start ?? "?"} – ` +
        `${meta?.window_end ?? "?"} · lane ${lane ?? "?"} · n=${n ?? "?"} · ` +
        `run ${meta?.run_id ?? "?"}`
    ),
    text(
      {x: 0, y: fy + 30, class: "chart-footer"},
      `${qualifier ?? "as classified by Jev"} · ` +
        "HN comments only; not market demand"
    )
  );

  const wrap = document.createElement("figure");
  wrap.className = "atlas-chart";
  wrap.append(svg);
  if (rows && columns) {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Show data table";
    details.append(summary, responsiveTable(rows, columns));
    wrap.append(details);
  }
  return wrap;
}
