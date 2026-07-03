const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;" })[c]);
let historyState = { limit: 25, offset: 0, sort: "created_at", order: "desc", total: 0 };
let currentItems = [];

async function api(path) {
  const response = await fetch(path);
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || response.statusText);
  }
  return response.json();
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  setTimeout(() => node.classList.remove("show"), 3500);
}

function formatValue(value) {
  if (value == null || value === "") return "empty";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function formatTimestamp(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function fieldChange(entry, field) {
  return `<div><span>${escapeHtml(field)}</span>: ${escapeHtml(formatValue(entry.before?.[field]))} <i>&rarr;</i> ${escapeHtml(formatValue(entry.after?.[field]))}</div>`;
}

function searchText(entry) {
  const productName = entry.after?.name || entry.before?.name || "";
  const fields = entry.changed_fields.flatMap((field) => [
    field,
    formatValue(entry.before?.[field]),
    formatValue(entry.after?.[field]),
  ]);
  return [
    productName,
    entry.barcode,
    entry.product_id,
    ...fields,
  ].join(" ").toLowerCase();
}

function logRow(entry) {
  const productName = entry.after?.name || entry.before?.name || `Product ${entry.product_id}`;
  return `<tr>
    <td>${escapeHtml(formatTimestamp(entry.created_at))}</td>
    <td>${escapeHtml(productName)}</td>
    <td><span class="cell-mono">${escapeHtml(entry.barcode)}</span></td>
    <td><span class="cell-mono">${escapeHtml(entry.product_id)}</span></td>
    <td class="changes-cell">
      ${entry.changed_fields.map(field => fieldChange(entry, field)).join("")}
    </td>
  </tr>`;
}

function updateSortButtons() {
  document.querySelectorAll(".log-sort").forEach((button) => {
    const active = button.dataset.sort === historyState.sort;
    button.classList.toggle("active", active);
    button.textContent = `${button.dataset.sort === "created_at" ? "Edited at" : button.dataset.sort === "product_name" ? "Product" : button.dataset.sort === "barcode" ? "Barcode" : "Product ID"}${active ? (historyState.order === "asc" ? " ↑" : " ↓") : ""}`;
  });
}

function updatePagination() {
  const start = historyState.total === 0 ? 0 : historyState.offset + 1;
  const end = Math.min(historyState.offset + historyState.limit, historyState.total);
  $("#log-page-status").textContent = historyState.total ? `${start}-${end} of ${historyState.total}` : "0 results";
  $("#log-prev").disabled = historyState.offset === 0;
  $("#log-next").disabled = historyState.offset + historyState.limit >= historyState.total;
}

function updateSummary() {
  const query = $("#log-filter-input")?.value.trim();
  if (query) {
    $("#log-summary").textContent = `${currentItems.length} match${currentItems.length === 1 ? "" : "es"} on this page · ${historyState.total} total edit${historyState.total === 1 ? "" : "s"}`;
    return;
  }
  $("#log-summary").textContent = `${historyState.total} total edit${historyState.total === 1 ? "" : "s"}`;
}

function renderRows() {
  const query = ($("#log-filter-input")?.value || "").trim().toLowerCase();
  const visibleItems = query ? currentItems.filter((entry) => searchText(entry).includes(query)) : currentItems;
  $("#log-table-body").innerHTML = visibleItems.length
    ? visibleItems.map(logRow).join("")
    : `<tr><td colspan="5" class="empty">${query ? "No matching edits on this page." : "No product edits yet."}</td></tr>`;
  updateSummary();
}

async function loadHistory() {
  try {
    const params = new URLSearchParams({
      limit: String(historyState.limit),
      offset: String(historyState.offset),
      sort: historyState.sort,
      order: historyState.order,
    });
    const result = await api(`/product-edit-history?${params.toString()}`);
    historyState.total = result.total;
    currentItems = result.items;
    renderRows();
    updateSortButtons();
    updatePagination();
  }
  catch (error) {
    currentItems = [];
    $("#log-table-body").innerHTML = `<tr><td colspan="5" class="empty">Could not load edit history.</td></tr>`;
    toast(error.message);
  }
}

document.addEventListener("click", (event) => {
  const sortButton = event.target.closest(".log-sort");
  if (sortButton) {
    if (historyState.sort === sortButton.dataset.sort) {
      historyState.order = historyState.order === "asc" ? "desc" : "asc";
    } else {
      historyState.sort = sortButton.dataset.sort;
      historyState.order = historyState.sort === "created_at" ? "desc" : "asc";
    }
    historyState.offset = 0;
    loadHistory();
    return;
  }
  if (event.target.matches("#log-prev")) {
    historyState.offset = Math.max(0, historyState.offset - historyState.limit);
    loadHistory();
    return;
  }
  if (event.target.matches("#log-next")) {
    historyState.offset += historyState.limit;
    loadHistory();
  }
});

document.addEventListener("input", (event) => {
  if (!event.target.matches("#log-filter-input")) return;
  renderRows();
});

loadHistory();
