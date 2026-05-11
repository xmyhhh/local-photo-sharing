const recycleBinUi = {};

initRecycleBinPlugin();

function initRecycleBinPlugin() {
  pluginDialogs?.append(createRecycleBinDialog());
  registerPluginAction("recycle_bin.open", openRecycleBin);
  bindRecycleBinEvents();
}

function createRecycleBinDialog() {
  const template = document.createElement("template");
  template.innerHTML = `
    <dialog id="recycleBinDialog" class="recycle-dialog">
      <div class="recycle-panel">
        <div class="recycle-header">
          <div>
            <div class="recycle-title">回收站</div>
            <div id="recycleBinStatus" class="recycle-status"></div>
          </div>
          <button id="closeRecycleBinBtn" class="ghost" type="button">关闭</button>
        </div>
        <div id="recycleBinItems" class="recycle-items"></div>
        <div class="recycle-actions">
          <button id="refreshRecycleBinBtn" class="ghost" type="button">刷新</button>
          <button id="restoreRecycleBinBtn" type="button" disabled>还原选中</button>
        </div>
      </div>
    </dialog>
  `;
  const dialog = template.content.firstElementChild;
  recycleBinUi.dialog = dialog;
  recycleBinUi.status = dialog.querySelector("#recycleBinStatus");
  recycleBinUi.items = dialog.querySelector("#recycleBinItems");
  recycleBinUi.closeButton = dialog.querySelector("#closeRecycleBinBtn");
  recycleBinUi.refreshButton = dialog.querySelector("#refreshRecycleBinBtn");
  recycleBinUi.restoreButton = dialog.querySelector("#restoreRecycleBinBtn");
  return dialog;
}

function bindRecycleBinEvents() {
  recycleBinUi.closeButton.addEventListener("click", () => recycleBinUi.dialog.close());
  recycleBinUi.refreshButton.addEventListener("click", loadRecycleBinItems);
  recycleBinUi.restoreButton.addEventListener("click", restoreSelectedRecycleItems);
}

async function openRecycleBin() {
  recycleBinUi.dialog.showModal();
  await loadRecycleBinItems();
}

async function loadRecycleBinItems() {
  recycleBinUi.status.textContent = "正在读取回收站...";
  recycleBinUi.items.innerHTML = "";
  recycleBinUi.restoreButton.disabled = true;
  try {
    const data = await fetchJson("/api/recycle-bin/items", { cache: "no-store" });
    renderRecycleBinItems(data.items || []);
  } catch (error) {
    recycleBinUi.status.textContent = error.message;
  }
}

function renderRecycleBinItems(items) {
  recycleBinUi.items.innerHTML = "";
  recycleBinUi.status.textContent = items.length ? `${items.length} 个项目` : "回收站为空。";
  items.forEach((item) => recycleBinUi.items.append(createRecycleBinItem(item)));
  updateRecycleRestoreState();
}

function createRecycleBinItem(item) {
  const row = document.createElement("label");
  row.className = "recycle-item";
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.value = item.id;
  checkbox.addEventListener("change", updateRecycleRestoreState);
  const text = document.createElement("div");
  text.className = "recycle-item-text";
  const name = document.createElement("div");
  name.className = "recycle-item-name";
  name.textContent = item.originalName || item.trashName || item.originalRel;
  const meta = document.createElement("div");
  meta.className = "recycle-item-meta";
  meta.textContent = `${item.rootId}/${item.originalRel} · ${item.deletedAt || ""}`;
  text.append(name, meta);
  row.append(checkbox, text);
  return row;
}

function selectedRecycleIds() {
  return Array.from(recycleBinUi.items.querySelectorAll("input[type='checkbox']:checked")).map((input) => input.value);
}

function updateRecycleRestoreState() {
  recycleBinUi.restoreButton.disabled = selectedRecycleIds().length === 0;
}

async function restoreSelectedRecycleItems() {
  const ids = selectedRecycleIds();
  if (!ids.length) {
    return;
  }
  recycleBinUi.restoreButton.disabled = true;
  recycleBinUi.status.textContent = "正在还原...";
  try {
    const result = await fetchJson("/api/recycle-bin/restore", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids }),
    });
    recycleBinUi.status.textContent = `已还原 ${result.restored?.length || 0} 个项目。`;
    await loadRecycleBinItems();
    loadFolder(state.folder, { silent: true });
  } catch (error) {
    recycleBinUi.status.textContent = error.message;
    updateRecycleRestoreState();
  }
}
