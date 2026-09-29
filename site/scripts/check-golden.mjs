// Checks the JS port in src/components/text.js against the shared golden
// vectors in tests/sitedata/golden_text.json (same vectors pytest checks
// against the Python original).
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {dirname, join} from "node:path";
import {fileURLToPath} from "node:url";

import {htmlToText, sha256Hex, splitSentences} from "../src/components/text.js";

const here = dirname(fileURLToPath(import.meta.url));
const golden = JSON.parse(
  readFileSync(join(here, "../../tests/sitedata/golden_text.json"), "utf8")
);

for (const v of golden.html_to_text) {
  assert.equal(htmlToText(v.input), v.output, `htmlToText(${v.input})`);
}
for (const v of golden.split_sentences) {
  assert.deepEqual(splitSentences(v.input), v.output, `splitSentences`);
}
for (const v of golden.sha256) {
  assert.equal(await sha256Hex(v.input), v.output, `sha256Hex(${v.input})`);
}
console.log("golden: ok");
