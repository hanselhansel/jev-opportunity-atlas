// Human-readable labels for domain and role ids. S8b adds
// story.labels.{domains,roles}; fall back to title case with spaces.

export function titleCase(id) {
  return String(id)
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function labelFor(story, kind, id) {
  return story.labels?.[kind]?.[id] ?? titleCase(id);
}
