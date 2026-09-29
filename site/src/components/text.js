// Port of atlas.sources.htmltext (L1, amendment A11): HN comment HTML to plain
// text and a conservative sentence splitter. Kept free of observablehq imports
// so node can check it against tests/sitedata/golden_text.json.

export const MAX_SENTENCES = 255; // Jev Choice accepts at most 255 options
const ABBREV = ["e.g.", "i.e.", "etc.", "vs.", "cf."];

const NAMED = {amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " "};

function decodeEntities(text) {
  return text.replace(/&(#[0-9]+|#[xX][0-9a-fA-F]+|[a-zA-Z]+);/g, (m, body) => {
    if (body.startsWith("#")) {
      const hex = body[1] === "x" || body[1] === "X";
      const code = parseInt(body.slice(hex ? 2 : 1), hex ? 16 : 10);
      return Number.isNaN(code) ? m : String.fromCodePoint(code);
    }
    return Object.hasOwn(NAMED, body) ? NAMED[body] : m;
  });
}

const TOKEN = /<!--[\s\S]*?-->|<[^>]*>/g;

export function htmlToText(raw) {
  if (!raw) return "";
  const parts = [];
  let last = 0;
  for (const m of raw.matchAll(TOKEN)) {
    parts.push(decodeEntities(raw.slice(last, m.index)));
    const tag = m[0];
    if (!tag.startsWith("<!--") && !/^<\s*\//.test(tag)) {
      const name = /^<\s*([a-zA-Z][a-zA-Z0-9]*)/.exec(tag)?.[1]?.toLowerCase();
      if (name === "p" || name === "pre") parts.push("\n\n");
    }
    last = m.index + tag.length;
  }
  parts.push(decodeEntities(raw.slice(last)));
  return parts
    .join("")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/^\n+/, "")
    .replace(/\n+$/, "")
    .trimEnd();
}

const BOUNDARY = /(?<=[.!?])\s+(?=\S)|\n{2,}/;

export function splitSentences(text) {
  const pieces = text
    .split(BOUNDARY)
    .map((s) => s.trim())
    .filter((s) => s);
  const merged = [];
  for (const piece of pieces) {
    const prev = merged[merged.length - 1];
    if (prev && ABBREV.some((a) => prev.toLowerCase().endsWith(a))) {
      merged[merged.length - 1] = `${prev} ${piece}`;
    } else {
      merged.push(piece);
    }
  }
  if (merged.length > MAX_SENTENCES) {
    merged.splice(
      MAX_SENTENCES - 1,
      merged.length,
      merged.slice(MAX_SENTENCES - 1).join(" ")
    );
  }
  return merged;
}

export async function sha256Hex(text) {
  const buf = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(text)
  );
  return [...new Uint8Array(buf)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
