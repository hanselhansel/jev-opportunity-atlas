# Jev Opportunity Atlas

```js
const metaRows = FileAttachment("data/meta.parquet").parquet();
const meta = Object.fromEntries(metaRows.map((r) => [r.key, r.value]));
```

Mode: ${meta.mode}
