// FileAttachment(...).parquet() returns an Apache Arrow Table, not an array.
// rowsOf converts to plain row objects; int64 columns arrive as BigInt and are
// coerced to Number (all ids here are < 2**53).
export function rowsOf(table) {
  return Array.from(table, (r) => {
    const o = typeof r.toJSON === "function" ? r.toJSON() : {...r};
    for (const k in o) if (typeof o[k] === "bigint") o[k] = Number(o[k]);
    return o;
  });
}

export function metaOf(table) {
  return Object.fromEntries(rowsOf(table).map((r) => [r.key, r.value]));
}
