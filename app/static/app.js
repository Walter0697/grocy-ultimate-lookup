const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;" })[c]);
let events = [];
let options = { locations: [], quantity_units: [] };
let activeFilter = "all";

async function api(path, init) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!response.ok) throw new Error((await response.json()).detail || response.statusText);
  return response.status === 204 ? null : response.json();
}
function toast(message) {
  const node = $("#toast"); node.textContent = message; node.classList.add("show");
  setTimeout(() => node.classList.remove("show"), 3500);
}
function needsReview(event) {
  return ["pending", "researching", "failed"].includes(event.status);
}
function image(event) {
  if (event.image_url) return `<img src="${escapeHtml(event.image_url)}" alt="">`;
  if (event.status === "researching") return `<div class="placeholder"><strong>?</strong><i class="scan-beam"></i></div>`;
  return `<div class="placeholder barcode-art"><i></i></div>`;
}
function operationBadge(event) {
  if (event.status === "researching") return "Researching";
  if (event.status === "pending") return event.product_name ? "Review match" : "Unknown";
  if (event.status === "failed") return "Failed";
  if (event.mode === "set") return `Set ${event.quantity}`;
  return `${event.mode === "add" ? "+" : "−"}${event.quantity}`;
}
function operationClass(event) {
  if (event.status === "failed") return "failed";
  if (needsReview(event)) return "pending";
  return event.mode;
}
function delta(event) {
  if (event.stock_before == null || event.stock_after == null) return "";
  return `Stock ${event.stock_before} → ${event.stock_after}`;
}
function subtitle(event) {
  const location = options.locations.find(x => x.id === event.location_id)?.name;
  return [delta(event), location, event.device_id, event.created_at].filter(Boolean).map(escapeHtml).join(" · ");
}
function card(event, index) {
  const review = needsReview(event);
  const result = event.lookup_payload?.result;
  return `<article class="polaroid ${review ? "review" : "applied"} ${event.status}" data-event="${escapeHtml(event.event_id)}" style="--delay:${Math.min(index, 10) * 35}ms">
    <div class="photo">${image(event)}<em class="badge ${operationClass(event)}">${escapeHtml(operationBadge(event))}</em></div>
    <div class="caption">
      <span>${escapeHtml(review ? (event.status === "failed" ? "NEEDS ATTENTION" : "ACTION NEEDED") : "APPLIED")}</span>
      <h2>${escapeHtml(event.product_name || "Unknown product")}</h2>
      ${result?.alternate_names ? Object.entries(result.alternate_names).slice(0, 1).map(([lang, name]) => `<p class="alternate">${escapeHtml(lang.toUpperCase())}: ${escapeHtml(name)}</p>`).join("") : ""}
      <p>${subtitle(event) || escapeHtml(event.barcode)}</p>
      ${event.error ? `<p class="error">${escapeHtml(event.error)}</p>` : ""}
      ${review ? `<button class="review-button">Review details</button>` : ""}
    </div>
  </article>`;
}
function render() {
  const visible = events.filter(event => {
    if (activeFilter === "review") return needsReview(event);
    if (activeFilter === "applied") return event.status === "applied";
    if (activeFilter === "failed") return event.status === "failed";
    return true;
  });
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
    <p class="drawer-kicker">${escapeHtml(event.status)} · ${escapeHtml(event.barcode)}</p>
    <h2>${escapeHtml(event.product_name || "Unknown product")}</h2>
    <p class="drawer-operation">Pending operation: <b>${event.mode.toUpperCase()} ${event.quantity}</b></p>
    <form class="review-form" data-event="${escapeHtml(event.event_id)}">
      <label>Product name<input name="name" value="${escapeHtml(event.product_name || "")}" required></label>
      <label>Brand<input name="brand" value="${escapeHtml(result.brand || "")}"></label>
      <label>Package quantity<input name="quantity" value="${escapeHtml(result.quantity || "")}"></label>
      <label>Image URL<input name="image_url" value="${escapeHtml(event.image_url || "")}"></label>
      <label>Description<textarea name="description">${escapeHtml(description)}</textarea></label>
      <div class="form-pair"><label>Location<select name="location_id">${locations}</select></label><label>Quantity unit<select name="qu_id">${units}</select></label></div>
      <button type="submit">Create in Grocy + apply scan</button>
      ${event.status === "researching" || event.status === "pending" ? `<button type="button" class="secondary refresh-event">Refresh lookup</button>` : ""}
    </form>`;
}
function openDrawer(eventId) {
  const event = events.find(x => x.event_id === eventId);
  if (!event || !needsReview(event)) return;
  $("#drawer-content").innerHTML = reviewForm(event);
  $("#review-drawer").classList.add("open");
  $("#review-drawer").setAttribute("aria-hidden", "false");
  $("#drawer-backdrop").classList.remove("hidden");
}
function closeDrawer() {
  $("#review-drawer").classList.remove("open");
  $("#review-drawer").setAttribute("aria-hidden", "true");
  $("#drawer-backdrop").classList.add("hidden");
}
async function load() {
  try {
    [events, options] = await Promise.all([api("/scan-events?limit=200"), api("/dashboard/options")]);
    const locationSelect = $("#scan-form [name=location_id]");
    const selected = locationSelect.value;
    locationSelect.innerHTML = `<option value="">Product default</option>${options.locations.map(x => `<option value="${x.id}">${escapeHtml(x.name)}</option>`).join("")}`;
    locationSelect.value = selected;
    render();
  } catch (error) { toast(error.message); }
}
$("#toggle-scanner").addEventListener("click", () => {
  $("#manual-scanner").classList.toggle("hidden");
  if (!$("#manual-scanner").classList.contains("hidden")) $("#scan-form [name=barcode]").focus();
});
$("#scan-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  data.quantity = Number(data.quantity);
  data.event_id = `${data.device_id}-${Date.now()}`;
  if (data.location_id) data.location_id = Number(data.location_id); else delete data.location_id;
  if (data.mode === "set" && !confirm(`Set stock to ${data.quantity}?`)) return;
  try {
    await api("/scan-events", { method: "POST", body: JSON.stringify(data) });
    event.target.barcode.value = "";
    await load();
  } catch (error) { toast(error.message); }
});
document.addEventListener("click", async (event) => {
  const filter = event.target.closest("[data-filter]");
  if (filter) {
    activeFilter = filter.dataset.filter;
    document.querySelectorAll("[data-filter]").forEach(x => x.classList.toggle("active", x === filter));
    render();
    return;
  }
  const polaroid = event.target.closest(".polaroid.review");
  if (polaroid) return openDrawer(polaroid.dataset.event);
  if (event.target.matches("#close-drawer") || event.target.matches("#drawer-backdrop")) return closeDrawer();
  if (event.target.matches(".refresh-event")) {
    try { await api(`/scan-events/${event.target.closest("form").dataset.event}/refresh`, { method: "POST" }); closeDrawer(); await load(); }
    catch (error) { toast(error.message); }
  }
});
document.addEventListener("submit", async (event) => {
  if (!event.target.matches(".review-form")) return;
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  data.location_id = Number(data.location_id); data.qu_id = Number(data.qu_id);
  if (!data.image_url) delete data.image_url;
  try { await api(`/scan-events/${event.target.dataset.event}/confirm`, { method: "POST", body: JSON.stringify(data) }); closeDrawer(); await load(); }
  catch (error) { toast(error.message); }
});
load();
setInterval(load, 12000);
