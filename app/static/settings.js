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
    path: form.path.value.trim(),
    export_images: form.export_images.checked,
    auto_commit: form.auto_commit.checked,
    auto_push: form.auto_push.checked,
    git_remote: form.git_remote.value.trim(),
    git_branch: form.git_branch.value.trim(),
    author_name: form.author_name.value.trim() || null,
    author_email: form.author_email.value.trim() || null
  };
}

function fillForm(settings) {
  const form = $("#community-catalog-form");
  form.enabled.checked = settings.enabled;
  form.path.value = settings.path;
  form.export_images.checked = settings.export_images;
  form.auto_commit.checked = settings.auto_commit;
  form.auto_push.checked = settings.auto_push;
  form.git_remote.value = settings.git_remote;
  form.git_branch.value = settings.git_branch;
  form.author_name.value = settings.author_name || "";
  form.author_email.value = settings.author_email || "";
}

function renderStatus(status) {
  $("#community-catalog-status").innerHTML = `Path: <b>${status.path}</b><br>Exists: <b>${status.path_exists ? "yes" : "no"}</b><br>Git repository: <b>${status.is_git_repo ? "yes" : "no"}</b>`;
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

$("#test-community-catalog").addEventListener("click", async event => {
  setButtonBusy(event.target, true, "Testing...");
  try {
    renderStatus(await api("/settings/community-catalog/test", { method: "POST" }));
  }
  catch (error) { toast(error.message); }
  finally { setButtonBusy(event.target, false); }
});

load().catch(error => toast(error.message));
