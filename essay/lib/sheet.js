// One sticky bottom detail sheet shared by every chart.

export function createSheet(el) {
  el.classList.add("sheet");
  el.innerHTML = `
    <div class="sheet-bar">
      <button type="button" class="sheet-prev" aria-label="Previous">&#8592;</button>
      <button type="button" class="sheet-next" aria-label="Next">&#8594;</button>
      <button type="button" class="sheet-close" aria-label="Close">&#215;</button>
    </div>
    <div class="sheet-body" role="dialog" aria-live="polite"></div>`;
  const body = el.querySelector(".sheet-body");
  let nav = { prev: null, next: null };

  el.querySelector(".sheet-close").addEventListener("click", () => close());
  el.querySelector(".sheet-prev").addEventListener("click", () => nav.prev && nav.prev());
  el.querySelector(".sheet-next").addEventListener("click", () => nav.next && nav.next());

  function open(html, handlers = {}) {
    body.innerHTML = html;
    nav = { prev: handlers.prev || null, next: handlers.next || null };
    el.querySelector(".sheet-prev").disabled = !nav.prev;
    el.querySelector(".sheet-next").disabled = !nav.next;
    el.classList.add("open");
  }
  function close() {
    el.classList.remove("open");
  }
  return { open, close, body, isOpen: () => el.classList.contains("open") };
}
