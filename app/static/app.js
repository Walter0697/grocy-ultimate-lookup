const $ = (selector) => document.querySelector(selector);
let options = { locations: [], quantity_units: [] };
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;" })[c]);

async function api(path, init) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!response.ok) throw new Error((await response.json()).detail || response.statusText);
  return response.status === 204 ? null : response.json();
}
function image(url) {
  return url ? `<img src="${url}" alt="">` : `<div class="image-placeholder">NO IMAGE</div>`;
}
function delta(event) {
  if (event.stock_before == null || event.stock_after == null) return "";
  const change = event.stock_after - event.stock_before;
  return change === 0 ? `=${event.stock_after}` : `${change > 0 ? "+" : ""}${change}`;
}
function toast(message) {
  const node = $("#toast"); node.textContent = message; node.style.display = "block";
  setTimeout(() => node.style.display = "none", 3500);
}
function eventCard(event) {
  return `<article class="card">
    ${image(event.image_url)}${delta(event) ? `<span class="delta">${delta(event)}</span>` : ""}
    <div class="card-body">
      <p class="status status-${event.status}">${event.status}</p>
      <h3>${escapeHtml(event.product_name || "Unknown product")}</h3>
      <p class="meta">${escapeHtml(event.barcode)}<br>${escapeHtml(event.device_id)} · ${event.mode.toUpperCase()} ${event.quantity}<br>${event.created_at}</p>
      ${event.stock_after != null ? `<p class="stock">Stock now: ${event.stock_after}</p>` : ""}
      ${event.error ? `<p class="meta">${escapeHtml(event.error)}</p>` : ""}
    </div>
  </article>`;
}
function pendingCard(event) {
  const result = event.lookup_payload?.result || {};
  const description = [
    result.alternate_names ? Object.entries(result.alternate_names).map(([k,v]) => `Alternate (${k.toUpperCase()}): ${v}`).join("\n") : "",
    result.source ? `Lookup source: ${result.source}` : "",
    event.lookup_payload?.research_status ? `Research: ${event.lookup_payload.research_status}` : ""
  ].filter(Boolean).join("\n");
  const locationOptions = options.locations.map(x => `<option value="${x.id}">${escapeHtml(x.name)}</option>`).join("");
  const quOptions = options.quantity_units.map(x => `<option value="${x.id}">${escapeHtml(x.name)}</option>`).join("");
  return `<article class="card">
    ${image(event.image_url)}
    <div class="card-body">
      <p class="status status-${event.status}">${event.status}</p>
      <h3>${escapeHtml(event.product_name || "Unknown product")}</h3>
      <p class="meta">${escapeHtml(event.barcode)}<br>Pending ${event.mode.toUpperCase()} ${event.quantity}</p>
      <form class="review-form" data-event="${event.event_id}">
        <input name="name" value="${escapeHtml(event.product_name || "")}" placeholder="Product name" required>
        <input name="brand" value="${escapeHtml(result.brand || "")}" placeholder="Brand">
        <input name="quantity" value="${escapeHtml(result.quantity || "")}" placeholder="Package quantity">
        <input name="image_url" value="${escapeHtml(event.image_url || "")}" placeholder="Image URL">
        <textarea name="description" placeholder="Description">${escapeHtml(description)}</textarea>
        <select name="location_id">${locationOptions}</select>
        <select name="qu_id">${quOptions}</select>
        <button type="submit">Create in Grocy + apply</button>
        <button type="button" class="ghost refresh-event">Refresh lookup</button>
      </form>
    </div>
  </article>`;
}
function productCard(product) {
  return `<article class="card">${image(product.image_url)}
    <div class="card-body"><p class="status status-applied">${product.location || "Grocy product"}</p>
    <h3>${escapeHtml(product.name)}</h3><p class="stock">${product.stock_amount} ${escapeHtml(product.quantity_unit || "")}</p>
    <p class="meta">${escapeHtml(product.barcodes.join(", ") || "No barcode")}</p></div></article>`;
}
async function load() {
  try {
    const [events, products, loadedOptions] = await Promise.all([
      api("/scan-events?limit=100"), api("/dashboard/products"), api("/dashboard/options")
    ]);
    options = loadedOptions;
    const pending = events.filter(x => ["pending", "researching"].includes(x.status));
    $("#pending-count").textContent = pending.length;
    $("#product-count").textContent = products.length;
    $("#pending-grid").innerHTML = pending.length ? pending.map(pendingCard).join("") : `<div class="empty">No products need review.</div>`;
    $("#event-grid").innerHTML = events.length ? events.map(eventCard).join("") : `<div class="empty">No scanner events yet.</div>`;
    $("#product-grid").innerHTML = products.length ? products.map(productCard).join("") : `<div class="empty">No Grocy products yet.</div>`;
  } catch (error) { toast(error.message); }
}
$("#scan-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const data = Object.fromEntries(new FormData(event.target));
  data.quantity = Number(data.quantity); data.event_id = `${data.device_id}-${Date.now()}`;
  try { await api("/scan-events", { method: "POST", body: JSON.stringify(data) }); event.target.barcode.value = ""; await load(); }
  catch (error) { toast(error.message); }
});
document.addEventListener("submit", async (event) => {
  if (!event.target.matches(".review-form")) return;
  event.preventDefault(); const data = Object.fromEntries(new FormData(event.target));
  data.location_id = Number(data.location_id); data.qu_id = Number(data.qu_id);
  if (!data.image_url) delete data.image_url;
  try { await api(`/scan-events/${event.target.dataset.event}/confirm`, { method: "POST", body: JSON.stringify(data) }); await load(); }
  catch (error) { toast(error.message); }
});
document.addEventListener("click", async (event) => {
  if (event.target.id === "refresh") return load();
  if (!event.target.matches(".refresh-event")) return;
  const id = event.target.closest("form").dataset.event;
  try { await api(`/scan-events/${id}/refresh`, { method: "POST" }); await load(); } catch (error) { toast(error.message); }
});
load();
setInterval(load, 12000);
