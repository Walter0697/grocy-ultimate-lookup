const $ = (selector) => document.querySelector(selector);

async function api(path, init) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!response.ok) throw new Error((await response.json()).detail || response.statusText);
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
  $("#community-catalog-status").innerHTML = `Repository: <b>${status.repository_url || "not configured"}</b><br>Branch: <b>${status.branch}</b><br>Internal checkout: <b>${status.path}</b><br>Exists: <b>${status.path_exists ? "yes" : "no"}</b><br>Git repository: <b>${status.is_git_repo ? "yes" : "no"}</b><br>Pending changes: <b>${status.pending_changes ? "yes" : "no"}</b>`;
}

function renderDiff(diff) {
  const files = diff.files.length ? diff.files.map(file => `<li>${file}</li>`).join("") : "<li>No pending files</li>";
  $("#community-catalog-diff").innerHTML = `Pending changes: <b>${diff.pending_changes ? "yes" : "no"}</b><ul>${files}</ul>`;
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
  try { renderDiff(await api("/settings/community-catalog/diff")); }
  catch (error) { toast(error.message); }
  finally { setButtonBusy(event.target, false); }
});

$("#push-community-catalog").addEventListener("click", async event => {
  setButtonBusy(event.target, true, "Pushing...");
  try {
    renderDiff(await api("/settings/community-catalog/push", { method: "POST" }));
    renderStatus(await api("/settings/community-catalog/test", { method: "POST" }));
    toast("Pending catalog changes pushed");
  }
  catch (error) { toast(error.message); }
  finally { setButtonBusy(event.target, false); }
});

$("#discard-community-catalog").addEventListener("click", async event => {
  setButtonBusy(event.target, true, "Discarding...");
  try {
    renderDiff(await api("/settings/community-catalog/discard", { method: "POST" }));
    renderStatus(await api("/settings/community-catalog/test", { method: "POST" }));
    toast("Pending catalog changes discarded");
  }
  catch (error) { toast(error.message); }
  finally { setButtonBusy(event.target, false); }
});

load().catch(error => toast(error.message));
