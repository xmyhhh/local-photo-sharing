function openFolderContextMenu(event, entry) {
  event.preventDefault();
  if (state.selectionMode) {
    closeAllContextMenus();
    return;
  }
  closeAllContextMenus();
  state.contextFolder = entry;
  state.contextEntry = entry;
  renderContextMenu(folderContextMenu, [
    menuSection("原生操作", [
      menuButton("下载", "↓", () => downloadEntry(entry)),
      menuButton("重命名", "✎", () => renameEntry(entry)),
      menuButton("删除", "×", () => deleteEntries([entry.path]), { danger: true }),
      menuButton("多选", "☑", () => enterSelectionMode(entry.path)),
    ]),
    ...pluginMenuSections("folder"),
  ]);
  openContextMenuAt(folderContextMenu, event.clientX, event.clientY);
}

function openItemContextMenu(event, entry) {
  event.preventDefault();
  event.stopPropagation();
  if (state.selectionMode) {
    closeAllContextMenus();
    return;
  }
  closeAllContextMenus();
  state.contextEntry = entry;
  state.contextFolder = entry.type === "folder" ? entry : null;
  renderContextMenu(itemContextMenu, [
    menuSection("原生操作", [
      menuButton("下载", "↓", () => downloadEntry(entry)),
      menuButton("重命名", "✎", () => renameEntry(entry)),
      menuButton("删除", "×", () => deleteEntries([entry.path]), { danger: true }),
      menuButton("多选", "☑", () => enterSelectionMode(entry.path)),
    ]),
  ]);
  openContextMenuAt(itemContextMenu, event.clientX, event.clientY);
}

function openBlankContextMenu(event) {
  if (state.selectionMode) {
    event.preventDefault();
    closeAllContextMenus();
    return;
  }
  if (event.target.closest(".tile") || event.target.closest(".context-menu")) {
    return;
  }
  event.preventDefault();
  closeAllContextMenus();
  state.contextFolder = null;
  state.contextEntry = null;
  renderContextMenu(blankContextMenu, [
    menuSection("原生操作", [
      menuButton("新建文件夹", "+", createFolderInCurrentFolder),
      menuButton("多选", "☑", () => enterSelectionMode()),
    ]),
  ]);
  openContextMenuAt(blankContextMenu, event.clientX, event.clientY);
}

function closeFolderContextMenu() {
  folderContextMenu.hidden = true;
}

function closeAllContextMenus() {
  folderContextMenu.hidden = true;
  blankContextMenu.hidden = true;
  itemContextMenu.hidden = true;
}

function renderContextMenu(menu, sections) {
  menu.innerHTML = "";
  sections.filter((section) => section.items.length).forEach((section) => {
    menu.append(section.element);
  });
}

function menuSection(title, items) {
  const section = document.createElement("div");
  section.className = "context-menu-section";
  const heading = document.createElement("div");
  heading.className = "context-menu-heading";
  heading.textContent = title;
  section.append(heading, ...items);
  return { element: section, items };
}

function pluginMenuSections(target) {
  if (typeof pluginContextMenuGroups !== "function") {
    return [];
  }
  return pluginContextMenuGroups(target).map((group) => menuSection(group.title, group.items.map(({ component, trigger }) => {
    const label = trigger.label || component.title || component.id;
    return menuButton(label, "◆", () => dispatchPluginComponentAction(component, trigger), { plugin: true });
  })));
}

function menuButton(label, icon, action, options = {}) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "context-menu-item";
  if (options.danger) {
    button.classList.add("danger");
  }
  if (options.plugin) {
    button.classList.add("plugin-action");
  }
  button.dataset.coreFileAction = "1";
  const iconNode = document.createElement("span");
  iconNode.className = "context-menu-icon";
  iconNode.textContent = icon;
  const labelNode = document.createElement("span");
  labelNode.className = "context-menu-label";
  labelNode.textContent = label;
  button.append(iconNode, labelNode);
  button.addEventListener("click", () => {
    closeAllContextMenus();
    action();
  });
  return button;
}

function openContextMenuAt(menu, clientX, clientY) {
  menu.hidden = false;
  const rect = menu.getBoundingClientRect();
  const left = Math.min(clientX, window.innerWidth - rect.width - 8);
  const top = Math.min(clientY, window.innerHeight - rect.height - 8);
  menu.style.left = `${Math.max(8, left)}px`;
  menu.style.top = `${Math.max(8, top)}px`;
}

async function createFolderInCurrentFolder() {
  const name = window.prompt("新建文件夹名称");
  if (!name) {
    return;
  }
  const parent = state.rootId ? qualifyPath(state.folder || "") : "";
  await fetchJson("/api/files/folder", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ parent, name }),
  });
  loadFolder(state.folder);
}

async function renameEntry(entry) {
  const name = window.prompt("新名称", entry.name);
  if (!name || name === entry.name) {
    return;
  }
  await fetchJson("/api/files/rename", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: entry.path, name }),
  });
  loadFolder(state.folder);
}

async function deleteEntries(paths) {
  if (!paths.length || !window.confirm(`确认删除 ${paths.length} 项？文件会移动到 .photo_share_trash。`)) {
    return;
  }
  await fetchJson("/api/files/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paths }),
  });
  exitSelectionMode();
  loadFolder(state.folder);
}

async function copyOrMoveSelected(move) {
  const paths = Array.from(state.selectedPaths);
  if (!paths.length) {
    return;
  }
  const destination = window.prompt("目标文件夹路径，例如 root1/子目录。留空表示默认保存地址。", state.rootId ? qualifyPath(state.folder || "") : "");
  if (destination === null) {
    return;
  }
  await fetchJson(move ? "/api/files/move" : "/api/files/copy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paths, destination }),
  });
  exitSelectionMode();
  loadFolder(state.folder);
}

async function cutSelectedEntries() {
  await copyOrMoveSelected(true);
}

async function downloadEntry(entry) {
  if (entry.type === "folder") {
    await downloadZip([entry.path], `${entry.name}.zip`);
    return;
  }
  window.location.href = `/api/download/${encodePath(entry.path)}`;
}

async function downloadSelectedEntries() {
  const paths = Array.from(state.selectedPaths);
  if (!paths.length) {
    return;
  }
  await downloadZip(paths, paths.length === 1 ? "photo-share.zip" : `photo-share-${paths.length}-items.zip`);
}

async function downloadZip(paths, fallbackName = "photo-share.zip") {
  const response = await fetch("/api/files/download-zip", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paths }),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  const blob = await response.blob();
  triggerBlobDownload(blob, filenameFromDisposition(response.headers.get("Content-Disposition")) || fallbackName);
}

function triggerBlobDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

function filenameFromDisposition(value) {
  if (!value) {
    return "";
  }
  const utf8Match = value.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch {
      return utf8Match[1];
    }
  }
  const plainMatch = value.match(/filename="?([^";]+)"?/i);
  return plainMatch ? plainMatch[1] : "";
}

function scheduleEntryLongPress(event, entry) {
  if (state.selectionMode || !isContextLongPressPointer(event) || event.target.closest(".tile-select") || event.target.closest(".rating")) {
    return;
  }
  startLongPress(event, () => {
    const menuEvent = longPressMenuEvent(event);
    if (entry.type === "folder") {
      openFolderContextMenu(menuEvent, entry);
    } else {
      openItemContextMenu(menuEvent, entry);
    }
  });
}

function scheduleBlankLongPress(event) {
  if (state.selectionMode || !isContextLongPressPointer(event) || event.target.closest(".tile") || event.target.closest(".context-menu")) {
    return;
  }
  startLongPress(event, () => openBlankContextMenu(longPressMenuEvent(event)));
}

function startLongPress(event, action) {
  cancelLongPress();
  state.longPress = {
    pointerId: event.pointerId,
    x: event.clientX,
    y: event.clientY,
    timer: window.setTimeout(() => {
      state.longPressTriggered = true;
      state.longPress = null;
      action();
    }, 620),
  };
}

function cancelLongPress() {
  if (state.longPress?.timer) {
    window.clearTimeout(state.longPress.timer);
  }
  state.longPress = null;
}

function cancelLongPressIfMoved(event) {
  if (!state.longPress || state.longPress.pointerId !== event.pointerId) {
    return;
  }
  const dx = event.clientX - state.longPress.x;
  const dy = event.clientY - state.longPress.y;
  if (Math.hypot(dx, dy) > 12) {
    cancelLongPress();
  }
}

function consumeLongPressClick() {
  if (!state.longPressTriggered) {
    return false;
  }
  state.longPressTriggered = false;
  return true;
}

function isContextLongPressPointer(event) {
  return event.pointerType === "touch" || event.pointerType === "pen";
}

function longPressMenuEvent(event) {
  return {
    clientX: event.clientX,
    clientY: event.clientY,
    target: event.target,
    preventDefault() {},
    stopPropagation() {},
  };
}

function enterSelectionMode(initialPath = "") {
  state.selectionMode = true;
  closeAllContextMenus();
  if (initialPath) {
    state.selectedPaths.add(initialPath);
    state.selectionAnchorPath = initialPath;
  }
  updateSelectionBar();
  renderGrid();
}

function exitSelectionMode() {
  state.selectionMode = false;
  state.selectedPaths.clear();
  state.selectionAnchorPath = "";
  cancelBoxSelection();
  updateSelectionBar();
  renderGrid();
}

function invertSelection() {
  const next = new Set();
  state.entries.forEach((entry) => {
    const path = qualifyPath(entry.path);
    if (!state.selectedPaths.has(path)) {
      next.add(path);
    }
  });
  state.selectedPaths = next;
  state.selectionAnchorPath = "";
  updateSelectionBar();
  renderGrid();
}

function handleSelectionClick(event, path, options = {}) {
  const forceSelection = Boolean(options.forceSelection);
  const additive = event.ctrlKey || event.metaKey;
  const range = event.shiftKey;
  if (!state.selectionMode && !forceSelection && !additive && !range) {
    return false;
  }
  event.preventDefault();
  event.stopPropagation();
  if (!state.selectionMode) {
    state.selectionMode = true;
    closeAllContextMenus();
  }
  if (range) {
    selectRangeTo(path, additive);
  } else {
    toggleSelectedPath(path);
    state.selectionAnchorPath = path;
  }
  renderGrid();
  return true;
}

function toggleSelectedPath(path, selected = null) {
  if (state.selectedPaths.has(path)) {
    if (selected !== true) {
      state.selectedPaths.delete(path);
    }
  } else {
    if (selected !== false) {
      state.selectedPaths.add(path);
    }
  }
  updateSelectionBar();
  updateSelectionTile(path);
}

function selectRangeTo(path, additive = false) {
  const paths = state.entries.map((entry) => qualifyPath(entry.path));
  const end = paths.indexOf(path);
  if (end < 0) {
    return;
  }
  const anchor = state.selectionAnchorPath && paths.includes(state.selectionAnchorPath)
    ? paths.indexOf(state.selectionAnchorPath)
    : end;
  if (!additive) {
    state.selectedPaths.clear();
  }
  const start = Math.min(anchor, end);
  const stop = Math.max(anchor, end);
  paths.slice(start, stop + 1).forEach((item) => state.selectedPaths.add(item));
  state.selectionAnchorPath = paths[anchor] || path;
  updateSelectionBar();
}

function updateSelectionTile(path) {
  const selected = state.selectedPaths.has(path);
  const tile = document.querySelector(`.tile[data-path="${CSS.escape(path)}"]`);
  tile?.classList.toggle("selected", selected);
  const checkbox = tile?.querySelector(".tile-select");
  if (checkbox) {
    checkbox.checked = selected;
  }
}

function startBoxSelection(event) {
  if (event.pointerType !== "mouse" || event.button !== 0 || event.target.closest(".tile") || event.target.closest(".context-menu")) {
    return;
  }
  event.preventDefault();
  closeAllContextMenus();
  if (!event.ctrlKey && !event.metaKey && !event.shiftKey) {
    state.selectedPaths.clear();
  }
  state.boxSelect = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    active: false,
    base: new Set(state.selectedPaths),
  };
  grid.setPointerCapture(event.pointerId);
}

function updateBoxSelection(event) {
  if (!state.boxSelect || state.boxSelect.pointerId !== event.pointerId) {
    return;
  }
  event.preventDefault();
  const width = Math.abs(event.clientX - state.boxSelect.startX);
  const height = Math.abs(event.clientY - state.boxSelect.startY);
  if (!state.boxSelect.active && Math.hypot(width, height) < 6) {
    return;
  }
  if (!state.boxSelect.active) {
    state.boxSelect.active = true;
    state.selectionMode = true;
    closeAllContextMenus();
  }
  updateSelectionBox(event.clientX, event.clientY);
  const rect = selectionBox.getBoundingClientRect();
  state.selectedPaths = new Set(state.boxSelect.base);
  document.querySelectorAll(".tile").forEach((tile) => {
    const tileRect = tile.getBoundingClientRect();
    const intersects = rect.left <= tileRect.right
      && rect.right >= tileRect.left
      && rect.top <= tileRect.bottom
      && rect.bottom >= tileRect.top;
    if (intersects && tile.dataset.path) {
      state.selectedPaths.add(tile.dataset.path);
    }
  });
  updateAllSelectionTiles();
  updateSelectionBar();
}

function finishBoxSelection(event) {
  if (!state.boxSelect || state.boxSelect.pointerId !== event.pointerId) {
    return;
  }
  if (!state.boxSelect.active) {
    cancelBoxSelection();
    return;
  }
  updateBoxSelection(event);
  const selected = Array.from(state.selectedPaths);
  state.selectionAnchorPath = selected[selected.length - 1] || state.selectionAnchorPath;
  cancelBoxSelection();
  renderGrid();
}

function cancelBoxSelection() {
  if (state.boxSelect?.pointerId !== undefined && grid.hasPointerCapture?.(state.boxSelect.pointerId)) {
    grid.releasePointerCapture(state.boxSelect.pointerId);
  }
  state.boxSelect = null;
  if (selectionBox) {
    selectionBox.hidden = true;
  }
}

function updateSelectionBox(clientX, clientY) {
  if (!selectionBox || !state.boxSelect) {
    return;
  }
  const left = Math.min(state.boxSelect.startX, clientX);
  const top = Math.min(state.boxSelect.startY, clientY);
  const width = Math.abs(clientX - state.boxSelect.startX);
  const height = Math.abs(clientY - state.boxSelect.startY);
  selectionBox.hidden = false;
  selectionBox.style.left = `${left}px`;
  selectionBox.style.top = `${top}px`;
  selectionBox.style.width = `${width}px`;
  selectionBox.style.height = `${height}px`;
}

function updateAllSelectionTiles() {
  document.querySelectorAll(".tile").forEach((tile) => {
    const selected = state.selectedPaths.has(tile.dataset.path);
    tile.classList.toggle("selected", selected);
    const checkbox = tile.querySelector(".tile-select");
    if (checkbox) {
      checkbox.checked = selected;
    }
  });
}

function updateSelectionBar() {
  if (!selectionBar) {
    return;
  }
  selectionBar.hidden = !state.selectionMode;
  filterPanelToggleBtn.hidden = state.selectionMode;
  compactToggleBtn.hidden = state.selectionMode;
  selectionCount.textContent = `已选择 ${state.selectedPaths.size} 项`;
  const hasSelection = state.selectedPaths.size > 0;
  [copySelectedBtn, cutSelectedBtn, downloadSelectedBtn, deleteSelectedBtn, moveSelectedBtn].forEach((button) => {
    if (button) {
      button.disabled = !hasSelection;
    }
  });
}
