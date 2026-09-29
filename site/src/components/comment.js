import {breadcrumbs} from "./filters.js";
import {htmlToText, sha256Hex, splitSentences} from "./text.js";

const HN_ITEM = "https://hacker-news.firebaseio.com/v0/item";
const HN_LINK = "https://news.ycombinator.com/item";

// The comment text block with its explicit states: loading skeleton, synthetic
// placeholder (fixture mode), deleted, unavailable, changed, and highlighted.
export function commentText(row, meta) {
  const box = document.createElement("div");
  box.className = "comment-text";
  if (meta?.mode === "fixture") {
    box.classList.add("skeleton");
    box.textContent = "synthetic comment (fixture mode: text is not fetched)";
    return box;
  }
  box.classList.add("skeleton");
  box.textContent = "Loading comment text from Hacker News…";
  renderRemote(box, row);
  return box;
}

async function renderRemote(box, row) {
  let item;
  let failed = false;
  try {
    const res = await fetch(`${HN_ITEM}/${row.comment_id}.json`);
    if (res.ok) item = await res.json();
    else failed = true;
  } catch {
    failed = true;
  }
  box.classList.remove("skeleton");
  if (failed) {
    box.textContent = "unavailable from HN";
    return;
  }
  if (!item || item.deleted || item.dead || !item.text) {
    box.textContent = "deleted on HN";
    return;
  }
  const text = htmlToText(item.text);
  const digest = await sha256Hex(text);
  if (digest !== row.text_sha256) {
    box.append(el("p", "changed", "text changed since classification"));
    box.append(el("p", null, text));
    return;
  }
  const sentences = splitSentences(text);
  const n = Number(String(row.support_sentence_id ?? "").slice(1));
  const frag = document.createDocumentFragment();
  sentences.forEach((s, i) => {
    if (i > 0) frag.append(" ");
    const node = document.createElement(i === n ? "mark" : "span");
    node.textContent = s;
    frag.append(node);
  });
  box.append(frag);
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

function field(label, value) {
  const dt = el("dt", null, label);
  const dd = el("dd", null, value == null || value === "" ? "—" : String(value));
  return [dt, dd];
}

function pct(v) {
  return v == null ? null : `${(Number(v) * 100).toFixed(0)}%`;
}

export function commentCard(row, state, meta) {
  const card = document.createElement("div");
  card.className = "comment-card";
  card.append(breadcrumbs(state));

  const probs = JSON.parse(row.probabilities_json ?? "{}");
  const dl = document.createElement("dl");
  dl.append(
    ...field("domain / subtopic", `${row.domain} · ${row.subtopic}`),
    ...field(
      "period / lane / thread",
      `${row.period} · ${row.lane} · ${row.thread_type}`
    ),
    ...field("firsthand", pct(row.firsthand_p)),
    ...field("specificity", row.specificity),
    ...field("workaround", pct(row.workaround_p)),
    ...field("consequence", pct(row.consequence_any_p)),
    ...field("concrete task", pct(probs.concrete_task)),
    ...field("behavior", pct(probs.behavior_any)),
    ...field("timing current", pct(probs.timing_current)),
    ...field("evidence strength", pct(row.evidence_strength)),
    ...field("TypeSafe confidence", pct(row.confidence)),
    ...field("model returned", row.model_returned),
    ...field("run", row.run_id),
    ...(row.human_label ? field("human label", row.human_label) : [])
  );
  card.append(dl);

  const link = document.createElement("a");
  link.href = `${HN_LINK}?id=${row.comment_id}`;
  link.textContent = `comment ${row.comment_id} on Hacker News`;
  card.append(link, commentText(row, meta));
  return card;
}
