const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;" })[c]);
let events = [];
let products = [];
let options = { locations: [], quantity_units: [], scanner_devices: [] };
let activeFilter = "all";
let activePreview = null;
let activeProduct = null;
let activeProductEvent = null;
let dashboardSignature = "";

async function api(path, init, json = true) {
  const response = await fetch(path, { headers: json ? { "Content-Type": "application/json" } : {}, ...init });
  if (!response.ok) {
    const body = await response.text();
    let message = response.statusText;
    if (body) {
      try {
        message = JSON.parse(body).detail || message;
      }
      catch {
        message = body;
      }
    }
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}
function toast(message) {
  const node = $("#toast"); node.textContent = message; node.classList.add("show");
  setTimeout(() => node.classList.remove("show"), 3500);
}
function bindBackdropClose(dialog, onClose) {
  if (!dialog) return;
  dialog.addEventListener("click", event => {
    if (event.target === dialog) {
      dialog.close();
      onClose?.();
    }
  });
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
function imageContainerForForm(form) {
  if (form.id === "preview-confirm-form") return $(".preview-photo");
  if (form.id === "product-edit-form") return form.closest("dialog")?.querySelector(".drawer-image");
  if (form.classList.contains("review-form")) return $(".drawer-image");
  return null;
}
async function uploadProductImage(input) {
  const file = input.files?.[0];
  if (!file) return;
  const form = input.closest("form");
  const imageUrlInput = form.querySelector('input[name="image_url"]');
  const overwrite = form.querySelector('input[name="overwrite_image"]')?.checked ?? true;
  const body = new FormData();
  body.append("file", file);
  input.disabled = true;
  try {
    const uploaded = await api("/product-image-uploads", { method: "POST", body }, false);
    input.dataset.uploadedImageUrl = uploaded.image_url;
    input.dataset.uploadedPreviewUrl = uploaded.preview_url;
    if (overwrite) {
      imageUrlInput.value = uploaded.image_url;
      const container = imageContainerForForm(form);
      if (container) container.innerHTML = `<img src="${escapeHtml(uploaded.preview_url)}" alt="">`;
    }
    toast(overwrite ? "Image uploaded and selected." : "Image uploaded. Check Use uploaded image to apply it.");
  }
  catch (error) { toast(error.message); }
  finally { input.disabled = false; }
}
function isLoading(event) { return event.status === "processing"; }
function needsReview(event) { return ["pending", "researching", "failed"].includes(event.status); }
function image(event) {
  if (event.image_url) return `<img src="${escapeHtml(event.image_url)}" alt="">`;
  if (isLoading(event)) return `<div class="placeholder"><strong>...</strong><i class="scan-beam"></i></div>`;
  return `<div class="placeholder barcode-art"><i></i></div>`;
}
function operationBadge(event) {
  if (event.review_kind === "image_update") return "Photo review";
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
  if (event.review_kind === "image_update") return "PHOTO REQUEST";
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
    review_kind: event.review_kind,
    created_at: event.created_at
  };
}
function optionsSignature(nextOptions) {
  return {
    locations: nextOptions.locations.map(x => ({ id: x.id, name: x.name })),
    quantity_units: nextOptions.quantity_units.map(x => ({ id: x.id, name: x.name })),
    scanner_devices: (nextOptions.scanner_devices || []).map(x => ({
      device_id: x.device_id,
      online: x.online,
      last_seen: x.last_seen,
      mode: x.mode,
      quantity: x.quantity,
      location_id: x.location_id,
      location_name: x.location_name,
      version: x.version
    }))
  };
}
function dataSignature(nextEvents, nextProducts, nextOptions) {
  return JSON.stringify({
    events: nextEvents.map(eventSignature),
    products: nextProductsSignature(nextProducts),
    options: optionsSignature(nextOptions)
  });
}
function nextProductsSignature(nextProducts) {
  return nextProducts.map(product => ({
    product_id: product.product_id,
    name: product.name,
    description: product.description,
    barcode: product.barcode,
    brand: product.brand,
    quantity: product.quantity,
    image_url: product.image_url,
    stock_amount: product.stock_amount,
    quantity_unit: product.quantity_unit,
    location_name: product.location_name,
    editable: product.editable
  }));
}
function subtitle(event) {
  const change = event.stock_before == null ? "" : `Stock ${event.stock_before} → ${event.stock_after}`;
  const location = options.locations.find(x => x.id === event.location_id)?.name;
  return [change, location, event.device_id, event.created_at].filter(Boolean).map(escapeHtml).join(" · ");
}
function relativeTime(value) {
  if (!value) return "never";
  const seconds = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  return `${hours}h ago`;
}
function scannerStatusLine(device) {
  const location = device.location_name || options.locations.find(x => x.id === device.location_id)?.name || "Product default";
  const state = [device.mode?.toUpperCase(), device.quantity != null ? `x${device.quantity}` : "", location].filter(Boolean).join(" ");
  return `<article class="scanner-device ${device.online ? "online-device" : "offline-device"}">
    <span><i></i>${escapeHtml(device.device_id)}</span>
    <b>${device.online ? "Online" : "Offline"}</b>
    <em>${escapeHtml(state || "No state reported")}</em>
    <small>${escapeHtml(relativeTime(device.last_seen))}${device.version ? ` · ${escapeHtml(device.version)}` : ""}</small>
  </article>`;
}
function renderScannerStatus() {
  const devices = options.scanner_devices || [];
  const node = $("#scanner-status");
  if (!devices.length) {
    node.innerHTML = `<div class="scanner-empty">No scanner clients have checked in yet.</div>`;
    return;
  }
  node.innerHTML = devices.map(scannerStatusLine).join("");
}
function productById(productId) {
  return products.find(x => String(x.product_id) === String(productId)) || null;
}
function activeScanContext(event) {
  if (!event) return "";
  const location = options.locations.find(x => x.id === event.location_id)?.name || "Product default";
  return `<fieldset><legend>Scan context</legend>
    <div class="form-pair readonly-pair">
      <label>Mode<input value="${escapeHtml(event.mode?.toUpperCase() || "")}" readonly></label>
      <label>Quantity<input value="${escapeHtml(event.quantity ?? "")}" readonly></label>
    </div>
    <div class="form-pair readonly-pair">
      <label>Location<input value="${escapeHtml(location)}" readonly></label>
      <label>Barcode<input value="${escapeHtml(event.barcode || "")}" readonly></label>
    </div>
  </fieldset>`;
}
function productEditDialog(product, event) {
  const locationOptions = options.locations.map(x => `<option value="${x.id}" ${x.id === product.location_id ? "selected" : ""}>${escapeHtml(x.name)}</option>`).join("");
  const stockUnitOptions = options.quantity_units.map(x => `<option value="${x.id}" ${x.id === product.qu_id_stock ? "selected" : ""}>${escapeHtml(x.name)}</option>`).join("");
  const purchaseUnitOptions = options.quantity_units.map(x => `<option value="${x.id}" ${x.id === product.qu_id_purchase ? "selected" : ""}>${escapeHtml(x.name)}</option>`).join("");
  return `<div class="drawer-image">${previewImage(product)}</div>
    <p class="drawer-kicker">GROCY PRODUCT</p>
    <h2>${escapeHtml(product.name || "Unnamed product")}</h2>
    <form id="product-edit-form" data-product-id="${escapeHtml(product.product_id)}" class="review-form">
      ${activeScanContext(event)}
      <label>Product name<input name="name" value="${escapeHtml(product.name || "")}" required></label>
      <label>Brand<input name="brand" value="${escapeHtml(product.brand || "")}"></label>
      <label>Package quantity<input name="quantity" value="${escapeHtml(product.quantity || "")}"></label>
      <label>Image URL<input name="image_url" value="${escapeHtml(product.image_url || "")}"></label>
      <div class="image-upload-row"><label>Upload image<input type="file" name="image_upload" accept="image/*"></label><label class="inline-option"><input type="checkbox" name="overwrite_image" checked> Use uploaded image</label></div>
      <label>Description<textarea name="description">${escapeHtml(product.description || "")}</textarea></label>
      <div class="form-pair"><label>Default location<select name="location_id">${locationOptions}</select></label><span></span></div>
      ${conversionRow(stockUnitOptions, purchaseUnitOptions, product.qu_factor_purchase_to_stock || 1)}
      <div class="review-dialog-actions"><button type="submit">Save product</button><button type="button" class="secondary request-image-review">Request external image</button></div>
    </form>`;
}
function openProductEditDialog(productId, eventId = null) {
  const product = productById(productId);
  if (!product) return toast("Product details are still loading. Try again in a moment.");
  activeProduct = product;
  activeProductEvent = eventId ? events.find(x => x.event_id === eventId) || null : null;
  $("#product-edit-content").innerHTML = productEditDialog(product, activeProductEvent);
  $("#product-edit-dialog").showModal();
}
function card(event, index) {
  const review = needsReview(event);
  const result = event.lookup_payload?.result;
  const cardClass = review || isLoading(event) ? "review" : "applied";
  return `<article class="polaroid ${cardClass} ${event.status}" data-event="${escapeHtml(event.event_id)}" data-product-id="${escapeHtml(event.product_id || "")}" style="--delay:${Math.min(index, 10) * 35}ms">
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
  renderScannerStatus();
  $("#event-grid").innerHTML = visible.length ? visible.map(card).join("") : `<div class="empty">No scans in this view yet.</div>`;
}
function imageReviewForm(event) {
  return `<div class="drawer-image">${image(event)}<span class="drawer-badge ${operationClass(event)}">${escapeHtml(operationBadge(event))}</span></div>
    <p class="drawer-kicker">IMAGE REVIEW · ${escapeHtml(event.barcode)}</p><h2>${escapeHtml(event.product_name || "Product review")}</h2>
    <p class="drawer-operation">Waiting for a photo upload from an external client.</p>
    <div class="review-dialog-actions">${event.product_id ? `<button type="button" class="secondary open-product-editor" data-product-id="${escapeHtml(event.product_id)}">Open product editor</button>` : ""}<button type="button" class="secondary danger dialog-delete-action delete-event" data-event="${escapeHtml(event.event_id)}">Dismiss from review</button></div>
    <form method="dialog" class="review-form"><label>Current image URL<input value="${escapeHtml(event.image_url || "")}" readonly></label><button type="submit">Close</button></form>`;
}
function reviewForm(event) {
  if (event.review_kind === "image_update") return imageReviewForm(event);
  const result = event.lookup_payload?.result || {};
  const alternate = result.alternate_names ? Object.entries(result.alternate_names).map(([lang, name]) => `Alternate (${lang.toUpperCase()}): ${name}`).join("\n") : "";
  const description = [alternate, result.source ? `Lookup source: ${result.source}` : "", event.error || ""].filter(Boolean).join("\n");
  const locations = options.locations.map(x => `<option value="${x.id}" ${x.id === event.location_id ? "selected" : ""}>${escapeHtml(x.name)}</option>`).join("");
  const units = options.quantity_units.map(x => `<option value="${x.id}">${escapeHtml(x.name)}</option>`).join("");
  const topActions = event.status === "failed"
    ? `<div class="review-dialog-actions"><button type="button" class="secondary danger dialog-delete-action delete-event" data-event="${escapeHtml(event.event_id)}">Dismiss from review</button></div>`
    : "";
  return `<div class="drawer-image">${image(event)}<span class="drawer-badge ${operationClass(event)}">${escapeHtml(operationBadge(event))}</span></div>
    <p class="drawer-kicker">${escapeHtml(event.status)} · ${escapeHtml(event.barcode)}</p><h2>${escapeHtml(event.product_name || "Unknown product")}</h2>
    <p class="drawer-operation">Pending operation: <b>${event.mode.toUpperCase()} ${event.quantity}</b></p>
    ${topActions}
    <form class="review-form" data-event="${escapeHtml(event.event_id)}"><label>Product name<input name="name" value="${escapeHtml(event.product_name || "")}" required></label>
      <label>Brand<input name="brand" value="${escapeHtml(result.brand || "")}"></label><label>Package quantity<input name="quantity" value="${escapeHtml(result.quantity || "")}"></label>
      <label>Image URL<input name="image_url" value="${escapeHtml(event.image_url || "")}"></label><div class="image-upload-row"><label>Upload image<input type="file" name="image_upload" accept="image/*"></label><label class="inline-option"><input type="checkbox" name="overwrite_image" checked> Use uploaded image</label></div><label>Description<textarea name="description">${escapeHtml(description)}</textarea></label>
      <div class="form-pair"><label>Location<select name="location_id">${locations}</select></label><span></span></div>${conversionRow(units)}
      <button type="submit">Create in Grocy + apply scan</button>${event.status !== "failed" ? `<button type="button" class="secondary refresh-event">Refresh lookup</button>` : ""}<button type="button" class="secondary danger delete-event">Dismiss from review</button></form>`;
}
function processingDialog(event) {
  const message = event.error || "This scan is still being processed.";
  return `<div class="drawer-image">${image(event)}<span class="drawer-badge ${operationClass(event)}">${escapeHtml(operationBadge(event))}</span></div>
    <p class="drawer-kicker">${escapeHtml(event.status)} · ${escapeHtml(event.barcode)}</p><h2>${escapeHtml(event.product_name || "Processing scan")}</h2>
    <p class="drawer-operation">Pending operation: <b>${event.mode.toUpperCase()} ${event.quantity}</b></p>
    <div class="review-dialog-actions"><button type="button" class="secondary danger dialog-delete-action delete-event" data-event="${escapeHtml(event.event_id)}">Dismiss from review</button></div>
    <form method="dialog" class="review-form">
      <label>Barcode<input value="${escapeHtml(event.barcode)}" readonly></label>
      <label>Mode<input value="${escapeHtml(event.mode)}" readonly></label>
      <label>Quantity<input value="${escapeHtml(event.quantity ?? "")}" readonly></label>
      <label>Status<input value="${escapeHtml(event.status)}" readonly></label>
      <label>Message<textarea readonly>${escapeHtml(message)}</textarea></label>
      <button type="submit">Close</button>
    </form>`;
}
function openReviewDialog(eventId) {
  const event = events.find(x => x.event_id === eventId);
  if (!event || !needsReview(event)) return;
  $("#review-dialog-content").innerHTML = isLoading(event) ? processingDialog(event) : reviewForm(event);
  $("#review-dialog").showModal();
}
function closeReviewDialog() { $("#review-dialog").close(); $("#quick-scan input").focus(); }
function resolveEventId(node) {
  return node?.dataset.event || node?.closest("[data-event]")?.dataset.event || "";
}
function previewImage(product) {
  return product?.image_url ? `<img src="${escapeHtml(product.image_url)}" alt="">` : `<div class="placeholder barcode-art"><i></i></div>`;
}
function previewDescription(preview, product) {
  const alternate = product?.alternate_names ? Object.entries(product.alternate_names).map(([lang, name]) => `Alternate (${lang.toUpperCase()}): ${name}`).join("\n") : "";
  const source = product?.source ? `Lookup source: ${product.source}` : "";
  const confidence = product?.confidence != null ? `Lookup confidence: ${product.confidence}` : "";
  const url = product?.raw_url ? `Source URL: ${product.raw_url}` : "";
  return [product?.description || "", alternate, source, confidence, url].filter(Boolean).join("\n");
}
function reviewIsManualContribution(event) {
  return !event.lookup_payload?.result;
}
function previewIsManualContribution(preview) {
  return preview?.resolution === "unknown";
}
function previewNeedsProductConfirmation(preview) {
  return preview?.resolution !== "grocy";
}
function conversionRow(stockUnitOptions, purchaseUnitOptions = stockUnitOptions, factor = 1) {
  return `<div class="conversion-row"><label>Stock unit<select name="qu_id_stock" required>${stockUnitOptions}</select></label><label>Per scan<input name="qu_factor_purchase_to_stock" type="number" min="0.01" step="0.01" value="${escapeHtml(factor)}" required></label><label>Scanned package<select name="qu_id_purchase" required>${purchaseUnitOptions}</select></label></div>`;
}
function previewDialog(preview) {
  const product = preview.product || {};
  const source = preview.resolution === "grocy" ? "Existing Grocy product" : preview.resolution === "lookup" ? `Suggested by ${product.source || "Ultimate Lookup"}` : "Unknown product";
  const locationOptions = options.locations.map((x, index) => `<option value="${x.id}" ${index === 0 ? "selected" : ""}>${escapeHtml(x.name)}</option>`).join("");
  const unitOptions = options.quantity_units.map((x, index) => `<option value="${x.id}" ${index === 0 ? "selected" : ""}>${escapeHtml(x.name)}</option>`).join("");
  const productFields = previewNeedsProductConfirmation(preview)
    ? `<fieldset class="product-edit-fields"><legend>Product</legend><label>Product name<input name="name" value="${escapeHtml(product.name || "")}" required></label>
        <label>Brand<input name="brand" value="${escapeHtml(product.brand || "")}"></label><label>Package quantity<input name="package_quantity" value="${escapeHtml(product.quantity || product.size || "")}"></label>
        <label>Image URL<input name="image_url" value="${escapeHtml(product.image_url || "")}"></label><div class="image-upload-row"><label>Upload image<input type="file" name="image_upload" accept="image/*"></label><label class="inline-option"><input type="checkbox" name="overwrite_image" checked> Use uploaded image</label></div><label>Description<textarea name="description">${escapeHtml(previewDescription(preview, product))}</textarea></label>
      <div class="form-pair"><label>Default location<select name="product_location_id" required>${locationOptions}</select></label><span></span></div>${conversionRow(unitOptions)}</fieldset>`
    : `<p class="current-stock">Existing Grocy units and conversion will be used for this scan.</p>`;
  return `<div class="preview-photo">${previewImage(product)}</div><p class="drawer-kicker">${escapeHtml(source)}</p><h2>${escapeHtml(product.name || "Unknown product")}</h2>
    <p class="preview-barcode">${escapeHtml(preview.barcode)}</p>${product.stock_amount != null ? `<p class="current-stock">Current stock: <b>${product.stock_amount}</b> ${escapeHtml(product.quantity_unit || "")}</p>` : ""}
    ${StockConfirm.formMarkup({
      formId: "preview-confirm-form",
      locations: options.locations,
      quantity: "1",
      extraFieldsHtml: productFields,
    })}`;
}
function updateConfirmLabel() {
  StockConfirm.updateConfirmLabel($("#preview-confirm-form"));
}
function openScanDialog(preview) {
  activePreview = preview; $("#scan-preview-content").innerHTML = previewDialog(preview); $("#scan-dialog").showModal(); updateConfirmLabel();
}
bindBackdropClose($("#scan-dialog"), () => {
  activePreview = null;
  $("#quick-scan input").focus();
});
bindBackdropClose($("#product-edit-dialog"), () => {
  activeProduct = null;
  activeProductEvent = null;
  $("#quick-scan input").focus();
});
bindBackdropClose($("#review-dialog"), () => {
  $("#quick-scan input").focus();
});
async function load() {
  try {
    const [nextEvents, nextOptions] = await Promise.all([api("/scan-events?limit=200"), api("/dashboard/options")]);
    let nextProducts = products;
    try {
      nextProducts = await api("/dashboard/products");
    }
    catch (error) {
      console.warn("Dashboard products refresh failed:", error);
    }
    const nextSignature = dataSignature(nextEvents, nextProducts, nextOptions);
    events = nextEvents;
    products = nextProducts;
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
  const polaroid = event.target.closest(".polaroid.review"); if (polaroid) return openReviewDialog(polaroid.dataset.event);
  const appliedPolaroid = event.target.closest(".polaroid.applied"); if (appliedPolaroid?.dataset.productId) return openProductEditDialog(appliedPolaroid.dataset.productId, appliedPolaroid.dataset.event);
  const choice = event.target.closest(".choice");
  if (choice) {
    const form = StockConfirm.findForm(choice);
    if (form && StockConfirm.handleChoiceClick(choice)) {
      StockConfirm.updateConfirmLabel(form);
      return;
    }
  }
  if (event.target.matches("#close-scan-dialog")) { $("#scan-dialog").close(); return $("#quick-scan input").focus(); }
  if (event.target.matches("#close-product-edit-dialog")) { $("#product-edit-dialog").close(); activeProduct = null; activeProductEvent = null; return $("#quick-scan input").focus(); }
  if (event.target.matches("#close-review-dialog")) return closeReviewDialog();
  if (event.target.matches(".open-product-editor")) {
    const productId = event.target.dataset.productId;
    $("#review-dialog").close();
    return openProductEditDialog(productId, resolveEventId(event.target));
  }
  if (event.target.matches(".request-image-review")) {
    if (!activeProduct?.product_id) return toast("No active product selected.");
    try {
      await api(`/dashboard/products/${activeProduct.product_id}/request-image-review`, { method: "POST" });
      $("#product-edit-dialog").close();
      activeProduct = null;
      activeProductEvent = null;
      await load();
      toast("Added to Needs review for external image upload.");
      return $("#quick-scan input").focus();
    } catch (error) { toast(error.message); }
  }
  if (event.target.matches(".refresh-event")) {
    const eventId = resolveEventId(event.target.closest("form"));
    try { await api(`/scan-events/${eventId}/refresh`, { method: "POST" }); closeReviewDialog(); await load(); } catch (error) { toast(error.message); }
  }
  if (event.target.matches(".delete-event")) {
    if (!confirm("Remove this scan from Needs review?")) return;
    const eventId = resolveEventId(event.target);
    try { await api(`/scan-events/${eventId}`, { method: "DELETE" }); closeReviewDialog(); await load(); } catch (error) { toast(error.message); }
  }
});
document.addEventListener("input", event => {
  const form = StockConfirm.findForm(event.target);
  if (form && StockConfirm.handleQuantityInput(event.target)) {
    StockConfirm.updateConfirmLabel(form);
    return;
  }
});
document.addEventListener("change", event => {
  if (event.target.matches('input[name="image_upload"]')) return uploadProductImage(event.target);
  if (event.target.matches('input[name="overwrite_image"]') && event.target.checked) {
    const form = event.target.closest("form");
    const upload = form.querySelector('input[name="image_upload"]');
    if (!upload?.dataset.uploadedImageUrl) return;
    form.querySelector('input[name="image_url"]').value = upload.dataset.uploadedImageUrl;
    const container = imageContainerForForm(form);
    if (container) container.innerHTML = `<img src="${escapeHtml(upload.dataset.uploadedPreviewUrl)}" alt="">`;
  }
});
document.addEventListener("submit", async event => {
  if (event.target.matches("#preview-confirm-form")) {
    event.preventDefault();
    const { mode, quantity, location_id } = StockConfirm.readValues(event.target);
    if (mode === "set" && !confirm(`Set stock to ${quantity}?`)) return;
    const data = { event_id: `dashboard-manual-${Date.now()}`, device_id: "dashboard-manual", barcode: activePreview.barcode, mode, quantity };
    if (location_id) data.location_id = location_id;
    const button = event.target.querySelector(".confirm-scan"); setButtonBusy(button, true, "Updating Grocy...");
    try {
      if (previewNeedsProductConfirmation(activePreview)) {
        const formData = new FormData(event.target);
        const product = {
          name: formData.get("name").trim(),
          brand: formData.get("brand").trim() || null,
          quantity: formData.get("package_quantity").trim() || null,
          image_url: formData.get("image_url").trim() || null,
          description: formData.get("description").trim() || null,
          lookup_source: activePreview.product?.source || null,
          catalog_contribution: previewIsManualContribution(activePreview),
          location_id: Number(formData.get("product_location_id")),
          qu_id_stock: Number(formData.get("qu_id_stock")),
          qu_id_purchase: Number(formData.get("qu_id_purchase")),
          qu_factor_purchase_to_stock: Number(formData.get("qu_factor_purchase_to_stock") || "1"),
        };
        if (!product.brand) delete product.brand;
        if (!product.quantity) delete product.quantity;
        if (!product.image_url) delete product.image_url;
        if (!product.description) delete product.description;
        if (!product.lookup_source) delete product.lookup_source;
        data.product = product;
        await api("/dashboard/scan-confirm", { method: "POST", body: JSON.stringify(data) });
      } else {
        await api("/scan-events", { method: "POST", body: JSON.stringify(data) });
      }
      $("#scan-dialog").close(); activePreview = null; await load(); $("#quick-scan input").focus();
    } catch (error) { toast(error.message); }
    finally { setButtonBusy(button, false); }
    return;
  }
  if (event.target.matches("#product-edit-form")) {
    event.preventDefault();
    if (!activeProduct?.product_id) return toast("No active product selected.");
    const formData = new FormData(event.target);
    const data = {
      name: formData.get("name").trim(),
      description: formData.get("description").trim() || null,
      brand: formData.get("brand").trim() || null,
      quantity: formData.get("quantity").trim() || null,
      image_url: formData.get("image_url").trim() || null,
      location_id: Number(formData.get("location_id")),
      qu_id_stock: Number(formData.get("qu_id_stock")),
      qu_id_purchase: Number(formData.get("qu_id_purchase")),
      qu_factor_purchase_to_stock: Number(formData.get("qu_factor_purchase_to_stock") || "1"),
    };
    const button = event.target.querySelector('button[type="submit"]'); setButtonBusy(button, true, "Saving...");
    try {
      const result = await api(`/dashboard/products/${activeProduct.product_id}`, { method: "PUT", body: JSON.stringify(data) });
      $("#product-edit-dialog").close();
      activeProduct = null;
      activeProductEvent = null;
      await load();
      toast(result.updated_event_count > 0 ? `Product updated. Updated ${result.updated_event_count} dashboard record(s).` : "Product updated.");
      $("#quick-scan input").focus();
    } catch (error) { toast(error.message); }
    finally { setButtonBusy(button, false); }
    return;
  }
  if (!event.target.matches(".review-form")) return;
  event.preventDefault(); const data = Object.fromEntries(new FormData(event.target)); data.location_id = Number(data.location_id); data.qu_id_stock = Number(data.qu_id_stock); data.qu_id_purchase = Number(data.qu_id_purchase); data.qu_factor_purchase_to_stock = Number(data.qu_factor_purchase_to_stock || "1"); data.catalog_contribution = reviewIsManualContribution(events.find(x => x.event_id === event.target.dataset.event)); if (!data.image_url) delete data.image_url;
  const button = event.target.querySelector('button[type="submit"]'); setButtonBusy(button, true, "Adding to Grocy...");
  try { await api(`/scan-events/${event.target.dataset.event}/confirm`, { method: "POST", body: JSON.stringify(data) }); closeReviewDialog(); await load(); } catch (error) { toast(error.message); }
  finally { setButtonBusy(button, false); }
});
load(); setInterval(load, 12000);
