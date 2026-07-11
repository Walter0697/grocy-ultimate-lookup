const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;" })[c]);

let categories = [];

let activeSearch = "";
let activeCategoryId = null;
let dialogVariantId = null;
let options = { locations: [] };
let expansionEl = null;
let expansionCategoryId = null;
let expansionClosing = null;
let toggleGeneration = 0;

const SWITCH_PAUSE_MS = 100;
const CLOSE_ANIMATION_MS = 320;

function wait(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  setTimeout(() => node.classList.remove("show"), 3200);
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
    <div class="photo"><div class="placeholder"><strong>${escapeHtml(category.emoji)}</strong></div></div>
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
    <div class="photo"><div class="placeholder"><strong>${escapeHtml(category.emoji)}</strong></div>${badge}</div>
    <div class="caption">
      <span>${escapeHtml(category.name)}</span>
      <h2>${escapeHtml(variant.name)}</h2>
      <p>${escapeHtml(variant.stock)} · ${escapeHtml(variant.location)}</p>
    </div>
  </article>`;
}

function expansionHeaderMarkup(category) {
  return `<p class="drawer-kicker">${escapeHtml(category.group)} · pick an item</p>
    <h3>${escapeHtml(category.emoji)} ${escapeHtml(category.name)}</h3>`;
}

function expansionVariantsMarkup(category) {
  const variants = filteredVariants(category);
  return variants.length
    ? variants.map(variant => variantPolaroid(category, variant)).join("")
    : `<div class="empty">No items match this search in ${escapeHtml(category.name)}.</div>`;
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
    $("#items-grid").innerHTML = `<div class="empty">No categories match this search.</div>`;
    return;
  }

  $("#items-grid").innerHTML = visible.map((entry, index) => categoryPolaroid(entry, index)).join("");

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
  };
}

async function loadReference() {
  const url = window.__ITEMS_CATALOG_URL || "/static/items-reference.json";
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error("Failed to load catalog");
    const data = await response.json();
    categories = (data.categories || []).map(category => ({
      ...category,
      variants: (category.variants || []).map(normalizeReferenceVariant),
    }));
  } catch {
    categories = [];
    toast("Could not load item catalog.");
  }
}

async function loadOptions() {
  try {
    const response = await fetch("/dashboard/options");
    if (!response.ok) throw new Error("Failed to load locations");
    options = await response.json();
  } catch {
    options = { locations: [] };
  }
}

function dialogMarkup(category, variant) {
  const locationId = StockConfirm.resolveLocationId(options.locations, variant.location);
  return `<div class="preview-photo"><div class="placeholder"><strong>${escapeHtml(category.emoji)}</strong></div></div>
    <p class="drawer-kicker">${escapeHtml(category.group)} · ${escapeHtml(category.name)}</p>
    <h2>${escapeHtml(variant.name)}</h2>
    <p class="current-stock">Current stock: <b>${escapeHtml(variant.stock)}</b> · ${escapeHtml(variant.unit)}</p>
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
  dialogVariantId = variantId;
  $("#items-dialog-content").innerHTML = dialogMarkup(category, variant);
  $("#items-dialog").showModal();
  StockConfirm.updateConfirmLabel($("#item-confirm-form"));
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
  const category = event.target.closest("[data-category-id]");
  if (category) {
    toggleCategory(category.dataset.categoryId);
    return;
  }

  const variant = event.target.closest("[data-variant-id]");
  if (variant) {
    openVariantDialog(variant.dataset.variantId);
    return;
  }

  const choice = event.target.closest(".choice");
  if (choice) {
    const form = StockConfirm.findForm(choice);
    if (form && StockConfirm.handleChoiceClick(choice)) {
      StockConfirm.updateConfirmLabel(form);
      return;
    }
  }
});

document.addEventListener("input", event => {
  const form = StockConfirm.findForm(event.target);
  if (form && StockConfirm.handleQuantityInput(event.target)) {
    StockConfirm.updateConfirmLabel(form);
  }
});

document.addEventListener("submit", event => {
  if (!event.target.matches("#item-confirm-form")) return;
  event.preventDefault();
  const variantEntry = variantById(dialogVariantId);
  if (!variantEntry) return;
  const { mode, quantity, location_id } = StockConfirm.readValues(event.target);
  if (mode === "set" && !confirm(`Set stock to ${quantity}?`)) return;
  const locationName = location_id
    ? options.locations.find(location => location.id === location_id)?.name || location_id
    : variantEntry.location;
  toast(`${variantEntry.name}: ${mode} ${quantity} at ${locationName} (mock)`);
  dialogVariantId = null;
  $("#items-dialog").close();
});

$("#close-items-dialog").addEventListener("click", () => {
  dialogVariantId = null;
  $("#items-dialog").close();
});
$("#items-dialog").addEventListener("click", event => {
  if (event.target === $("#items-dialog")) {
    dialogVariantId = null;
    $("#items-dialog").close();
  }
});

window.addEventListener("resize", () => {
  if (activeCategoryId) positionExpansionArrow();
});

async function init() {
  $("#items-grid").innerHTML = `<div class="empty">Loading catalog...</div>`;
  await Promise.all([loadReference(), loadOptions()]);
  renderCategories();
}

init();
