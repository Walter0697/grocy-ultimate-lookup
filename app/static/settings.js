const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;" })[c]);
let pendingProducts = [];
let catalogSources = [];

async function api(path, init) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
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
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  setTimeout(() => node.classList.remove("show"), 3500);
}

function setButtonBusy(button, busy, label) {
  if (!button) return;
  if (busy) button.dataset.label = button.textContent;
  button.disabled = busy;
  button.classList.toggle("busy-button", busy);
  button.textContent = busy ? label : button.dataset.label || button.textContent;
}

function formData() {
  const form = $("#community-catalog-form");
  return {
    enabled: form.enabled.checked,
    repository_url: form.repository_url.value.trim() || null,
    github_pat: form.github_pat.value.trim() || null,
    branch: form.branch.value.trim() || "main",
    export_images: form.export_images.checked,
    auto_push: form.auto_push.checked,
    author_name: form.author_name.value.trim() || null,
    author_email: form.author_email.value.trim() || null
  };
}

function fillForm(settings) {
  const form = $("#community-catalog-form");
  form.enabled.checked = settings.enabled;
  form.repository_url.value = settings.repository_url || "";
  form.github_pat.value = "";
  form.github_pat_status.value = settings.github_pat_set ? "Saved" : "Not saved";
  form.branch.value = settings.branch || "main";
  form.export_images.checked = settings.export_images;
  form.auto_push.checked = settings.auto_push;
  form.author_name.value = settings.author_name || "";
  form.author_email.value = settings.author_email || "";
  updateCatalogConfigState();
}

function updateCatalogConfigState() {
  const form = $("#community-catalog-form");
  $("#community-catalog-config").classList.toggle("is-dimmed", !form.enabled.checked);
  const reviewActions = $("#pending-review-actions");
  reviewActions.classList.toggle("is-dimmed", form.auto_push.checked);
  reviewActions.querySelectorAll("button").forEach(button => {
    button.disabled = form.auto_push.checked;
  });
}

function renderStatus(status) {
  const node = $("#community-catalog-status");
  if (!node) return;
  node.innerHTML = `Repository: <b>${status.repository_url || "not configured"}</b><br>Branch: <b>${status.branch}</b><br>Internal checkout: <b>${status.path}</b><br>Exists: <b>${status.path_exists ? "yes" : "no"}</b><br>Git repository: <b>${status.is_git_repo ? "yes" : "no"}</b><br>Pending changes: <b>${status.pending_changes ? "yes" : "no"}</b>`;
}

function renderDiff(diff) {
  const node = $("#community-catalog-diff");
  const files = diff.files.length ? diff.files.map(file => `<li>${file}</li>`).join("") : "<li>No pending files</li>";
  if (!node) {
    toast(diff.pending_changes ? `Pending catalog changes: ${diff.files.length} file(s)` : "No pending catalog changes");
    return;
  }
  node.innerHTML = `Pending changes: <b>${diff.pending_changes ? "yes" : "no"}</b><ul>${files}</ul>`;
}

function selectedPendingBarcodes() {
  return Array.from(document.querySelectorAll('.pending-product-card input[type="checkbox"]:checked')).map(input => input.value);
}

function renderPendingProducts(payload) {
  pendingProducts = payload.products || [];
  const list = $("#pending-products-list");
  if (!payload.configured) {
    list.innerHTML = `<div class="pending-empty">Repository URL is not configured.</div>`;
  }
  else if (!pendingProducts.length) {
    list.innerHTML = `<div class="pending-empty">No manual catalog products are waiting for approval.</div>`;
  }
  else {
    list.innerHTML = pendingProducts.map(product => {
      const title = product.name || product.barcode;
      const meta = [product.brand, product.quantity, product.has_image ? "image.jpg" : ""].filter(Boolean).join(" · ");
      const files = product.files.map(file => `<li>${escapeHtml(file)}</li>`).join("");
      return `<label class="pending-product-card">
        <input type="checkbox" value="${escapeHtml(product.barcode)}" checked>
        <span>
          <strong>${escapeHtml(title)}</strong>
          <em>${escapeHtml(product.barcode)}</em>
          ${meta ? `<small>${escapeHtml(meta)}</small>` : ""}
          <ul>${files}</ul>
        </span>
      </label>`;
    }).join("");
  }
  updatePendingDialogActions();
}

function updatePendingDialogActions() {
  const selected = selectedPendingBarcodes().length;
  const hasProducts = pendingProducts.length > 0;
  $("#push-selected-products").disabled = selected === 0;
  $("#discard-selected-products").disabled = selected === 0;
  $("#push-all-products").disabled = !hasProducts;
  $("#discard-all-products").disabled = !hasProducts;
}

function renderCatalogSources() {
  const list = $("#catalog-source-list");
  if (!catalogSources.length) {
    list.innerHTML = `<div class="pending-empty">No community catalogs saved yet.</div>`;
    return;
  }
  list.innerHTML = catalogSources.map((source, index) => `<article class="catalog-source-card" data-index="${index}">
    <label class="inline-option"><input type="checkbox" class="source-enabled" ${source.enabled ? "checked" : ""}> Enabled</label>
    <label>Name<input class="source-name" value="${escapeHtml(source.name || "")}" placeholder="Optional label"></label>
    <label>Repository URL<input class="source-url" value="${escapeHtml(source.repository_url)}"></label>
    <div class="source-order-actions">
      <button type="button" class="secondary source-up" ${index === 0 ? "disabled" : ""}>Move up</button>
      <button type="button" class="secondary source-down" ${index === catalogSources.length - 1 ? "disabled" : ""}>Move down</button>
      <button type="button" class="secondary danger source-remove">Remove</button>
    </div>
  </article>`).join("");
}

function syncCatalogSourcesFromDom() {
  catalogSources = Array.from(document.querySelectorAll(".catalog-source-card")).map((card, index) => {
    const existing = catalogSources[Number(card.dataset.index)] || {};
    return {
      id: existing.id || null,
      name: card.querySelector(".source-name").value.trim() || null,
      repository_url: card.querySelector(".source-url").value.trim(),
      enabled: card.querySelector(".source-enabled").checked,
      priority: index
    };
  }).filter(source => source.repository_url);
}

async function loadCatalogSources() {
  const payload = await api("/settings/community-catalog-sources");
  catalogSources = payload.sources || [];
  renderCatalogSources();
}

function moveCatalogSource(index, direction) {
  syncCatalogSourcesFromDom();
  const next = index + direction;
  if (next < 0 || next >= catalogSources.length) return;
  [catalogSources[index], catalogSources[next]] = [catalogSources[next], catalogSources[index]];
  renderCatalogSources();
}

async function refreshPendingProducts() {
  const payload = await api("/settings/community-catalog/pending-products");
  renderPendingProducts(payload);
  return payload;
}

async function runPendingAction(button, path, barcodes, busyLabel, doneMessage) {
  if (!barcodes.length) return toast("Select at least one pending product");
  setButtonBusy(button, true, busyLabel);
  try {
    renderPendingProducts(await api(path, { method: "POST", body: JSON.stringify({ barcodes }) }));
    renderStatus(await api("/settings/community-catalog/test", { method: "POST" }));
    toast(doneMessage);
  }
  catch (error) { toast(error.message); }
  finally { setButtonBusy(button, false); }
}

async function load() {
  const settings = await api("/settings/community-catalog");
  fillForm(settings);
  renderStatus(await api("/settings/community-catalog/test", { method: "POST" }));
}

$("#community-catalog-form").addEventListener("submit", async event => {
  event.preventDefault();
  const button = event.target.querySelector('button[type="submit"]');
  setButtonBusy(button, true, "Saving...");
  try {
    fillForm(await api("/settings/community-catalog", { method: "PUT", body: JSON.stringify(formData()) }));
    renderStatus(await api("/settings/community-catalog/test", { method: "POST" }));
    toast("Settings saved");
  }
  catch (error) { toast(error.message); }
  finally { setButtonBusy(button, false); }
});

$("#community-catalog-form").enabled.addEventListener("change", updateCatalogConfigState);
$("#community-catalog-form").auto_push.addEventListener("change", updateCatalogConfigState);

$("#test-community-catalog").addEventListener("click", async event => {
  setButtonBusy(event.target, true, "Testing...");
  try {
    fillForm(await api("/settings/community-catalog", { method: "PUT", body: JSON.stringify(formData()) }));
    renderStatus(await api("/settings/community-catalog/sync", { method: "POST" }));
    toast("Catalog checkout is ready");
  }
  catch (error) { toast(error.message); }
  finally { setButtonBusy(event.target, false); }
});

$("#show-token-help").addEventListener("click", () => {
  $("#token-help-dialog").showModal();
});

$("#review-community-catalog").addEventListener("click", async event => {
  setButtonBusy(event.target, true, "Loading...");
  try {
    await refreshPendingProducts();
    $("#pending-products-dialog").showModal();
  }
  catch (error) { toast(error.message); }
  finally { setButtonBusy(event.target, false); }
});

$("#pending-products-list").addEventListener("change", event => {
  if (event.target.matches('input[type="checkbox"]')) updatePendingDialogActions();
});

$("#push-selected-products").addEventListener("click", event => {
  runPendingAction(event.target, "/settings/community-catalog/push-products", selectedPendingBarcodes(), "Pushing...", "Selected catalog products pushed");
});

$("#push-all-products").addEventListener("click", event => {
  runPendingAction(event.target, "/settings/community-catalog/push-products", pendingProducts.map(product => product.barcode), "Pushing...", "All pending catalog products pushed");
});

$("#discard-selected-products").addEventListener("click", event => {
  if (!confirm("Discard selected pending catalog products?")) return;
  runPendingAction(event.target, "/settings/community-catalog/discard-products", selectedPendingBarcodes(), "Discarding...", "Selected catalog products discarded");
});

$("#discard-all-products").addEventListener("click", event => {
  if (!confirm("Discard all pending catalog products?")) return;
  runPendingAction(event.target, "/settings/community-catalog/discard-products", pendingProducts.map(product => product.barcode), "Discarding...", "All pending catalog products discarded");
});

$("#open-catalog-source-list").addEventListener("click", async event => {
  setButtonBusy(event.target, true, "Loading...");
  try {
    await loadCatalogSources();
    $("#catalog-sources-dialog").showModal();
  }
  catch (error) { toast(error.message); }
  finally { setButtonBusy(event.target, false); }
});

$("#open-add-catalog-source").addEventListener("click", () => {
  syncCatalogSourcesFromDom();
  $("#new-source-name").value = "";
  $("#new-source-url").value = "";
  $("#add-catalog-source-dialog").showModal();
});

$("#add-catalog-source").addEventListener("click", () => {
  syncCatalogSourcesFromDom();
  const nameInput = $("#new-source-name");
  const urlInput = $("#new-source-url");
  const repositoryUrl = urlInput.value.trim();
  if (!repositoryUrl) return toast("Enter a catalog repository URL");
  if (catalogSources.some(source => source.repository_url.toLowerCase() === repositoryUrl.toLowerCase())) return toast("Catalog already exists");
  catalogSources.push({ id: null, name: nameInput.value.trim() || null, repository_url: repositoryUrl, enabled: true, priority: catalogSources.length });
  $("#add-catalog-source-dialog").close();
  renderCatalogSources();
});

$("#catalog-source-list").addEventListener("click", event => {
  const card = event.target.closest(".catalog-source-card");
  if (!card) return;
  const index = Number(card.dataset.index);
  if (event.target.matches(".source-up")) return moveCatalogSource(index, -1);
  if (event.target.matches(".source-down")) return moveCatalogSource(index, 1);
  if (event.target.matches(".source-remove")) {
    syncCatalogSourcesFromDom();
    catalogSources.splice(index, 1);
    renderCatalogSources();
  }
});

$("#save-catalog-sources").addEventListener("click", async event => {
  syncCatalogSourcesFromDom();
  setButtonBusy(event.target, true, "Saving...");
  try {
    const saved = await api("/settings/community-catalog-sources", { method: "PUT", body: JSON.stringify({ sources: catalogSources }) });
    catalogSources = saved.sources || [];
    renderCatalogSources();
    toast("Community catalog list saved");
  }
  catch (error) { toast(error.message); }
  finally { setButtonBusy(event.target, false); }
});

load().catch(error => toast(error.message));
