// A real <table> that CSS turns into stacked cards below 640 px
// (td[data-label] supplies the card field labels).
export function responsiveTable(rows, columns, {onSelect} = {}) {
  const table = document.createElement("table");
  table.className = "responsive-table";
  const thead = table.createTHead();
  const hr = thead.insertRow();
  for (const col of columns) {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = col.label ?? col.key;
    hr.append(th);
  }
  const tbody = table.createTBody();
  for (const row of rows) {
    const tr = tbody.insertRow();
    for (const col of columns) {
      const td = tr.insertCell();
      td.setAttribute("data-label", col.label ?? col.key);
      const v = row[col.key];
      if (col.title) {
        const t = col.title(v, row);
        if (t != null && t !== "") td.setAttribute("title", t);
      }
      td.textContent = col.format ? col.format(v, row) : (v ?? "");
    }
    if (onSelect) {
      tr.tabIndex = 0;
      tr.classList.add("selectable");
      const pick = () => onSelect(row);
      tr.addEventListener("click", pick);
      tr.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          pick();
        }
      });
    }
  }
  return table;
}
