const SHAPES = {measured: "●", calculated: "■", estimated: "◆", unknown: "?"};

export function badge(kind) {
  const el = document.createElement("span");
  el.className = `badge badge-${kind}`;
  const mark = document.createElement("span");
  mark.className = "badge-mark";
  mark.setAttribute("aria-hidden", "true");
  mark.textContent = SHAPES[kind] ?? "?";
  el.append(mark, ` ${kind}`);
  return el;
}

export function banner(meta) {
  const el = document.createElement("div");
  if (meta?.mode === "fixture") {
    el.className = "site-banner fiction";
    el.textContent = "FICTIONAL DATA: layout preview only";
  } else {
    el.className = "site-banner provenance";
    el.textContent =
      `snapshot ${meta?.snapshot_id ?? "?"} · run ${meta?.run_id ?? "?"} · ` +
      `window ${meta?.window_start ?? "?"} – ${meta?.window_end ?? "?"}`;
  }
  return el;
}
