import test from "node:test";
import assert from "node:assert/strict";
import { render, chartIds } from "../lib/md.js";

test("renders headings", () => {
  const html = render("# Title\n\n## Chapter one\n\n### Section");
  assert.match(html, /<h1>Title<\/h1>/);
  assert.match(html, /<h2>Chapter one<\/h2>/);
  assert.match(html, /<h3>Section<\/h3>/);
});

test("renders paragraphs and bold", () => {
  const html = render("First line **bold** here.\n\nSecond paragraph.");
  assert.match(html, /<p>First line <strong>bold<\/strong> here\.<\/p>/);
  assert.match(html, /<p>Second paragraph\.<\/p>/);
});

test("renders bullet lists", () => {
  const html = render("- one\n- two\n\nafter");
  assert.match(html, /<ul><li>one<\/li><li>two<\/li><\/ul>/);
  assert.match(html, /<p>after<\/p>/);
});

test("chart placeholders become mount divs", () => {
  const html = render("Text.\n\n<!-- chart:forest-top -->\n\nMore.");
  assert.match(html, /<div class="chart" data-chart="forest-top"><\/div>/);
  assert.deepEqual(chartIds("<!-- chart:a -->\n<!-- chart:b -->"), ["a", "b"]);
});

test("escapes HTML in prose", () => {
  const html = render("1 < 2 and \"quotes\" & <b>tags</b>");
  assert.match(html, /1 &lt; 2 and &quot;quotes&quot; &amp; &lt;b&gt;tags&lt;\/b&gt;/);
});

test("inline code and links are not required; raw html comments pass through harmlessly", () => {
  const html = render("<!-- a normal comment -->");
  assert.equal(html.includes("a normal comment"), false);
});
