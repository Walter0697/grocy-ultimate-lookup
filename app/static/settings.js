const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;" })[c]);
let pendingProducts = [];
let catalogSources = [];
let searchProviders = [];
let catalogSourceSortable = null;
let searchProviderSortable = null;
let unavailableSearchProviders = {};

const SEARCH_PROVIDER_LABELS = {
  grocy_current: "Grocy current data",
  ultimate_lookup_cache: "Ultimate Lookup cache",
  community_catalog: "Community catalogs",
  open_food_facts: "Open Food Facts",
  open_products_facts: "Open Products Facts",
  open_beauty_facts: "Open Beauty Facts",
  open_pet_food_facts: "Open Pet Food Facts",
  upcitemdb: "UPCItemDB",
  web_search: "Web search structured extraction",
  agent_completed: "Completed Codex result cache",
  llm_fallback: "LLM page extraction fallback",
  codex_agent: "Codex based final fallback"
};

const SEARCH_PROVIDER_RECOMMENDATIONS = {
  grocy_current: "Recommend first",
  ultimate_lookup_cache: "Recommend second",
  community_catalog: "Recommend third",
  llm_fallback: "Recommend last",
  codex_agent: "Recommend last"
};

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
    github_pat: null,
    branch: form.branch.value.trim() || "main",
    export_images: form.export_images.checked,
    auto_push: form.auto_push.checked,
    author_name: form.author_name.value.trim() || null,
    author_email: form.author_email.value.trim() || null
  };
}

function githubAccessFormData() {
  return {
    ...formData(),
    github_pat: $("#github-access-form").github_pat.value.trim() || null
  };
}

function lookupFormData() {
  const form = $("#lookup-form");
  syncSearchProvidersFromDom();
  return {
    enable_open_facts: searchProviders.some(provider => provider.id.startsWith("open_") && provider.enabled),
    enable_upcitemdb: searchProviders.some(provider => provider.id === "upcitemdb" && provider.enabled),
    enable_web_search: searchProviders.some(provider => provider.id === "web_search" && provider.enabled),
    search_providers: searchProviders,
    web_search_provider: form.web_search_provider.value,
    searxng_base_url: form.searxng_base_url.value.trim() || null,
    enable_llm_fallback: searchProviders.some(provider => provider.id === "llm_fallback" && provider.enabled),
    llm_base_url: form.llm_base_url.value.trim() || "https://api.openai.com/v1",
    llm_api_key: form.llm_api_key.value.trim() || null,
    llm_model: form.llm_model.value.trim() || null
  };
}

function fillForm(settings) {
  const form = $("#community-catalog-form");
  form.enabled.checked = settings.enabled;
  form.repository_url.value = settings.repository_url || "";
  form.branch.value = settings.branch || "main";
  form.export_images.checked = settings.export_images;
  form.auto_push.checked = settings.auto_push;
  form.author_name.value = settings.author_name || "";
  form.author_email.value = settings.author_email || "";
  updateCatalogConfigState();
}

function fillGithubAccessForm(settings) {
  const form = $("#github-access-form");
  form.github_pat.value = "";
  form.github_pat_status.value = settings.github_pat_set ? "Saved" : "Not saved";
}

function fillLookupForm(settings) {
  const form = $("#lookup-form");
  searchProviders = settings.search_providers || [];
  form.web_search_provider.value = settings.web_search_provider || "duckduckgo";
  form.searxng_base_url.value = settings.searxng_base_url || "";
  form.llm_base_url.value = settings.llm_base_url || "https://api.openai.com/v1";
  form.llm_model.value = settings.llm_model || "";
  form.llm_api_key.value = "";
  form.llm_api_key_status.value = settings.llm_api_key_set ? "Saved" : "Not saved";
  unavailableSearchProviders.llm_fallback = settings.llm_api_key_set && settings.llm_model ? null : "Set an LLM API key and model first";
  renderSearchProviders();
  updateLookupConfigState();
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

function updateLookupConfigState() {
  const form = $("#lookup-form");
  const webEnabled = searchProviders.some(provider => provider.id === "web_search" && provider.enabled && !unavailableSearchProviders[provider.id]);
  $("#web-search-config").classList.toggle("is-dimmed", !webEnabled);
  $("#web-search-config").querySelectorAll("input, select").forEach(input => {
    input.disabled = !webEnabled;
  });
  $("#llm-config").classList.toggle("is-dimmed", !webEnabled);
  $("#llm-config").querySelectorAll("input").forEach(input => {
    input.disabled = !webEnabled;
  });
}

function renderSearchProviders() {
  const list = $("#search-provider-list");
  if (!searchProviders.length) {
    list.innerHTML = `<div class="pending-empty">No lookup providers configured.</div>`;
    updateLookupConfigState();
    return;
  }
  list.innerHTML = searchProviders.map((provider, index) => {
    const recommendation = SEARCH_PROVIDER_RECOMMENDATIONS[provider.id];
    const label = SEARCH_PROVIDER_LABELS[provider.id] || provider.id;
    const unavailableReason = unavailableSearchProviders[provider.id];
    const disabled = Boolean(unavailableReason);
    const enabled = provider.enabled && !disabled;
    return `<article
      class="search-provider-card ${disabled ? "is-unavailable" : ""}"
      data-index="${index}"
      data-provider-id="${escapeHtml(provider.id)}"
      title="${disabled ? escapeHtml(unavailableReason) : ""}"
    >
    <span class="search-provider-grip" aria-hidden="true"></span>
    <span class="search-provider-label">
      <strong>${escapeHtml(label)}</strong>
      ${recommendation ? `<small>${escapeHtml(recommendation)}</small>` : ""}
      ${disabled ? `<small>${escapeHtml(unavailableReason)}</small>` : ""}
    </span>
    <button
      type="button"
      class="search-provider-toggle ${enabled ? "is-enabled" : ""}"
      aria-pressed="${enabled ? "true" : "false"}"
      aria-label="${enabled ? "Disable" : "Enable"} ${escapeHtml(label)}"
      title="${disabled ? unavailableReason : enabled ? "Enabled" : "Disabled"}"
      ${disabled ? "disabled" : ""}
    ></button>
  </article>`;
  }).join("");
  initSearchProviderSortable();
  updateLookupConfigState();
}

function syncSearchProvidersFromDom() {
  searchProviders = Array.from(document.querySelectorAll(".search-provider-card")).map((card, index) => {
    return {
      id: card.dataset.providerId,
      enabled: !card.classList.contains("is-unavailable")
        && card.querySelector(".search-provider-toggle").getAttribute("aria-pressed") === "true",
      priority: index
    };
  }).filter(provider => provider.id);
}

function updateSearchProviderIndexes() {
  document.querySelectorAll(".search-provider-card").forEach((card, index) => {
    card.dataset.index = String(index);
  });
}

function initSearchProviderSortable() {
  const list = $("#search-provider-list");
  if (!list || typeof Sortable === "undefined") return;
  if (searchProviderSortable) searchProviderSortable.destroy();
  searchProviderSortable = Sortable.create(list, {
    animation: 150,
    handle: ".search-provider-grip",
    draggable: ".search-provider-card:not(.is-unavailable)",
    filter: ".is-unavailable",
    ghostClass: "is-dragging",
    chosenClass: "is-chosen",
    dragClass: "is-drag-active",
    onMove: event => {
      return !event.dragged.classList.contains("is-unavailable");
    },
    onEnd: () => {
      syncSearchProvidersFromDom();
      updateSearchProviderIndexes();
      updateLookupConfigState();
    }
  });
}

function setSearchProviderEnabled(index, enabled) {
  syncSearchProvidersFromDom();
  if (!searchProviders[index]) return;
  searchProviders[index].enabled = enabled;
  renderSearchProviders();
}

function renderAgentSearchAvailability(status) {
  unavailableSearchProviders.codex_agent = status.available ? null : "Set up Codex auth/runtime first";
  renderSearchProviders();
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
  list.innerHTML = catalogSources.map((source, index) => {
    const title = source.name || source.repository_url;
    const summary = [source.owner, source.product_count != null ? `${source.product_count} products` : null].filter(Boolean).join(" · ");
    const warnings = (source.warnings || []).map(warning => `<small class="catalog-source-warning">${escapeHtml(warning)}</small>`).join("");
    const statusClass = source.validation_status && source.validation_status !== "valid" && source.validation_status !== "valid_with_warnings"
      ? "is-invalid"
      : source.validation_status === "valid_with_warnings" ? "is-warning" : "";
    const checks = [source.last_successful_check ? `Last good: ${source.last_successful_check}` : null, source.last_failed_check ? `Last failed: ${source.last_failed_check}` : null].filter(Boolean).join(" · ");
    return `<article
      class="catalog-source-card ${statusClass}"
      data-index="${index}"
      data-source-id="${escapeHtml(source.id || "")}"
      data-source-name="${escapeHtml(source.name || "")}"
      data-source-url="${escapeHtml(source.repository_url)}"
    >
    <span class="catalog-source-grip search-provider-grip" aria-hidden="true"></span>
    <span class="catalog-source-label search-provider-label">
      <strong>${escapeHtml(title)}</strong>
      ${source.name ? `<small>${escapeHtml(source.repository_url)}</small>` : ""}
      ${source.description ? `<small>${escapeHtml(source.description)}</small>` : ""}
      ${summary ? `<small>${escapeHtml(summary)}</small>` : ""}
      ${source.validation_message ? `<small class="catalog-source-status">${escapeHtml(source.validation_message)}</small>` : ""}
      ${source.last_checked ? `<small>Last checked: ${escapeHtml(source.last_checked)}</small>` : ""}
      ${checks ? `<small>${escapeHtml(checks)}</small>` : ""}
      ${source.last_error ? `<small class="catalog-source-warning">${escapeHtml(source.last_error)}</small>` : ""}
      ${warnings}
    </span>
    <button type="button" class="secondary source-refresh" title="Recheck source">↻</button>
    <button
      type="button"
      class="source-toggle search-provider-toggle ${source.enabled ? "is-enabled" : ""}"
      aria-pressed="${source.enabled ? "true" : "false"}"
      aria-label="${source.enabled ? "Disable" : "Enable"} ${escapeHtml(title)}"
      title="${source.enabled ? "Enabled" : "Disabled"}"
    ></button>
    <button type="button" class="source-remove" aria-label="Remove ${escapeHtml(title)}" title="Remove">X</button>
  </article>`;
  }).join("");
  initCatalogSourceSortable();
}

function syncCatalogSourcesFromDom() {
  catalogSources = Array.from(document.querySelectorAll(".catalog-source-card")).map((card, index) => {
    return {
      id: card.dataset.sourceId || null,
      name: card.dataset.sourceName || null,
      repository_url: card.dataset.sourceUrl || "",
      enabled: card.querySelector(".source-toggle").getAttribute("aria-pressed") === "true",
      priority: index
    };
  }).filter(source => source.repository_url);
}

function updateCatalogSourceIndexes() {
  document.querySelectorAll(".catalog-source-card").forEach((card, index) => {
    card.dataset.index = String(index);
  });
}

function initCatalogSourceSortable() {
  const list = $("#catalog-source-list");
  if (!list || typeof Sortable === "undefined") return;
  if (catalogSourceSortable) catalogSourceSortable.destroy();
  catalogSourceSortable = Sortable.create(list, {
    animation: 150,
    handle: ".catalog-source-grip",
    draggable: ".catalog-source-card",
    ghostClass: "is-dragging",
    chosenClass: "is-chosen",
    dragClass: "is-drag-active",
    onEnd: () => {
      syncCatalogSourcesFromDom();
      updateCatalogSourceIndexes();
    }
  });
}

async function loadCatalogSources() {
  const payload = await api("/settings/community-catalog-sources");
  catalogSources = payload.sources || [];
  renderCatalogSources();
}

async function refreshCatalogSource(button, index) {
  syncCatalogSourcesFromDom();
  const source = catalogSources[index];
  if (!source?.id) return toast("Save the source list before rechecking.");
  setButtonBusy(button, true, "Checking...");
  try {
    const refreshed = await api(`/settings/community-catalog-sources/${encodeURIComponent(source.id)}/refresh`, { method: "POST" });
    catalogSources[index] = refreshed;
    renderCatalogSources();
    toast("Catalog source refreshed");
  }
  catch (error) { toast(error.message); }
  finally { setButtonBusy(button, false); }
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
  const lookupSettings = await api("/settings/lookup");
  const agentSearchStatus = await api("/settings/agent-search");
  fillForm(settings);
  fillGithubAccessForm(settings);
  fillLookupForm(lookupSettings);
  renderAgentSearchAvailability(agentSearchStatus);
  await loadCatalogSources();
  renderStatus(await api("/settings/community-catalog/test", { method: "POST" }));
}

$("#community-catalog-form").addEventListener("submit", async event => {
  event.preventDefault();
  const button = event.target.querySelector('button[type="submit"]');
  setButtonBusy(button, true, "Saving...");
  try {
    const saved = await api("/settings/community-catalog", { method: "PUT", body: JSON.stringify(formData()) });
    fillForm(saved);
    fillGithubAccessForm(saved);
    renderStatus(await api("/settings/community-catalog/test", { method: "POST" }));
    toast("Settings saved");
  }
  catch (error) { toast(error.message); }
  finally { setButtonBusy(button, false); }
});

$("#community-catalog-form").enabled.addEventListener("change", updateCatalogConfigState);
$("#community-catalog-form").auto_push.addEventListener("change", updateCatalogConfigState);
$("#search-provider-list").addEventListener("click", event => {
  if (event.target.matches(".search-provider-toggle")) {
    const card = event.target.closest(".search-provider-card");
    const index = Number(card.dataset.index);
    const enabled = event.target.getAttribute("aria-pressed") !== "true";
    return setSearchProviderEnabled(index, enabled);
  }
});

$("#github-access-form").addEventListener("submit", async event => {
  event.preventDefault();
  const button = event.target.querySelector('button[type="submit"]');
  setButtonBusy(button, true, "Saving...");
  try {
    const saved = await api("/settings/community-catalog", { method: "PUT", body: JSON.stringify(githubAccessFormData()) });
    fillForm(saved);
    fillGithubAccessForm(saved);
    toast("GitHub access saved");
  }
  catch (error) { toast(error.message); }
  finally { setButtonBusy(button, false); }
});

$("#lookup-form").addEventListener("submit", async event => {
  event.preventDefault();
  const button = event.target.querySelector('button[type="submit"]');
  setButtonBusy(button, true, "Saving...");
  try {
    fillLookupForm(await api("/settings/lookup", { method: "PUT", body: JSON.stringify(lookupFormData()) }));
    toast("Lookup settings saved");
  }
  catch (error) { toast(error.message); }
  finally { setButtonBusy(button, false); }
});

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
  if (event.target.matches(".source-refresh")) return refreshCatalogSource(event.target, index);
  if (event.target.matches(".source-toggle")) {
    syncCatalogSourcesFromDom();
    if (!catalogSources[index]) return;
    catalogSources[index].enabled = event.target.getAttribute("aria-pressed") !== "true";
    return renderCatalogSources();
  }
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
