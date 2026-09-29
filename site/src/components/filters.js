// Shared filter state in the URL hash so a breadcrumb path is shareable:
// #lane=breadth&domain=Domain%20B. No observablehq imports: node-safe.

const KEYS = ["lane", "domain", "subtopic", "from", "to", "comment"];

export function readState(hash) {
  const params = new URLSearchParams(String(hash ?? "").replace(/^#/, ""));
  const state = {};
  for (const k of KEYS) state[k] = params.get(k);
  if (state.lane !== "discovery") state.lane = "breadth";
  return state;
}

export function encodeState(state) {
  const parts = [];
  for (const k of KEYS) {
    const v = state[k];
    if (v != null && v !== "") parts.push(`${k}=${encodeURIComponent(v)}`);
  }
  return `#${parts.join("&")}`;
}

export function setState(patch) {
  const next = {...readState(location.hash), ...patch};
  location.hash = encodeState(next);
}

export function onHashChange(cb) {
  const handler = () => cb(readState(location.hash));
  addEventListener("hashchange", handler);
  return () => removeEventListener("hashchange", handler);
}

export function breadcrumbs(state) {
  const nav = document.createElement("nav");
  nav.className = "breadcrumbs";
  nav.setAttribute("aria-label", "breadcrumb");
  const crumbs = [{label: "Findings", href: "./"}];
  if (state.domain) {
    crumbs.push({
      label: state.domain,
      href: encodeState({...state, subtopic: null, comment: null}),
    });
  }
  if (state.subtopic) {
    crumbs.push({
      label: state.subtopic,
      href: encodeState({...state, comment: null}),
    });
  }
  if (state.comment) crumbs.push({label: `comment ${state.comment}`});
  crumbs.forEach((c, i) => {
    if (i > 0) nav.append(document.createTextNode(" › "));
    if (c.href) {
      const a = document.createElement("a");
      a.href = c.href;
      a.textContent = c.label;
      nav.append(a);
    } else {
      const s = document.createElement("span");
      s.textContent = c.label;
      nav.append(s);
    }
  });
  return nav;
}
