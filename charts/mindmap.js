// "Find your need" navigator: groups -> cards, indented outline with inline
// share numbers, one group open at a time, search box, follow-this-card.
import { groupColor } from "../lib/palette.js";

export function prepare(story) {
  const groups = story.groups.map((g) => ({
    id: g.id,
    label: g.label,
    share: g.share?.est ?? 0,
    cards: (g.cards || [])
      .map((id) => story.cards.find((c) => c.id === id))
      .filter(Boolean)
      .sort((a, b) => b.share.est - a.share.est)
      .map((c) => ({ id: c.id, label: c.short, share: c.share.est, statement: c.statement })),
  }));
  return { groups };
}

const state = { openGroup: null, query: "" };
let repaint = null;

export function mount(el, story, api) {
  const { groups } = prepare(story);
  state.openGroup = null;

  const paint = () => {
    el.innerHTML = "";
    const q = state.query.trim().toLowerCase();
    for (const g of groups) {
      const cards = q ? g.cards.filter((c) => (c.label + " " + c.statement).toLowerCase().includes(q)) : g.cards;
      if (q && !cards.length) continue;
      const gEl = document.createElement("div");
      gEl.style.marginBottom = "6px";
      const head = document.createElement("button");
      head.type = "button";
      head.style.cssText = "display:block;width:100%;text-align:left;border:0;background:none;color:inherit;font-weight:700;padding:8px 6px;cursor:pointer;min-height:44px";
      const sw = document.createElement("span");
      sw.style.cssText = `display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;background:${groupColor(g.id)}`;
      head.appendChild(sw);
      head.appendChild(document.createTextNode(`${g.label} `));
      const meta = document.createElement("span");
      meta.className = "cell-label";
      meta.textContent = `${(g.share * 100).toFixed(1)}% · ${g.cards.length} cards`;
      head.appendChild(meta);
      head.addEventListener("click", () => {
        state.openGroup = state.openGroup === g.id ? null : g.id;
        paint();
      });
      gEl.appendChild(head);
      if (q || state.openGroup === g.id) {
        for (const c of cards) {
          const row = document.createElement("button");
          row.type = "button";
          row.dataset.card = c.id;
          row.style.cssText = "display:block;width:100%;text-align:left;border:0;background:none;color:inherit;padding:7px 6px 7px 22px;cursor:pointer;min-height:44px";
          const t1 = document.createElement("span");
          t1.textContent = `${c.label} `;
          const t2 = document.createElement("span");
          t2.className = "cell-label";
          t2.textContent = `${(c.share * 100).toFixed(2)}%`;
          const br = document.createElement("br");
          const t3 = document.createElement("span");
          t3.className = "cell-label";
          t3.textContent = c.statement;
          row.append(t1, t2, br, t3);
          row.addEventListener("click", () => {
            api.followCard(c.id);
            api.openSheet(c.id);
          });
          gEl.appendChild(row);
        }
      }
      el.appendChild(gEl);
    }
    const f = api.followedCard?.();
    if (f) el.querySelectorAll(`[data-card="${f}"]`).forEach((n) => n.classList.add("mark-followed"));
  };
  repaint = paint;
  paint();
  api.onFollow?.(paint);
}

export function filter(q) {
  state.query = q || "";
  repaint?.();
}
