// Six super-group hues with light and dark variants for the 13 groups,
// plus neutral grey for "not placed". Colors are CSS tokens on :root.

export const SUPER_HUES = 6;

export function groupIndex(gid) {
  const m = /(\d+)\s*$/.exec(gid || "");
  return m ? parseInt(m[1], 10) - 1 : -1;
}

// 13 groups: hues 0-5 base for the first 6 groups, dark variants for the rest.
export function groupColor(gid) {
  const i = groupIndex(gid);
  if (i < 0) return "var(--grey)";
  const hue = i % SUPER_HUES;
  const variant = i < SUPER_HUES ? "" : "-d";
  return `var(--h${hue}${variant})`;
}

export const NOT_PLACED = "var(--grey)";
export const TOOL_COLORS = [
  "var(--h0)", "var(--h1)", "var(--h2)", "var(--h3)", "var(--h4)", "var(--h5)",
];

export function toolColor(category, categories) {
  const i = Math.max(0, categories.indexOf(category));
  return i < TOOL_COLORS.length ? TOOL_COLORS[i] : "var(--grey)";
}
