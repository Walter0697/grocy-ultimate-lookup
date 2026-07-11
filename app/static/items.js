const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;" })[c]);

let categories = [];

let activeSearch = "";
let activeCategoryId = null;
let dialogVariantId = null;
let options = { locations: [], quantity_units: [] };
let expansionEl = null;
let expansionCategoryId = null;
let expansionClosing = null;
let toggleGeneration = 0;

const SWITCH_PAUSE_MS = 100;
const CLOSE_ANIMATION_MS = 320;
const ITEMS_PAGE_DIALOGS = ["#items-dialog", "#add-category-dialog", "#add-item-dialog"];

function closeItemsDialogs(exceptSelector = null) {
  ITEMS_PAGE_DIALOGS.forEach(selector => {
    if (selector === exceptSelector) return;
    const dialog = $(selector);
    if (dialog?.open) dialog.close();
  });
  if (!exceptSelector) {
    addItemCategoryId = null;
    dialogVariantId = null;
  }
  syncItemsPageInert();
}

function itemsPageDialogOpen() {
  return ITEMS_PAGE_DIALOGS.some(selector => $(selector)?.open);
}

function syncItemsPageInert() {
  const inert = itemsPageDialogOpen();
  document.body.classList.toggle("items-dialog-open", inert);
  const addCategoryButton = $("#open-add-category");
  if (addCategoryButton) addCategoryButton.disabled = inert;
}

function bindDialogCancelHandlers() {
  $("#items-dialog")?.addEventListener("cancel", () => {
    stopCatalogImagePoll();
    dialogVariantId = null;
  });
  $("#add-item-dialog")?.addEventListener("cancel", () => {
    addItemCategoryId = null;
    syncItemsPageInert();
  });
}

const CURATED_EMOJIS = [
  "🍎", "🍌", "🍊", "🍋", "🍇", "🍉", "🍑", "🥭", "🍍", "🥥", "🥝", "🍅", "🥑", "🥦", "🥬", "🥒",
  "🌶️", "🫑", "🌽", "🥕", "🧄", "🧅", "🥔", "🍄", "🥜", "🌰", "🍞", "🥐", "🥖", "🧀", "🥚", "🍳",
  "🥓", "🍗", "🍖", "🐟", "🦐", "🍚", "🍝", "🍜", "🥣", "🧈", "🥛", "🍯", "🫘", "🌾", "🍪", "🍰",
  "☕", "🍵", "🧊", "🫙", "🥡", "🍱", "🥗", "🌿", "🍲", "🧃", "🥤", "🍷", "🍺", "📦",
];

let categoryIconMode = "emoji";
let categoryImagePreviewUrl = "";
let addItemCategoryId = null;
let itemImagePreviewUrl = "";
let catalogImagePollTimer = null;
let activeCatalogImageEventId = null;

const VARIANT_OVERRIDE_KEY = "items-variant-overrides";

function readVariantOverrides() {
  try {
    return JSON.parse(localStorage.getItem(VARIANT_OVERRIDE_KEY) || "{}");
  } catch {
    return {};
  }
}

function writeVariantOverrides(overrides) {
  localStorage.setItem(VARIANT_OVERRIDE_KEY, JSON.stringify(overrides));
}

function patchVariantOverride(variantId, patch) {
  const overrides = readVariantOverrides();
  overrides[variantId] = { ...(overrides[variantId] || {}), ...patch };
  writeVariantOverrides(overrides);
}

function applyVariantOverridesToList(categoriesList) {
  const overrides = readVariantOverrides();
  return categoriesList.map(category => ({
    ...category,
    variants: (category.variants || []).map(variant => {
      const patch = overrides[variant.id];
      return patch ? { ...variant, ...patch } : variant;
    }),
  }));
}

function variantPhotoMarkup(category, variant, { badge = "" } = {}) {
  if (variant.image_url) {
    return `<div class="photo variant-photo"><img src="${escapeHtml(variant.image_url)}" alt="${escapeHtml(variant.name)}">${badge}</div>`;
  }
  if (variant.emoji) {
    return `<div class="photo"><div class="placeholder"><strong>${escapeHtml(variant.emoji)}</strong></div>${badge}</div>`;
  }
  return categoryPhotoMarkup(category, { badge });
}

function wait(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  setTimeout(() => node.classList.remove("show"), 3200);
}

function setExternalCatalogLoading(loading) {
  const node = $("#items-external-catalog-status");
  if (!node) return;
  node.classList.toggle("hidden", !loading);
}

async function api(path, init, json = true) {
  const response = await fetch(path, { headers: json ? { "Content-Type": "application/json" } : {}, ...init });
  if (!response.ok) {
    const body = await response.text();
    let message = response.statusText;
    if (body) {
      try {
        message = JSON.parse(body).detail || message;
      } catch {
        message = body;
      }
    }
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

function setButtonBusy(button, busy, label) {
  if (!button) return;
  if (busy) button.dataset.label = button.textContent;
  button.disabled = busy;
  button.classList.toggle("busy-button", busy);
  button.textContent = busy ? label : button.dataset.label || button.textContent;
}

function variantBarcode(variant) {
  if (variant.barcode) return variant.barcode;
  const stored = readVariantOverrides()[variant.id]?.barcode;
  if (stored) return stored;
  const slug = String(variant.id).replace(/[^a-zA-Z0-9]/g, "").toUpperCase().slice(0, 32);
  return `GUL${slug || "ITEM"}`;
}

function resolveQuantityUnitId(unitName) {
  const units = options.quantity_units || [];
  if (!units.length) return null;
  const normalized = String(unitName || "piece").toLowerCase();
  const exact = units.find(unit => unit.name.toLowerCase() === normalized);
  if (exact) return exact.id;
  const fuzzy = units.find(unit => {
    const name = unit.name.toLowerCase();
    return normalized.includes(name) || name.includes(normalized);
  });
  return (fuzzy || units[0]).id;
}

function resolveProductLocationId(stockLocationId, variant) {
  if (stockLocationId) return stockLocationId;
  const fromVariant = StockConfirm.resolveLocationId(options.locations, variant.location || variant.default_location);
  if (fromVariant) return Number(fromVariant);
  const first = options.locations[0]?.id;
  return first ? Number(first) : null;
}

function absoluteImageUrl(url) {
  const trimmed = String(url || "").trim();
  if (!trimmed) return null;
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  if (trimmed.startsWith("/")) return `${window.location.origin}${trimmed}`;
  return trimmed;
}

async function submitVariantStock(variant, detail, stockValues, barcode) {
  const productLocationId = resolveProductLocationId(stockValues.location_id, variant);
  const unitId = resolveQuantityUnitId(variant.unit);
  if (!productLocationId) throw new Error("No storage location configured in Grocy.");
  if (!unitId) throw new Error("No quantity units configured in Grocy.");

  const product = {
    name: detail.name,
    description: detail.note || null,
    quantity: variant.quantity || null,
    image_url: absoluteImageUrl(detail.image_url),
    catalog_contribution: false,
    lookup_source: "manual-catalog",
    location_id: productLocationId,
    qu_id_stock: unitId,
    qu_id_purchase: unitId,
    qu_factor_purchase_to_stock: 1,
  };
  if (!product.description) delete product.description;
  if (!product.quantity) delete product.quantity;
  if (!product.image_url) delete product.image_url;

  const payload = {
    event_id: `items-${variant.id}-${Date.now()}`,
    device_id: "items-page",
    barcode,
    mode: stockValues.mode,
    quantity: stockValues.quantity,
    product,
  };
  if (stockValues.location_id) payload.location_id = stockValues.location_id;

  return api("/dashboard/scan-confirm", { method: "POST", body: JSON.stringify(payload) });
}

function catalogImagePreviewUrl(imageUrl) {
  const trimmed = String(imageUrl || "").trim();
  if (!trimmed) return "";
  try {
    const url = new URL(trimmed, window.location.origin);
    if (url.pathname.startsWith("/uploaded-images/")) return url.pathname;
    return trimmed;
  } catch {
    return trimmed;
  }
}

function stopCatalogImagePoll() {
  if (catalogImagePollTimer) {
    clearInterval(catalogImagePollTimer);
    catalogImagePollTimer = null;
  }
  activeCatalogImageEventId = null;
  const button = $("#request-catalog-image-button");
  if (button) {
    button.disabled = false;
    button.classList.remove("busy-button");
    if (button.dataset.label) button.textContent = button.dataset.label;
  }
  $("#variant-image-preview")?.classList.remove("items-image-waiting");
}

function applyCatalogImageToDialog(variantId, imageUrl) {
  const previewUrl = catalogImagePreviewUrl(imageUrl);
  const category = categoryByVariantId(variantId);
  $("#variant-image-url-input").value = previewUrl;
  const preview = $("#variant-image-preview");
  if (preview && category) {
    preview.innerHTML = variantImagePreviewMarkup(category, { image_url: previewUrl });
    preview.classList.remove("items-image-waiting");
  }
}

function setCatalogImageWaiting(waiting) {
  const button = $("#request-catalog-image-button");
  const status = $("#catalog-image-status");
  const preview = $("#variant-image-preview");
  if (button) {
    if (waiting) {
      if (!button.dataset.label) button.dataset.label = button.textContent;
      button.disabled = true;
      button.classList.add("busy-button");
      button.textContent = "Waiting for image…";
    } else {
      button.disabled = false;
      button.classList.remove("busy-button");
      button.textContent = button.dataset.label || "Request external image";
    }
  }
  if (status) status.textContent = waiting ? "Pending on Dashboard — upload from your external client." : "";
  preview?.classList.toggle("items-image-waiting", waiting);
}

async function requestCatalogImageReview(variant) {
  const detail = readVariantDetailFields();
  const name = detail.name || variant.name;
  const barcode = variantBarcode(variant);
  const locationId = StockConfirm.resolveLocationId(options.locations, variant.location || variant.default_location);
  const event = await api("/dashboard/catalog-image-review", {
    method: "POST",
    body: JSON.stringify({
      barcode,
      product_name: name,
      variant_id: variant.id,
      location_id: locationId ? Number(locationId) : null,
    }),
  });
  activeCatalogImageEventId = event.event_id;
  if (event.image_url) {
    applyCatalogImageToDialog(variant.id, event.image_url);
    toast("External image already available.");
    return;
  }
  if (event.status !== "pending") return;
  toast("Waiting for external image — see Dashboard Needs review.");
  startCatalogImagePoll(event.event_id, variant.id);
}

function startCatalogImagePoll(eventId, variantId) {
  stopCatalogImagePoll();
  activeCatalogImageEventId = eventId;
  setCatalogImageWaiting(true);
  const poll = async () => {
    if (dialogVariantId !== variantId || activeCatalogImageEventId !== eventId) {
      stopCatalogImagePoll();
      return;
    }
    try {
      const event = await api(`/scan-events/${eventId}`);
      if (event.image_url) {
        applyCatalogImageToDialog(variantId, event.image_url);
        stopCatalogImagePoll();
        api(`/scan-events/${eventId}`, { method: "DELETE" }).catch(() => {});
        toast("External image received.");
      } else if (!["pending", "researching", "processing"].includes(event.status)) {
        stopCatalogImagePoll();
      }
    } catch {
      stopCatalogImagePoll();
    }
  };
  poll();
  catalogImagePollTimer = setInterval(poll, 2500);
}

function filteredCategories() {
  return categories.filter(category => {
    const haystack = [
      category.name,
      category.group,
      ...category.variants.map(variant => `${variant.name} ${variant.note} ${variant.id}`),
    ].join(" ").toLowerCase();
    return haystack.includes(activeSearch);
  });
}

function activeCategory() {
  return categories.find(category => category.id === activeCategoryId) || null;
}

function categoryByVariantId(variantId) {
  return categories.find(category => category.variants.some(variant => variant.id === variantId)) || null;
}

function variantById(variantId) {
  const category = categoryByVariantId(variantId);
  return category?.variants.find(variant => variant.id === variantId) || null;
}

function categoryEmoji(category) {
  return category.emoji || "📦";
}

function categoryPhotoMarkup(category, { badge = "" } = {}) {
  if (category.image_url) {
    return `<div class="photo category-photo"><img src="${escapeHtml(category.image_url)}" alt="">${badge}</div>`;
  }
  return `<div class="photo"><div class="placeholder"><strong>${escapeHtml(categoryEmoji(category))}</strong></div>${badge}</div>`;
}

function categoryIconInline(category) {
  if (category.image_url) {
    return `<img class="category-inline-icon" src="${escapeHtml(category.image_url)}" alt="">`;
  }
  return `<span class="category-inline-emoji">${escapeHtml(categoryEmoji(category))}</span>`;
}

function addItemPolaroid(category) {
  return `<article class="polaroid items-card variant-card add-item-card" data-action="add-item" data-category-id="${escapeHtml(category.id)}">
    <div class="photo"><div class="placeholder add-category-placeholder"><strong>+</strong></div></div>
    <div class="caption">
      <span>${escapeHtml(category.name)}</span>
      <h2>Add item</h2>
      <p>Custom variant</p>
    </div>
  </article>`;
}
function addCategoryPolaroid() {
  return `<article class="polaroid items-card category-card add-category-card" data-action="add-category">
    <div class="photo"><div class="placeholder add-category-placeholder"><strong>+</strong></div></div>
    <div class="caption">
      <span>custom</span>
      <h2>Add category</h2>
      <p>New browse group</p>
    </div>
  </article>`;
}
function filteredVariants(category) {
  return category.variants.filter(variant => {
    const haystack = `${variant.name} ${variant.note} ${variant.stock} ${variant.location}`.toLowerCase();
    return haystack.includes(activeSearch);
  });
}

function categoryPolaroid(category, index) {
  const selected = category.id === activeCategoryId ? " selected" : "";
  const count = `${category.variants.length} item${category.variants.length === 1 ? "" : "s"}`;
  return `<article class="polaroid applied items-card category-card${selected}" data-category-id="${escapeHtml(category.id)}" style="--delay:${Math.min(index, 10) * 35}ms">
    ${categoryPhotoMarkup(category)}
    <div class="caption">
      <span>${escapeHtml(category.group)}</span>
      <h2>${escapeHtml(category.name)}</h2>
      <p>${escapeHtml(count)}</p>
    </div>
  </article>`;
}

function variantPolaroid(category, variant) {
  const badge = variant.favorite ? `<em class="badge set">Favorite</em>` : "";
  return `<article class="polaroid applied items-card variant-card" data-variant-id="${escapeHtml(variant.id)}">
    ${variantPhotoMarkup(category, variant, { badge })}
    <div class="caption">
      <span>${escapeHtml(category.name)}</span>
      <h2>${escapeHtml(variant.name)}</h2>
      <p>${escapeHtml(variant.stock)} · ${escapeHtml(variant.location)}</p>
    </div>
  </article>`;
}

function expansionHeaderMarkup(category) {
  return `<div class="items-expansion-heading">
    <div>
      <p class="drawer-kicker">${escapeHtml(category.group)} · pick an item</p>
      <h3>${categoryIconInline(category)} ${escapeHtml(category.name)}</h3>
    </div>
    <button type="button" class="items-add-item-button" data-action="add-item" data-category-id="${escapeHtml(category.id)}">+ Add item</button>
  </div>`;
}

function expansionVariantsMarkup(category) {
  const variants = filteredVariants(category);
  const addCard = addItemPolaroid(category);
  if (!variants.length) {
    const empty = activeSearch
      ? `<div class="empty">No items match this search in ${escapeHtml(category.name)}.</div>`
      : `<div class="empty items-expansion-empty">No items yet. Tap + Add item to create one.</div>`;
    return `${empty}${addCard}`;
  }
  return `${variants.map(variant => variantPolaroid(category, variant)).join("")}${addCard}`;
}

function expansionMarkup(category) {
  return `<section class="items-expansion" data-expansion-for="${escapeHtml(category.id)}">
    <div class="items-expansion-clip">
      <div class="items-expansion-inner">
        <div class="items-expansion-arrow" aria-hidden="true"></div>
        <div class="items-expansion-panel">
          <div class="items-expansion-header">${expansionHeaderMarkup(category)}</div>
          <div class="items-expansion-grid">${expansionVariantsMarkup(category)}</div>
        </div>
      </div>
    </div>
  </section>`;
}

function rowEndIndex(cards, selectedIndex) {
  if (!cards.length || selectedIndex < 0) return selectedIndex;
  const rowTop = cards[selectedIndex].offsetTop;
  let end = selectedIndex;
  for (let index = selectedIndex; index < cards.length; index += 1) {
    if (cards[index].offsetTop !== rowTop) break;
    end = index;
  }
  return end;
}

function positionExpansionArrow() {
  const grid = $("#items-grid");
  const expansion = expansionEl || grid.querySelector(".items-expansion");
  const selected = grid.querySelector(".category-card.selected");
  if (!expansion || !selected) return;
  const gridRect = grid.getBoundingClientRect();
  const cardRect = selected.getBoundingClientRect();
  const center = cardRect.left + cardRect.width / 2 - gridRect.left;
  expansion.style.setProperty("--arrow-left", `${center}px`);
}

function updateSelection() {
  $("#items-grid").querySelectorAll(".category-card").forEach(card => {
    card.classList.toggle("selected", card.dataset.categoryId === activeCategoryId);
  });
}

function expansionAnchor(categoryId) {
  const grid = $("#items-grid");
  const cards = [...grid.querySelectorAll(".category-card")];
  const selectedIndex = cards.findIndex(card => card.dataset.categoryId === categoryId);
  if (selectedIndex < 0) return null;
  return cards[rowEndIndex(cards, selectedIndex)];
}

function destroyExpansionImmediate() {
  expansionEl?.remove();
  expansionEl = null;
  expansionCategoryId = null;
  expansionClosing = null;
}

function closeExpansion() {
  if (expansionClosing) return expansionClosing;
  expansionClosing = new Promise(resolve => {
    const node = expansionEl;
    if (!node) {
      expansionClosing = null;
      resolve();
      return;
    }
    const clip = node.querySelector(".items-expansion-clip");
    const finish = () => {
      node.remove();
      if (expansionEl === node) expansionEl = null;
      expansionCategoryId = null;
      expansionClosing = null;
      resolve();
    };
    if (!clip || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      finish();
      return;
    }
    let done = false;
    const end = () => {
      if (done) return;
      done = true;
      finish();
    };
    clip.addEventListener("transitionend", event => {
      if (event.propertyName === "grid-template-rows") end();
    }, { once: true });
    node.classList.add("is-closing");
    requestAnimationFrame(() => {
      node.classList.remove("is-open");
      setTimeout(end, CLOSE_ANIMATION_MS + 80);
    });
  });
  return expansionClosing;
}

function openExpansion(category) {
  const anchor = expansionAnchor(category.id);
  if (!anchor) return;
  anchor.insertAdjacentHTML("afterend", expansionMarkup(category));
  expansionEl = $("#items-grid").querySelector(".items-expansion");
  expansionCategoryId = category.id;
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      expansionEl?.classList.add("is-open");
      positionExpansionArrow();
      expansionEl?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
  });
}

function refreshExpansionContent(category) {
  if (!expansionEl) return;
  expansionEl.dataset.expansionFor = category.id;
  expansionEl.querySelector(".items-expansion-header").innerHTML = expansionHeaderMarkup(category);
  expansionEl.querySelector(".items-expansion-grid").innerHTML = expansionVariantsMarkup(category);
}

async function toggleCategory(categoryId) {
  const generation = ++toggleGeneration;

  if (activeCategoryId === categoryId) {
    activeCategoryId = null;
    updateSelection();
    await closeExpansion();
    return;
  }

  const wasOpen = Boolean(expansionEl);

  if (wasOpen) {
    await closeExpansion();
    if (generation !== toggleGeneration) return;
    await wait(SWITCH_PAUSE_MS);
    if (generation !== toggleGeneration) return;
  }

  activeCategoryId = categoryId;
  updateSelection();
  const category = activeCategory();
  if (!category) return;

  openExpansion(category);
}

function renderCategories() {
  const visible = filteredCategories();
  if (activeCategoryId && !visible.some(entry => entry.id === activeCategoryId)) {
    activeCategoryId = null;
  }

  destroyExpansionImmediate();

  if (!visible.length) {
    $("#items-grid").innerHTML = `${addCategoryPolaroid()}<div class="empty">No categories match this search.</div>`;
    return;
  }

  $("#items-grid").innerHTML = `${visible.map((entry, index) => categoryPolaroid(entry, index)).join("")}${addCategoryPolaroid()}`;

  const category = activeCategory();
  if (!category) return;

  updateSelection();
  openExpansion(category);
}


function normalizeReferenceVariant(variant) {
  return {
    ...variant,
    stock: variant.stock ?? "Not in pantry",
    location: variant.location ?? variant.default_location ?? "Pantry",
    favorite: Boolean(variant.favorite),
    custom: Boolean(variant.custom),
  };
}

function normalizeCustomItem(item) {
  return normalizeReferenceVariant({
    id: item.id,
    name: item.name,
    quantity: item.quantity,
    unit: item.unit,
    default_location: item.default_location,
    note: item.note,
    emoji: item.emoji,
    image_url: item.image_url,
    favorite: item.favorite,
    custom: true,
  });
}

function mergeCustomItems(categoriesList, items) {
  const byCategory = new Map();
  for (const item of items) {
    if (!byCategory.has(item.category_id)) byCategory.set(item.category_id, []);
    byCategory.get(item.category_id).push(normalizeCustomItem(item));
  }
  return categoriesList.map(category => ({
    ...category,
    variants: [
      ...(category.variants || []),
      ...(byCategory.get(category.id) || []),
    ],
  }));
}

async function loadReference() {
  const url = window.__ITEMS_CATALOG_URL || "/static/items-reference.json";
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error("Failed to load catalog");
    const data = await response.json();
    return (data.categories || []).map(category => ({
      ...category,
      custom: false,
      variants: (category.variants || []).map(normalizeReferenceVariant),
    }));
  } catch {
    toast("Could not load item catalog.");
    return [];
  }
}

async function loadCustomCategories() {
  try {
    const response = await fetch("/dashboard/manual-categories");
    if (!response.ok) throw new Error("Failed to load custom categories");
    return await response.json();
  } catch {
    return [];
  }
}

async function loadCustomItems() {
  try {
    const response = await fetch("/dashboard/manual-category-items");
    if (!response.ok) throw new Error("Failed to load custom items");
    return await response.json();
  } catch {
    return [];
  }
}

async function loadCommunityCatalogCategories() {
  try {
    const response = await fetch("/dashboard/community-catalog-items");
    if (!response.ok) throw new Error("Failed to load subscribed catalog items");
    const data = await response.json();
    return (Array.isArray(data) ? data : []).map(category => ({
      ...category,
      custom: false,
      community_catalog: true,
      variants: (category.variants || []).map(normalizeReferenceVariant),
    }));
  } catch {
    return [];
  }
}

async function loadCategories() {
  const [referenceCategories, communityCatalogCategories, customCategories, customItems] = await Promise.all([
    loadReference(),
    loadCommunityCatalogCategories(),
    loadCustomCategories(),
    loadCustomItems(),
  ]);
  const merged = [
    ...referenceCategories,
    ...communityCatalogCategories,
    ...customCategories.map(category => ({
      ...category,
      custom: true,
      variants: [],
    })),
  ];
  categories = applyVariantOverridesToList(mergeCustomItems(merged, customItems));
}

async function loadLocalCategories() {
  const [referenceCategories, customCategories, customItems] = await Promise.all([
    loadReference(),
    loadCustomCategories(),
    loadCustomItems(),
  ]);
  const merged = [
    ...referenceCategories,
    ...customCategories.map(category => ({
      ...category,
      custom: true,
      variants: [],
    })),
  ];
  categories = applyVariantOverridesToList(mergeCustomItems(merged, customItems));
}

function categoryMergeKey(category) {
  return String(category?.name || "").trim().toLowerCase();
}

function mergeCategoryLists(baseCategories, incomingCategories) {
  const merged = [...baseCategories];
  const byKey = new Map(merged.map(category => [categoryMergeKey(category), category]));
  for (const incoming of incomingCategories) {
    const key = categoryMergeKey(incoming);
    if (!key) {
      merged.push(incoming);
      continue;
    }
    const existing = byKey.get(key);
    if (!existing) {
      merged.push(incoming);
      byKey.set(key, incoming);
      continue;
    }
    existing.group = existing.group || incoming.group;
    existing.emoji = existing.emoji || incoming.emoji;
    existing.image_url = existing.image_url || incoming.image_url;
    existing.community_catalog = Boolean(existing.community_catalog || incoming.community_catalog);
    existing.variants = [...(existing.variants || []), ...(incoming.variants || [])];
  }
  return merged;
}

async function mergeCommunityCatalogCategories() {
  const communityCatalogCategories = await loadCommunityCatalogCategories();
  if (!communityCatalogCategories.length) return;
  categories = applyVariantOverridesToList(
    mergeCategoryLists(categories.filter(category => !category.community_catalog), communityCatalogCategories)
  );
}

async function loadOptions() {
  try {
    const response = await fetch("/dashboard/options");
    if (!response.ok) throw new Error("Failed to load locations");
    options = await response.json();
  } catch {
    options = { locations: [], quantity_units: [] };
  }
}

function variantImagePreviewMarkup(category, variant) {
  if (variant.image_url) {
    return `<img src="${escapeHtml(variant.image_url)}" alt="${escapeHtml(variant.name)}">`;
  }
  return `<div class="items-image-preview-empty">No custom photo yet — the category icon is used in the grid.</div>`;
}

function variantDetailFieldsMarkup(category, variant) {
  return `<div class="items-variant-detail product-edit-fields">
    <fieldset class="items-photo-fieldset">
      <legend>Item photo</legend>
      <p class="items-photo-help">Shown in your catalog and sent to Grocy when you confirm stock.</p>
      <div id="variant-image-preview" class="items-item-photo-preview" aria-live="polite">${variantImagePreviewMarkup(category, variant)}</div>
      <label class="items-upload-label">Upload image<input type="file" id="variant-image-upload" accept="image/*"></label>
      <button type="button" id="request-catalog-image-button" class="secondary">Request external image</button>
      <p id="catalog-image-status" class="items-photo-help" aria-live="polite"></p>
      <button type="button" id="clear-variant-image-button" class="secondary items-clear-photo-button">Remove photo</button>
      <input type="hidden" id="variant-image-url-input" value="${escapeHtml(variant.image_url || "")}">
    </fieldset>
    <label>Name<input name="variant_name" type="text" required maxlength="120" value="${escapeHtml(variant.name)}"></label>
    <label>Description<textarea name="variant_note" rows="3" maxlength="240" placeholder="Optional detail for this item">${escapeHtml(variant.note || "")}</textarea></label>
  </div>`;
}

function readVariantDetailFields() {
  const root = $("#items-dialog-content");
  return {
    name: root?.querySelector("input[name='variant_name']")?.value.trim() || "",
    note: root?.querySelector("textarea[name='variant_note']")?.value.trim() || "",
    image_url: $("#variant-image-url-input")?.value.trim() || "",
  };
}

function applyVariantDetail(variantId, detail) {
  const category = categoryByVariantId(variantId);
  const variant = variantById(variantId);
  if (!variant) return;
  const next = {
    name: detail.name || variant.name,
    note: detail.note || null,
    image_url: detail.image_url || null,
  };
  Object.assign(variant, next);
  patchVariantOverride(variantId, next);
  if (category && activeCategoryId === category.id) {
    refreshExpansionContent(category);
  }
}

function dialogMarkup(category, variant) {
  const locationId = StockConfirm.resolveLocationId(options.locations, variant.location);
  return `
    <p class="drawer-kicker">${escapeHtml(category.group)} · ${escapeHtml(category.name)}</p>
    <h2>${escapeHtml(variant.name)}</h2>
    <p class="items-dialog-hint">Edit this item for lookup, then confirm the stock change below.</p>
    ${variantDetailFieldsMarkup(category, variant)}
    <p class="current-stock">Current stock: <b>${escapeHtml(variant.stock)}</b> · ${escapeHtml(variant.unit)} · ${escapeHtml(variant.quantity)}</p>
    ${StockConfirm.formMarkup({
      formId: "item-confirm-form",
      locations: options.locations,
      selectedLocationId: locationId,
      quantity: "1",
    })}`;
}

function openVariantDialog(variantId) {
  const category = categoryByVariantId(variantId);
  const variant = variantById(variantId);
  if (!category || !variant) return;
  closeItemsDialogs("#items-dialog");
  dialogVariantId = variantId;
  $("#items-dialog-content").innerHTML = dialogMarkup(category, variant);
  $("#items-dialog").showModal();
  StockConfirm.updateConfirmLabel($("#item-confirm-form"));
  syncItemsPageInert();
  requestAnimationFrame(() => $("#items-dialog")?.scrollTo(0, 0));
}

$("#items-search-input").addEventListener("input", event => {
  activeSearch = event.target.value.trim().toLowerCase();
  if (expansionEl && activeCategoryId) {
    const category = activeCategory();
    if (category) refreshExpansionContent(category);
    return;
  }
  renderCategories();
});

document.addEventListener("click", event => {
  if (event.target.closest("#items-dialog")) {
    const choice = event.target.closest(".choice");
    if (choice) {
      const form = StockConfirm.findForm(choice);
      if (form && StockConfirm.handleChoiceClick(choice)) {
        StockConfirm.updateConfirmLabel(form);
      }
    }
    return;
  }
});

function handleItemsGridClick(event) {
  if (itemsPageDialogOpen()) return;

  if (event.target.closest("[data-action='add-category']") || event.target.closest("#open-add-category")) {
    openAddCategoryDialog();
    return;
  }

  const addItem = event.target.closest("[data-action='add-item']");
  if (addItem) {
    event.preventDefault();
    event.stopPropagation();
    openAddItemDialog(addItem.dataset.categoryId);
    return;
  }

  const category = event.target.closest(".category-card[data-category-id]");
  if (category) {
    toggleCategory(category.dataset.categoryId);
    return;
  }

  const variant = event.target.closest("[data-variant-id]");
  if (variant) {
    openVariantDialog(variant.dataset.variantId);
    return;
  }
}

$("#items-grid")?.addEventListener("click", handleItemsGridClick);

document.addEventListener("input", event => {
  const form = StockConfirm.findForm(event.target);
  if (form && StockConfirm.handleQuantityInput(event.target)) {
    StockConfirm.updateConfirmLabel(form);
  }
});

document.addEventListener("submit", async event => {
  if (!event.target.matches("#item-confirm-form")) return;
  event.preventDefault();
  const variantId = dialogVariantId;
  const variantEntry = variantById(variantId);
  if (!variantEntry) return;
  const detail = readVariantDetailFields();
  if (!detail.name) {
    toast("Item name is required.");
    return;
  }
  const { mode, quantity, location_id } = StockConfirm.readValues(event.target);
  if (mode === "set" && !confirm(`Set stock to ${quantity}?`)) return;

  applyVariantDetail(variantId, detail);
  const barcode = variantBarcode(variantEntry);
  const button = event.target.querySelector(".confirm-scan");
  setButtonBusy(button, true, "Updating Grocy...");
  try {
    const result = await submitVariantStock(variantEntry, detail, { mode, quantity, location_id }, barcode);
    if (result.status === "failed") {
      toast(result.error || "Stock update failed.");
      return;
    }
    patchVariantOverride(variantId, {
      barcode,
      product_id: result.product_id,
      grocy_linked: result.status === "applied",
    });
    variantEntry.barcode = barcode;
    if (result.product_id) variantEntry.product_id = result.product_id;
    if (result.stock_after != null) {
      variantEntry.stock = `${result.stock_after} ${variantEntry.unit}`;
    }
    const category = categoryByVariantId(variantId);
    if (category && activeCategoryId === category.id) {
      refreshExpansionContent(category);
    }
    const stockLabel = result.stock_after != null ? ` — stock now ${result.stock_after}` : "";
    toast(`${detail.name} updated in Grocy${stockLabel}. See Dashboard for the event.`);
    dialogVariantId = null;
    $("#items-dialog").close();
    syncItemsPageInert();
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false);
  }
});

$("#close-items-dialog").addEventListener("click", () => {
  stopCatalogImagePoll();
  dialogVariantId = null;
  $("#items-dialog").close();
  syncItemsPageInert();
});
$("#items-dialog").addEventListener("click", event => {
  if (event.target.matches("#request-catalog-image-button")) {
    const variant = variantById(dialogVariantId);
    if (!variant) return;
    requestCatalogImageReview(variant).catch(error => {
      stopCatalogImagePoll();
      toast(error.message);
    });
    return;
  }
  if (event.target.matches("#clear-variant-image-button")) {
    $("#variant-image-url-input").value = "";
    $("#variant-image-upload").value = "";
    const category = categoryByVariantId(dialogVariantId);
    $("#variant-image-preview").innerHTML = variantImagePreviewMarkup(category, { image_url: "" });
    return;
  }
  if (event.target === $("#items-dialog")) {
    stopCatalogImagePoll();
    dialogVariantId = null;
    $("#items-dialog").close();
    syncItemsPageInert();
  }
});
$("#items-dialog")?.addEventListener("change", async event => {
  if (!event.target.matches("#variant-image-upload")) return;
  const file = event.target.files?.[0];
  if (!file) return;
  event.target.disabled = true;
  try {
    await uploadLookupImage(file, {
      previewSelector: "#variant-image-preview",
      urlInputSelector: "#variant-image-url-input",
    });
  } catch (error) {
    toast(error.message);
  } finally {
    event.target.disabled = false;
  }
});

window.addEventListener("resize", () => {
  if (activeCategoryId) positionExpansionArrow();
});

function updateActiveCategoryCount() {
  const category = activeCategory();
  if (!category) return;
  const card = document.querySelector(`.category-card[data-category-id="${category.id}"]`);
  const countNode = card?.querySelector(".caption p");
  if (!countNode) return;
  const count = `${category.variants.length} item${category.variants.length === 1 ? "" : "s"}`;
  countNode.textContent = count;
}

async function init() {
  $("#items-grid").innerHTML = `<div class="empty">Loading catalog...</div>`;
  renderCategoryEmojiPanel();
  resetAddCategoryForm();
  resetAddItemForm();
  try {
    await Promise.all([loadLocalCategories(), loadOptions()]);
    renderCategories();
  } catch (error) {
    $("#items-grid").innerHTML = `<div class="empty">Could not load catalog.</div>`;
    toast(error.message || "Could not load catalog.");
    return;
  }
  setExternalCatalogLoading(true);
  mergeCommunityCatalogCategories()
    .then(() => {
      renderCategories();
    })
    .catch(error => {
      toast(error.message || "Could not load subscribed catalog items.");
    })
    .finally(() => {
      setExternalCatalogLoading(false);
    });
}

function renderCategoryEmojiPanel() {
  const panel = $("#category-emoji-panel");
  if (!panel) return;
  panel.innerHTML = CURATED_EMOJIS.map(emoji => (
    `<button type="button" class="choice items-emoji-option" data-emoji="${escapeHtml(emoji)}" aria-label="${escapeHtml(emoji)}">${emoji}</button>`
  )).join("");
}

function setCategoryIconMode(mode) {
  categoryIconMode = mode;
  $("#add-category-form")?.querySelectorAll("[data-icon-mode]").forEach(button => {
    button.classList.toggle("selected", button.dataset.iconMode === mode);
  });
  $("#category-emoji-panel")?.classList.toggle("hidden", mode !== "emoji");
  $("#category-image-panel")?.classList.toggle("hidden", mode !== "image");
}

function resetAddCategoryForm() {
  const form = $("#add-category-form");
  if (!form) return;
  form.reset();
  categoryImagePreviewUrl = "";
  $("#category-emoji-input").value = "";
  $("#category-image-url-input").value = "";
  $("#category-image-preview").innerHTML = `<div class="items-image-preview-empty">Upload a square-ish photo to use as the category icon.</div>`;
  $("#category-emoji-panel")?.querySelectorAll(".items-emoji-option").forEach(button => {
    button.classList.remove("selected");
  });
  setCategoryIconMode("emoji");
}

function openAddCategoryDialog() {
  closeItemsDialogs("#add-category-dialog");
  resetAddCategoryForm();
  $("#add-category-dialog").showModal();
  syncItemsPageInert();
  requestAnimationFrame(() => {
    $("#add-category-dialog")?.scrollTo(0, 0);
    $("#add-category-form input[name='name']")?.focus({ preventScroll: true });
  });
}

function closeAddCategoryDialog() {
  $("#add-category-dialog").close();
  syncItemsPageInert();
}

async function uploadCategoryImage(file) {
  const body = new FormData();
  body.append("file", file);
  const response = await fetch("/product-image-uploads", { method: "POST", body });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || "Image upload failed");
  }
  const uploaded = await response.json();
  categoryImagePreviewUrl = uploaded.preview_url;
  $("#category-image-url-input").value = uploaded.preview_url;
  $("#category-emoji-input").value = "";
  $("#category-emoji-panel")?.querySelectorAll(".items-emoji-option").forEach(button => {
    button.classList.remove("selected");
  });
  $("#category-image-preview").innerHTML = `<img src="${escapeHtml(uploaded.preview_url)}" alt="">`;
}

async function saveCustomCategory(form) {
  const payload = {
    name: form.name.value.trim(),
    group: form.group.value,
  };
  if (categoryIconMode === "image") {
    payload.image_url = $("#category-image-url-input").value.trim();
    if (!payload.image_url) throw new Error("Upload an image or switch to emoji.");
  } else {
    payload.emoji = $("#category-emoji-input").value.trim();
    if (!payload.emoji) throw new Error("Pick an emoji or switch to image.");
  }

  const response = await fetch("/dashboard/manual-categories", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(parseApiError(error, "Could not save category"));
  }
  return response.json();
}

function parseApiError(error, fallback) {
  const detail = error.detail;
  if (Array.isArray(detail)) return detail.map(item => item.msg).join(" ");
  if (typeof detail === "string") return detail;
  return fallback;
}

function populateItemLocationSelect() {
  const select = $("#add-item-location-select");
  if (!select) return;
  const locations = options.locations?.length
    ? options.locations
    : [{ id: "", name: "Pantry" }];
  select.innerHTML = locations.map(location => (
    `<option value="${escapeHtml(location.name)}">${escapeHtml(location.name)}</option>`
  )).join("");
}

function resetAddItemForm() {
  const form = $("#add-item-form");
  if (!form) return;
  form.reset();
  addItemCategoryId = null;
  itemImagePreviewUrl = "";
  $("#item-image-url-input").value = "";
  $("#item-image-preview").innerHTML = `<div class="items-image-preview-empty">No photo yet — the category icon will be used.</div>`;
  populateItemLocationSelect();
}

function openAddItemDialog(categoryId) {
  const category = categories.find(entry => entry.id === categoryId);
  if (!category) return;
  closeItemsDialogs("#add-item-dialog");
  addItemCategoryId = categoryId;
  resetAddItemForm();
  addItemCategoryId = categoryId;
  $("#add-item-kicker").textContent = `${category.group} · ${category.name}`;
  $("#add-item-title").textContent = `Add item to ${category.name}`;
  $("#add-item-dialog").showModal();
  syncItemsPageInert();
  requestAnimationFrame(() => {
    $("#add-item-dialog")?.scrollTo(0, 0);
    $("#add-item-form input[name='name']")?.focus({ preventScroll: true });
  });
}

function closeAddItemDialog() {
  addItemCategoryId = null;
  $("#add-item-dialog").close();
  syncItemsPageInert();
}

async function uploadLookupImage(file, { previewSelector, urlInputSelector }) {
  const body = new FormData();
  body.append("file", file);
  const response = await fetch("/product-image-uploads", { method: "POST", body });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(parseApiError(error, "Image upload failed"));
  }
  const uploaded = await response.json();
  $(urlInputSelector).value = uploaded.preview_url;
  $(previewSelector).innerHTML = `<img src="${escapeHtml(uploaded.preview_url)}" alt="">`;
  return uploaded.preview_url;
}

async function uploadItemImage(file) {
  itemImagePreviewUrl = await uploadLookupImage(file, {
    previewSelector: "#item-image-preview",
    urlInputSelector: "#item-image-url-input",
  });
}

function clearItemImage() {
  itemImagePreviewUrl = "";
  $("#item-image-url-input").value = "";
  $("#item-image-upload").value = "";
  $("#item-image-preview").innerHTML = `<div class="items-image-preview-empty">No photo yet — the category icon will be used.</div>`;
}

async function saveCustomItem(form) {
  if (!addItemCategoryId) throw new Error("No category selected for this item.");
  const payload = {
    name: form.name.value.trim(),
    quantity: form.quantity.value.trim(),
    unit: form.unit.value,
    default_location: form.default_location.value,
    note: form.note.value.trim() || null,
    favorite: Boolean(form.favorite?.checked),
  };
  const imageUrl = $("#item-image-url-input").value.trim();
  if (imageUrl) payload.image_url = imageUrl;

  const response = await fetch(`/dashboard/manual-categories/${encodeURIComponent(addItemCategoryId)}/items`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(parseApiError(error, "Could not save item"));
  }
  return response.json();
}

$("#open-add-category")?.addEventListener("click", openAddCategoryDialog);
$("#close-add-category-dialog")?.addEventListener("click", closeAddCategoryDialog);
$("#add-category-dialog")?.addEventListener("click", event => {
  if (event.target === $("#add-category-dialog")) closeAddCategoryDialog();
});
$("#category-emoji-panel")?.addEventListener("click", event => {
  const button = event.target.closest("[data-emoji]");
  if (!button) return;
  $("#category-emoji-input").value = button.dataset.emoji;
  $("#category-image-url-input").value = "";
  categoryImagePreviewUrl = "";
  $("#category-emoji-panel").querySelectorAll(".items-emoji-option").forEach(node => {
    node.classList.toggle("selected", node === button);
  });
});
$("#add-category-form")?.addEventListener("click", event => {
  const modeButton = event.target.closest("[data-icon-mode]");
  if (modeButton) {
    setCategoryIconMode(modeButton.dataset.iconMode);
  }
});
$("#category-image-upload")?.addEventListener("change", async event => {
  const file = event.target.files?.[0];
  if (!file) return;
  event.target.disabled = true;
  try {
    await uploadCategoryImage(file);
    setCategoryIconMode("image");
  } catch (error) {
    toast(error.message);
  } finally {
    event.target.disabled = false;
  }
});
$("#add-category-form")?.addEventListener("submit", async event => {
  event.preventDefault();
  const button = $("#save-category-button");
  button.disabled = true;
  try {
    const category = await saveCustomCategory(event.target);
    categories.push({
      ...category,
      variants: (category.variants || []).map(normalizeReferenceVariant),
    });
    closeAddCategoryDialog();
    activeCategoryId = category.id;
    renderCategories();
    toast(`Added ${category.name}.`);
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
  }
});

$("#close-add-item-dialog")?.addEventListener("click", closeAddItemDialog);
$("#add-item-dialog")?.addEventListener("click", event => {
  if (event.target === $("#add-item-dialog")) closeAddItemDialog();
});
$("#item-image-upload")?.addEventListener("change", async event => {
  const file = event.target.files?.[0];
  if (!file) return;
  event.target.disabled = true;
  try {
    await uploadItemImage(file);
  } catch (error) {
    toast(error.message);
  } finally {
    event.target.disabled = false;
  }
});
$("#clear-item-image-button")?.addEventListener("click", clearItemImage);
$("#add-item-form")?.addEventListener("submit", async event => {
  event.preventDefault();
  const button = $("#save-item-button");
  button.disabled = true;
  try {
    const item = await saveCustomItem(event.target);
    const category = categories.find(entry => entry.id === item.category_id);
    if (!category) throw new Error("Category not found after save.");
    const variant = normalizeCustomItem(item);
    category.variants.push(variant);
    closeAddItemDialog();
    if (activeCategoryId === category.id) {
      refreshExpansionContent(category);
      updateActiveCategoryCount();
    } else {
      renderCategories();
    }
    toast(`Added ${variant.name}.`);
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
  }
});

bindDialogCancelHandlers();
syncItemsPageInert();
init();
