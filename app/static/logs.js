const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;" })[c]);
let historyState = { limit: 25, offset: 0, sort: "created_at", order: "desc", total: 0, query: "", view: "entries" };
let currentItems = [];

const ENTRY_SORT_LABELS = {
  created_at: "Edited at",
  product_name: "Product",
  barcode: "Barcode",
  product_id: "Product ID",
};
const BARCODE_SORT_LABELS = {
  barcode: "Barcode",
  product_name: "Product",
  edit_count: "Edits",
  last_edited_at: "Last edited",
};

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

function bindBackdropClose(dialog) {
  if (!dialog) return;
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
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

function logRow(entry) {
  const productName = entry.after?.name || entry.before?.name || `Product ${entry.product_id}`;
  return `<tr class="log-entry-row" data-history-id="${escapeHtml(entry.id)}">
    <td>${escapeHtml(formatTimestamp(entry.created_at))}</td>
    <td>${escapeHtml(productName)}</td>
    <td><span class="cell-mono">${escapeHtml(entry.barcode)}</span></td>
    <td><span class="cell-mono">${escapeHtml(entry.product_id)}</span></td>
    <td class="changes-cell">
      ${entry.changed_fields.map(field => fieldChange(entry, field)).join("")}
    </td>
  </tr>`;
}

function barcodeRow(item) {
  return `<tr class="barcode-row" data-barcode="${escapeHtml(item.barcode)}">
    <td><span class="cell-mono">${escapeHtml(item.barcode)}</span></td>
    <td>${escapeHtml(item.product_name)}</td>
    <td><span class="cell-mono">${escapeHtml(item.edit_count)}</span></td>
    <td>${escapeHtml(formatTimestamp(item.last_edited_at))}</td>
  </tr>`;
}

function updateSortButtons() {
  document.querySelectorAll(".log-sort").forEach((button) => {
    const active = button.dataset.sort === historyState.sort;
    button.classList.toggle("active", active);
    const labels = historyState.view === "entries" ? ENTRY_SORT_LABELS : BARCODE_SORT_LABELS;
    const label = labels[button.dataset.sort] || button.textContent;
    button.textContent = `${label}${active ? (historyState.order === "asc" ? " ↑" : " ↓") : ""}`;
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
  const suffix = historyState.view === "entries" ? "edit" : "barcode";
  const noun = historyState.total === 1 ? suffix : `${suffix}s`;
  const queryNote = historyState.query ? ` matching "${historyState.query}"` : "";
  $("#log-summary").textContent = `${historyState.total} total ${noun}${queryNote}`;
}

async function loadHistory() {
  try {
    const params = new URLSearchParams({
      limit: String(historyState.limit),
      offset: String(historyState.offset),
      sort: historyState.sort,
      order: historyState.order,
      query: String(historyState.query || ""),
    });
    const result = await api(`/product-edit-history?${params.toString()}`);
    historyState.total = result.total;
    currentItems = result.items;
    $("#log-table-body").innerHTML = currentItems.length
      ? currentItems.map(logRow).join("")
      : `<tr><td colspan="5" class="empty">No product edits found.</td></tr>`;
    updateSortButtons();
    updateSummary();
    updatePagination();
  }
  catch (error) {
    currentItems = [];
    $("#log-table-body").innerHTML = `<tr><td colspan="5" class="empty">Could not load edit history.</td></tr>`;
    toast(error.message);
  }
}

async function loadBarcodeSummary() {
  try {
    const params = new URLSearchParams({
      limit: String(historyState.limit),
      offset: String(historyState.offset),
      sort: historyState.sort,
      order: historyState.order,
      query: String(historyState.query || ""),
    });
    const result = await api(`/product-edit-history/barcodes?${params.toString()}`);
    historyState.total = result.total;
    currentItems = result.items;
    $("#barcode-table-body").innerHTML = currentItems.length
      ? currentItems.map(barcodeRow).join("")
      : `<tr><td colspan="4" class="empty">No barcode summaries found.</td></tr>`;
    updateSortButtons();
    updateSummary();
    updatePagination();
  }
  catch (error) {
    currentItems = [];
    $("#barcode-table-body").innerHTML = `<tr><td colspan="4" class="empty">Could not load barcode summaries.</td></tr>`;
    toast(error.message);
  }
}

function renderLogDetail(detail) {
  const entry = detail.entry;
  const productName = entry.after?.name || entry.before?.name || `Product ${entry.product_id}`;
  return `<div class="log-detail-panel">
    <p class="drawer-kicker">${escapeHtml(entry.source)} · ${escapeHtml(formatTimestamp(entry.created_at))}</p>
    <h2>${escapeHtml(productName)}</h2>
    <p class="log-detail-meta">Barcode ${escapeHtml(entry.barcode)} · Product #${escapeHtml(entry.product_id)} · ${escapeHtml(entry.source)}</p>
    <div class="log-detail-cards">
      ${detail.diffs.map((diff) => `<article class="log-detail-card"><span>${escapeHtml(diff.field)}</span><div class="log-detail-values"><b>${escapeHtml(formatValue(diff.before))}</b><i>&rarr;</i><b>${escapeHtml(formatValue(diff.after))}</b></div></article>`).join("")}
    </div>
  </div>`;
}

async function openLogDetail(historyId) {
  try {
    const detail = await api(`/product-edit-history/${historyId}`);
    $("#log-detail-content").innerHTML = renderLogDetail(detail);
    $("#log-detail-dialog").showModal();
  }
  catch (error) {
    toast(error.message);
  }
}

function setView(view) {
  historyState.view = view;
  historyState.offset = 0;
  if (view === "entries") {
    if (!ENTRY_SORT_LABELS[historyState.sort]) {
      historyState.sort = "created_at";
      historyState.order = "desc";
    }
    $("#log-entries-view").classList.remove("hidden");
    $("#log-barcodes-view").classList.add("hidden");
  } else {
    if (!BARCODE_SORT_LABELS[historyState.sort]) {
      historyState.sort = "last_edited_at";
      historyState.order = "desc";
    }
    $("#log-barcodes-view").classList.remove("hidden");
    $("#log-entries-view").classList.add("hidden");
  }
  document.querySelectorAll("[data-log-view]").forEach((button) => button.classList.toggle("active", button.dataset.logView === view));
  loadCurrentView();
}

function loadCurrentView() {
  if (historyState.view === "barcodes") return loadBarcodeSummary();
  return loadHistory();
}

bindBackdropClose($("#log-detail-dialog"));

document.addEventListener("click", (event) => {
  const viewButton = event.target.closest("[data-log-view]");
  if (viewButton) return setView(viewButton.dataset.logView);
  const sortButton = event.target.closest(".log-sort");
  if (sortButton) {
    if (historyState.sort === sortButton.dataset.sort) {
      historyState.order = historyState.order === "asc" ? "desc" : "asc";
    } else {
      historyState.sort = sortButton.dataset.sort;
      historyState.order = historyState.sort === "created_at" || historyState.sort === "last_edited_at" ? "desc" : "asc";
    }
    historyState.offset = 0;
    loadCurrentView();
    return;
  }
  const entryRow = event.target.closest(".log-entry-row");
  if (entryRow?.dataset.historyId) return openLogDetail(entryRow.dataset.historyId);
  const barcodeRowNode = event.target.closest(".barcode-row");
  if (barcodeRowNode?.dataset.barcode) {
    $("#log-filter-input").value = barcodeRowNode.dataset.barcode;
    historyState.query = barcodeRowNode.dataset.barcode;
    return setView("entries");
  }
  if (event.target.matches("#log-prev")) {
    historyState.offset = Math.max(0, historyState.offset - historyState.limit);
    loadCurrentView();
    return;
  }
  if (event.target.matches("#log-next")) {
    historyState.offset += historyState.limit;
    loadCurrentView();
    return;
  }
  if (event.target.matches("#close-log-detail-dialog")) $("#log-detail-dialog").close();
});

document.addEventListener("input", (event) => {
  if (!event.target.matches("#log-filter-input")) return;
  historyState.query = event.target.value.trim();
  historyState.offset = 0;
  loadCurrentView();
});

loadCurrentView();
