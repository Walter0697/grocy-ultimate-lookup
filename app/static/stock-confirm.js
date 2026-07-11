(function () {
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;" })[c]);
  const MODE_LABELS = { add: "Add", remove: "Remove", set: "Set stock to" };

  function quantityChoices(quantity) {
    const value = String(quantity ?? "1");
    return ["1", "2", "3"].map(amount => {
      const selected = value === amount ? " selected" : "";
      return `<button type="button" class="choice quantity-choice${selected}" data-value="${amount}">${amount}</button>`;
    }).join("");
  }

  function formMarkup({
    formId = "",
    locations = [],
    selectedLocationId = "",
    quantity = "1",
    extraFieldsHtml = "",
    formClass = "",
  } = {}) {
    const formIdAttr = formId ? ` id="${escapeHtml(formId)}"` : "";
    const locationButtons = locations.map(location => {
      const selected = String(location.id) === String(selectedLocationId) ? " selected" : "";
      return `<button type="button" class="choice location-choice${selected}" data-value="${location.id}">${escapeHtml(location.name)}</button>`;
    }).join("");
    const defaultSelected = selectedLocationId ? "" : " selected";
    const qty = escapeHtml(quantity);
    return `<form${formIdAttr} class="stock-confirm-form ${formClass}">
      <fieldset><legend>Operation</legend><div class="choice-group"><button type="button" class="choice mode-choice selected add-choice" data-value="add">＋ Add</button><button type="button" class="choice mode-choice remove-choice" data-value="remove">− Remove</button><button type="button" class="choice mode-choice set-choice" data-value="set">◎ Manage / Set</button></div></fieldset>
      <fieldset><legend>Quantity</legend><div class="choice-group quantity-group">${quantityChoices(quantity)}<input class="custom-quantity" type="number" min="0" step="0.01" value="${qty}" aria-label="Custom quantity"></div></fieldset>
      <fieldset><legend>Stock location</legend><div class="choice-group location-group"><button type="button" class="choice location-choice${defaultSelected}" data-value="">Product default</button>${locationButtons}</div></fieldset>
      <button type="submit" class="confirm-scan">Confirm Add ${qty}</button>
      ${extraFieldsHtml}
    </form>`;
  }

  function getFormElements(form) {
    if (!form) return null;
    return {
      form,
      mode: () => form.querySelector(".mode-choice.selected")?.dataset.value || "add",
      quantity: () => form.querySelector(".custom-quantity")?.value || "1",
      location: () => form.querySelector(".location-choice.selected")?.dataset.value || "",
      submit: () => form.querySelector(".confirm-scan"),
    };
  }

  function updateConfirmLabel(form) {
    const els = getFormElements(form);
    if (!els?.submit()) return;
    const mode = els.mode();
    const quantity = els.quantity();
    els.submit().textContent = `Confirm ${MODE_LABELS[mode] || "Add"} ${quantity}`;
  }

  function handleChoiceClick(choice) {
    if (!choice?.classList.contains("choice")) return false;
    const group = choice.closest(".choice-group");
    if (!group) return false;
    group.querySelectorAll(".choice").forEach(node => node.classList.remove("selected"));
    choice.classList.add("selected");
    if (choice.classList.contains("quantity-choice")) {
      const quantityInput = choice.closest("form")?.querySelector(".custom-quantity");
      if (quantityInput) quantityInput.value = choice.dataset.value;
    }
    return true;
  }

  function handleQuantityInput(input) {
    if (!input?.classList.contains("custom-quantity")) return false;
    const group = input.closest(".quantity-group");
    if (!group) return false;
    group.querySelectorAll(".quantity-choice").forEach(node => {
      node.classList.toggle("selected", node.dataset.value === input.value);
    });
    return true;
  }

  function readValues(form) {
    const els = getFormElements(form);
    const location = els.location();
    return {
      mode: els.mode(),
      quantity: Number(els.quantity()),
      location_id: location ? Number(location) : null,
    };
  }

  function resolveLocationId(locations, name) {
    if (!name) return "";
    const match = locations.find(location => location.name.toLowerCase() === String(name).toLowerCase());
    return match ? String(match.id) : "";
  }

  function findForm(node) {
    return node?.matches?.(".stock-confirm-form") ? node : node?.closest?.(".stock-confirm-form") || null;
  }

  window.StockConfirm = {
    formMarkup,
    updateConfirmLabel,
    handleChoiceClick,
    handleQuantityInput,
    readValues,
    resolveLocationId,
    findForm,
  };
})();
