// Opportunity profile: one card in full, used in the bottom sheet and inline.
import { tooFew } from "../lib/glyph.js";

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

export function prepare(story, cardId) {
  const c = story.cards.find((x) => x.id === cardId);
  if (!c) return null;
  const g = story.groups.find((x) => x.id === c.group);
  const sections = [
    {
      title: "Size and trend",
      lines: [
        { label: "share of problems", est: c.share },
        { label: "first half", est: c.h1 },
        { label: "second half", est: c.h2 },
        { label: "problems", text: `${c.n_problems} from ${c.n_authors} authors, ${c.n_threads} threads` },
        { label: "change q", text: c.change?.p_adj != null ? c.change.p_adj.toFixed(2) : "n/a" },
      ],
    },
    {
      title: "Money",
      lines: [
        { label: "paid", est: c.coping?.paid },
        { label: "switched", est: c.coping?.switched },
        { label: "abandoned", est: c.coping?.abandoned },
        { label: "workaround", est: c.coping?.workaround },
      ],
    },
    {
      title: "Solved or not",
      lines: c.unsolved
        ? [
            { label: "no reply fixed it", est: c.unsolved.unsolved },
            { label: "author reports a fix", est: c.unsolved.author_solved },
            { label: "launch ratio", est: c.builders?.ratio },
          ]
        : [
            { label: "replies", text: "not measured (outside top 40)" },
            { label: "launch ratio", est: c.builders?.ratio },
          ],
    },
    {
      title: "Who",
      lines: [
        { label: "real cost or worse", est: c.quality?.severe3 },
        { label: "very specific", est: c.quality?.specific3 },
        { label: "top-3 threads carry", text: c.concentration ? `${(c.concentration.top3_threads * 100).toFixed(1)}%` : "n/a" },
      ],
    },
  ];
  const pct1 = (v) => `${((v ?? 0) * 100).toFixed(1)}%`;
  const trend = !c.change
    ? null
    : c.change.p_adj < 0.05
      ? `${c.change.est >= 0 ? "rising" : "cooling"} (q ${c.change.p_adj.toFixed(2)})`
      : "no clear change";
  const summaryBits = [
    `${pct1(c.share?.est)} of problems`,
    trend,
    c.coping?.paid ? `${pct1(c.coping.paid.est)} paid` : null,
    c.unsolved ? `${pct1(c.unsolved.unsolved.est)} unsolved` : "replies not measured",
  ].filter(Boolean);
  return { id: c.id, label: c.short, statement: c.statement, group: g?.label || c.group, summary: summaryBits.join(", ") + ".", sections };
}

export function sheetHtml(card, story, fmt) {
  const p = prepare(story, card.id);
  if (!p) return `<h3>${esc(card.short)}</h3>`;
  const estLine = (l) =>
    l.est == null
      ? `<tr><td>${esc(l.label)}</td><td>${esc(l.text || "n/a")}</td></tr>`
      : tooFew(l.est)
        ? `<tr><td>${esc(l.label)}</td><td><em>too few mentions to show</em></td></tr>`
        : `<tr><td>${esc(l.label)}</td><td>${fmt.pct(l.est.est, 1)} <span class="cell-label">95% ${fmt.pct(l.est.lo95, 1)}-${fmt.pct(l.est.hi95, 1)}, n=${fmt.n(l.est.n)}</span></td></tr>`;
  const secs = p.sections
    .map((s) => `<h4 style="margin:10px 0 4px">${esc(s.title)}</h4><table>${s.lines.map(estLine).join("")}</table>`)
    .join("");
  return `<h3>${esc(p.label)}</h3>
    <p class="def">${esc(p.statement)}</p>
    <p class="def"><span class="gchip">${esc(p.group)}</span></p>
    <p>${esc(p.summary)}</p>${secs}`;
}

export function mount(el, story, api) {
  el.innerHTML = "";
  const host = document.createElement("div");
  el.appendChild(host);
  const renderIt = () => {
    const id = api.followedCard() || [...story.cards].sort((a, b) => b.share.est - a.share.est)[0]?.id;
    const card = story.cards.find((c) => c.id === id);
    host.innerHTML = card ? `<div style="border:1px solid var(--line);border-radius:8px;padding:10px 12px">${sheetHtml(card, story, api.fmt)}</div>` : "";
  };
  renderIt();
  api.onFollow(renderIt);
}
