const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;" })[c]);
let events = [];
let options = { locations: [], quantity_units: [] };
let activeFilter = "all";
let activePreview = null;
let dashboardSignature = "";

async function api(path, init) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!response.ok) throw new Error((await response.json()).detail || response.statusText);
  return response.status === 204 ? null : response.json();
}
function toast(message) {
  const node = $("#toast"); node.textContent = message; node.classList.add("show");
  setTimeout(() => node.classList.remove("show"), 3500);
}
function setQuickScanBusy(busy) {
  const form = $("#quick-scan");
  form.classList.toggle("busy", busy);
  form.querySelector("input").disabled = busy;
}
function setButtonBusy(button, busy, label) {
  if (!button) return;
  if (busy) button.dataset.label = button.textContent;
  button.disabled = busy;
  button.classList.toggle("busy-button", busy);
  button.textContent = busy ? label : button.dataset.label || button.textContent;
}
function isLoading(event) { return event.status === "processing"; }
function needsReview(event) { return ["pending", "researching", "failed"].includes(event.status); }
function image(event) {
  if (event.image_url) return `<img src="${escapeHtml(event.image_url)}" alt="">`;
  if (isLoading(event)) return `<div class="placeholder"><strong>...</strong><i class="scan-beam"></i></div>`;
  return `<div class="placeholder barcode-art"><i></i></div>`;
}
function operationBadge(event) {
  if (event.status === "processing") return "Working...";
  if (event.status === "researching") return event.product_name ? "Review match" : "Unknown";
  if (event.status === "pending") return event.product_name ? "Review match" : "Unknown";
  if (event.status === "failed") return event.product_name ? "Operation failed" : "Failed";
  if (event.mode === "set") return `Set ${event.quantity}`;
  return `${event.mode === "add" ? "+" : "−"}${event.quantity}`;
}
function operationClass(event) {
  if (isLoading(event)) return "pending";
  if (event.status === "failed") return "failed";
  if (needsReview(event)) return "pending";
  return event.mode;
}
function title(event) {
  if (event.product_name) return event.product_name;
  if (event.status === "processing") return "Processing scan";
  return "Unknown product";
}
function captionStatus(event, review) {
  if (isLoading(event)) return "IN PROGRESS";
  if (review) return event.status === "failed" ? "NEEDS ATTENTION" : "ACTION NEEDED";
  return "APPLIED";
}
function eventSignature(event) {
  return {
    event_id: event.event_id,
    barcode: event.barcode,
    mode: event.mode,
    quantity: event.quantity,
    location_id: event.location_id,
    status: event.status,
    product_id: event.product_id,
    product_name: event.product_name,
    image_url: event.image_url,
    stock_before: event.stock_before,
    stock_after: event.stock_after,
    lookup_payload: event.lookup_payload,
    error: event.error,
    created_at: event.created_at
  };
}
function optionsSignature(nextOptions) {
  return {
    locations: nextOptions.locations.map(x => ({ id: x.id, name: x.name })),
    quantity_units: nextOptions.quantity_units.map(x => ({ id: x.id, name: x.name }))
  };
}
function dataSignature(nextEvents, nextOptions) {
  return JSON.stringify({ events: nextEvents.map(eventSignature), options: optionsSignature(nextOptions) });
}
function subtitle(event) {
  const change = event.stock_before == null ? "" : `Stock ${event.stock_before} → ${event.stock_after}`;
  const location = options.locations.find(x => x.id === event.location_id)?.name;
  return [change, location, event.device_id, event.created_at].filter(Boolean).map(escapeHtml).join(" · ");
}
function card(event, index) {
  const review = needsReview(event);
  const result = event.lookup_payload?.result;
  return `<article class="polaroid ${review || isLoading(event) ? "review" : "applied"} ${event.status}" data-event="${escapeHtml(event.event_id)}" style="--delay:${Math.min(index, 10) * 35}ms">
    <div class="photo">${image(event)}<em class="badge ${operationClass(event)}">${escapeHtml(operationBadge(event))}</em></div>
    <div class="caption"><span>${captionStatus(event, review)}</span>
      <h2>${escapeHtml(title(event))}</h2>
      ${result?.alternate_names ? Object.entries(result.alternate_names).slice(0, 1).map(([lang, name]) => `<p class="alternate">${escapeHtml(lang.toUpperCase())}: ${escapeHtml(name)}</p>`).join("") : ""}
      <p>${subtitle(event) || escapeHtml(event.barcode)}</p>${event.error ? `<p class="error">${escapeHtml(event.error)}</p>` : ""}
      ${review && !isLoading(event) ? `<button class="review-button">Review details</button>` : ""}</div></article>`;
}
function render() {
  const visible = events.filter(event => activeFilter === "review" ? needsReview(event) : activeFilter === "applied" ? event.status === "applied" : activeFilter === "failed" ? event.status === "failed" : true);
  $("#all-count").textContent = events.length;
  $("#review-count").textContent = events.filter(needsReview).length;
  $("#event-grid").innerHTML = visible.length ? visible.map(card).join("") : `<div class="empty">No scans in this view yet.</div>`;
}
function reviewForm(event) {
  const result = event.lookup_payload?.result || {};
  const alternate = result.alternate_names ? Object.entries(result.alternate_names).map(([lang, name]) => `Alternate (${lang.toUpperCase()}): ${name}`).join("\n") : "";
  const description = [alternate, result.source ? `Lookup source: ${result.source}` : "", event.error || ""].filter(Boolean).join("\n");
  const locations = options.locations.map(x => `<option value="${x.id}" ${x.id === event.location_id ? "selected" : ""}>${escapeHtml(x.name)}</option>`).join("");
  const units = options.quantity_units.map(x => `<option value="${x.id}">${escapeHtml(x.name)}</option>`).join("");
  return `<div class="drawer-image">${image(event)}<span class="drawer-badge ${operationClass(event)}">${escapeHtml(operationBadge(event))}</span></div>
    <p class="drawer-kicker">${escapeHtml(event.status)} · ${escapeHtml(event.barcode)}</p><h2>${escapeHtml(event.product_name || "Unknown product")}</h2>
    <p class="drawer-operation">Pending operation: <b>${event.mode.toUpperCase()} ${event.quantity}</b></p>
    <form class="review-form" data-event="${escapeHtml(event.event_id)}"><label>Product name<input name="name" value="${escapeHtml(event.product_name || "")}" required></label>
      <label>Brand<input name="brand" value="${escapeHtml(result.brand || "")}"></label><label>Package quantity<input name="quantity" value="${escapeHtml(result.quantity || "")}"></label>
      <label>Image URL<input name="image_url" value="${escapeHtml(event.image_url || "")}"></label><label>Description<textarea name="description">${escapeHtml(description)}</textarea></label>
      <div class="form-pair"><label>Location<select name="location_id">${locations}</select></label><label>Quantity unit<select name="qu_id">${units}</select></label></div>
      <button type="submit">Create in Grocy + apply scan</button>${event.status !== "failed" ? `<button type="button" class="secondary refresh-event">Refresh lookup</button>` : ""}</form>`;
}
function openDrawer(eventId) {
  const event = events.find(x => x.event_id === eventId);
  if (!event || !needsReview(event)) return;
  $("#drawer-content").innerHTML = reviewForm(event);
  $("#review-drawer").classList.add("open"); $("#drawer-backdrop").classList.remove("hidden");
}
function closeDrawer() { $("#review-drawer").classList.remove("open"); $("#drawer-backdrop").classList.add("hidden"); }
function previewImage(product) {
  return product?.image_url ? `<img src="${escapeHtml(product.image_url)}" alt="">` : `<div class="placeholder barcode-art"><i></i></div>`;
}
function previewDialog(preview) {
  const product = preview.product || {};
  const source = preview.resolution === "grocy" ? "Existing Grocy product" : preview.resolution === "grocy_auto_created" ? "Trusted match added to Grocy" : preview.resolution === "lookup" ? `Suggested by ${product.source || "Ultimate Lookup"}` : "Unknown product";
  const locations = options.locations.map(x => `<button type="button" class="choice location-choice" data-value="${x.id}">${escapeHtml(x.name)}</button>`).join("");
  return `<div class="preview-photo">${previewImage(product)}</div><p class="drawer-kicker">${escapeHtml(source)}</p><h2>${escapeHtml(product.name || "Unknown product")}</h2>
    <p class="preview-barcode">${escapeHtml(preview.barcode)}</p>${product.stock_amount != null ? `<p class="current-stock">Current stock: <b>${product.stock_amount}</b> ${escapeHtml(product.quantity_unit || "")}</p>` : ""}
    <form id="preview-confirm-form"><fieldset><legend>Operation</legend><div class="choice-group"><button type="button" class="choice mode-choice selected add-choice" data-value="add">＋ Add</button><button type="button" class="choice mode-choice remove-choice" data-value="remove">− Remove</button><button type="button" class="choice mode-choice set-choice" data-value="set">◎ Manage / Set</button></div></fieldset>
      <fieldset><legend>Quantity</legend><div class="choice-group quantity-group"><button type="button" class="choice quantity-choice selected" data-value="1">1</button><button type="button" class="choice quantity-choice" data-value="2">2</button><button type="button" class="choice quantity-choice" data-value="3">3</button><input id="custom-quantity" type="number" min="0" step="0.01" value="1" aria-label="Custom quantity"></div></fieldset>
      <fieldset><legend>Location</legend><div class="choice-group location-group"><button type="button" class="choice location-choice selected" data-value="">Product default</button>${locations}</div></fieldset>
      <button type="submit" class="confirm-scan">Confirm Add 1</button></form>`;
}
function updateConfirmLabel() {
  const form = $("#preview-confirm-form"); if (!form) return;
  const mode = form.querySelector(".mode-choice.selected")?.dataset.value || "add";
  form.querySelector(".confirm-scan").textContent = `Confirm ${{ add: "Add", remove: "Remove", set: "Set stock to" }[mode]} ${$("#custom-quantity").value}`;
}
function openScanDialog(preview) {
  activePreview = preview; $("#scan-preview-content").innerHTML = previewDialog(preview); $("#scan-dialog").showModal(); updateConfirmLabel();
}
async function load() {
  try {
    const [nextEvents, nextOptions] = await Promise.all([api("/scan-events?limit=200"), api("/dashboard/options")]);
    const nextSignature = dataSignature(nextEvents, nextOptions);
    events = nextEvents;
    options = nextOptions;
    if (nextSignature === dashboardSignature) return;
    dashboardSignature = nextSignature;
    render();
  }
  catch (error) { toast(error.message); }
}
$("#quick-scan").addEventListener("submit", async event => {
  event.preventDefault(); const barcode = new FormData(event.target).get("barcode").trim();
  setQuickScanBusy(true);
  try { openScanDialog(await api(`/scan-preview/${encodeURIComponent(barcode)}`)); event.target.barcode.value = ""; }
  catch (error) { toast(error.message); }
  finally { setQuickScanBusy(false); }
});
document.addEventListener("click", async event => {
  const filter = event.target.closest("[data-filter]");
  if (filter) { activeFilter = filter.dataset.filter; document.querySelectorAll("[data-filter]").forEach(x => x.classList.toggle("active", x === filter)); return render(); }
  const polaroid = event.target.closest(".polaroid.review"); if (polaroid) return openDrawer(polaroid.dataset.event);
  const choice = event.target.closest(".choice");
  if (choice) {
    choice.closest(".choice-group").querySelectorAll(".choice").forEach(x => x.classList.remove("selected")); choice.classList.add("selected");
    if (choice.classList.contains("quantity-choice")) $("#custom-quantity").value = choice.dataset.value; return updateConfirmLabel();
  }
  if (event.target.matches("#close-scan-dialog")) { $("#scan-dialog").close(); return $("#quick-scan input").focus(); }
  if (event.target.matches("#close-drawer") || event.target.matches("#drawer-backdrop")) return closeDrawer();
  if (event.target.matches(".refresh-event")) {
    try { await api(`/scan-events/${event.target.closest("form").dataset.event}/refresh`, { method: "POST" }); closeDrawer(); await load(); } catch (error) { toast(error.message); }
  }
});
document.addEventListener("input", event => {
  if (event.target.matches("#custom-quantity")) { event.target.closest(".quantity-group").querySelectorAll(".choice").forEach(x => x.classList.toggle("selected", x.dataset.value === event.target.value)); updateConfirmLabel(); }
});
document.addEventListener("submit", async event => {
  if (event.target.matches("#preview-confirm-form")) {
    event.preventDefault();
    const mode = event.target.querySelector(".mode-choice.selected").dataset.value;
    const location = event.target.querySelector(".location-choice.selected").dataset.value;
    const quantity = Number($("#custom-quantity").value);
    if (mode === "set" && !confirm(`Set stock to ${quantity}?`)) return;
    const data = { event_id: `dashboard-manual-${Date.now()}`, device_id: "dashboard-manual", barcode: activePreview.barcode, mode, quantity };
    if (location) data.location_id = Number(location);
    const button = event.target.querySelector(".confirm-scan"); setButtonBusy(button, true, "Updating Grocy...");
    try { await api("/scan-events", { method: "POST", body: JSON.stringify(data) }); $("#scan-dialog").close(); activePreview = null; await load(); $("#quick-scan input").focus(); } catch (error) { toast(error.message); }
    finally { setButtonBusy(button, false); }
    return;
  }
  if (!event.target.matches(".review-form")) return;
  event.preventDefault(); const data = Object.fromEntries(new FormData(event.target)); data.location_id = Number(data.location_id); data.qu_id = Number(data.qu_id); if (!data.image_url) delete data.image_url;
  const button = event.target.querySelector('button[type="submit"]'); setButtonBusy(button, true, "Adding to Grocy...");
  try { await api(`/scan-events/${event.target.dataset.event}/confirm`, { method: "POST", body: JSON.stringify(data) }); closeDrawer(); await load(); } catch (error) { toast(error.message); }
  finally { setButtonBusy(button, false); }
});
load(); setInterval(load, 12000);
