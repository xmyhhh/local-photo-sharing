function openFolderContextMenu(event, entry) {
  event.preventDefault();
  if (state.selectionMode) {
    closeAllContextMenus();
    return;
  }
  closeAllContextMenus();
  state.contextFolder = entry;
  state.contextEntry = entry;
  if (isVirtualRootEntry(entry)) {
    renderContextMenu(folderContextMenu, [
      menuSection("原生操作", [
        menuButton("打开", "↵", () => navigateFolder(entry.path)),
        menuButton("多选", "☑", () => enterSelectionMode(entry.path)),
      ]),
      menuSection("访问控制", publicAlbumMenuItems(entry)),
      ...pluginMenuSections("folder"),
    ]);
    openContextMenuAt(folderContextMenu, event.clientX, event.clientY);
    return;
  }
  renderContextMenu(folderContextMenu, [
    menuSection("原生操作", [
      menuButton("下载", "↓", () => downloadEntry(entry)),
      menuButton("重命名", "✎", () => renameEntry(entry)),
      menuButton("删除", "×", () => deleteEntries([entry.path]), { danger: true }),
      menuButton("多选", "☑", () => enterSelectionMode(entry.path)),
    ]),
    menuSection("访问控制", publicAlbumMenuItems(entry)),
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
    ...(entry.type === "photo" ? pluginMenuSections("file") : []),
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

function isVirtualRootEntry(entry) {
  return !state.rootId && entry?.type === "folder" && state.roots.some((root) => root.id === entry.path);
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
    return menuButton(label, trigger.icon || "", () => dispatchPluginComponentAction(component, trigger), { plugin: true });
  })));
}

function publicAlbumMenuItems(entry) {
  if (!state.authEnabled || state.authRole !== "admin") {
    return [];
  }
  const path = qualifyPath(entry.path);
  const isPublic = isExactPublicAlbum(path);
  return [
    menuButton(isPublic ? "取消公开相册" : "设为公开相册", isPublic ? "🔒" : "🔓", () => setPublicAlbum(path, !isPublic)),
  ];
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
  iconNode.classList.toggle("empty", !icon);
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
  const parent = state.rootId ? currentRootedFolderPath() : "";
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
  const message = recycleBinEnabled()
    ? `确认删除 ${paths.length} 项？文件会放入回收站。`
    : `确认永久删除 ${paths.length} 项？回收站未启用，此操作不可撤销。`;
  if (!paths.length || !window.confirm(message)) {
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
  const destination = window.prompt("目标文件夹路径，例如 root1/子目录。留空表示默认保存地址。", state.rootId ? currentRootedFolderPath() : "");
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

function selectedEntries() {
  return Array.from(state.selectedPaths)
    .map((path) => state.entryByPath.get(path))
    .filter(Boolean);
}

function selectedEntriesAreAllPhotos(entries = selectedEntries()) {
  return entries.length === state.selectedPaths.size && entries.length > 0 && entries.every((entry) => entry.type === "photo");
}

async function rateSelectedPhotos(rating) {
  const entries = selectedEntries();
  if (!selectedEntriesAreAllPhotos(entries)) {
    return;
  }
  const previousBusy = batchRatingButtons.some((button) => button.disabled);
  batchRatingButtons.forEach((button) => {
    button.disabled = true;
  });
  try {
    const result = await fetchJson("/api/ratings/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths: entries.map((entry) => entry.path), rating }),
    });
    (result.updated || []).forEach((item) => {
      const entry = state.entryByPath.get(item.path);
      if (!entry) {
        return;
      }
      entry.rating = item.rating;
      entry.ratingPending = false;
      if (!entryMatchesActiveRatingFilter(entry)) {
        state.selectedPaths.delete(entry.path);
        removeGridEntry(entry);
      } else {
        updateGridRating(entry);
      }
    });
    const failed = result.failed || [];
    if (failed.length) {
      window.alert(`有 ${failed.length} 张照片评分写入失败，其余照片已完成。`);
    }
  } finally {
    batchRatingButtons.forEach((button) => {
      button.disabled = previousBusy ? button.disabled : false;
    });
    updateSelectionBar();
  }
}

function currentRootedFolderPath() {
  if (!state.rootId) {
    return "";
  }
  return state.folder ? qualifyPath(state.folder) : state.rootId;
}

async function setPublicAlbum(path, publicAlbum) {
  const normalized = normalizeRootedSettingsPath(path);
  if (!normalized) {
    return;
  }
  const albums = publicAlbum
    ? Array.from(new Set([...state.publicAlbums, normalized]))
    : state.publicAlbums.filter((item) => normalizeRootedSettingsPath(item) !== normalized);
  const settings = await fetchJson("/api/auth/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ publicAlbums: albums }),
  });
  applyAuthStatus(settings);
  if (typeof notifyBackendTaskStarted === "function") {
    notifyBackendTaskStarted();
  }
  renderGrid();
}

function entryFromTile(tile) {
  return tile?.dataset?.path ? state.entryByPath.get(tile.dataset.path) : null;
}

function handleGridTileClick(event) {
  const tile = event.target.closest(".tile");
  if (!tile || !grid.contains(tile) || event.target.closest(".rating")) {
    return;
  }
  const entry = entryFromTile(tile);
  if (!entry) {
    return;
  }
  if (event.target.closest(".tile-select")) {
    handleCheckboxSelectionClick(event, entry.path);
    return;
  }
  if (!event.target.closest(".tile-button")) {
    return;
  }
  if (consumeLongPressClick()) {
    return;
  }
  if (handleSelectionClick(event, entry.path)) {
    return;
  }
  if (entry.type === "folder") {
    navigateFolder(entry.path);
  } else {
    openViewer(entry);
  }
}

function handleGridTileContextMenu(event) {
  const tile = event.target.closest(".tile");
  if (!tile || !grid.contains(tile)) {
    openBlankContextMenu(event);
    return;
  }
  const entry = entryFromTile(tile);
  if (!entry) {
    return;
  }
  if (entry.type === "folder") {
    openFolderContextMenu(event, entry);
  } else {
    openItemContextMenu(event, entry);
  }
}

function handleGridTilePointerDown(event) {
  const tile = event.target.closest(".tile");
  if (!tile || !grid.contains(tile)) {
    scheduleBlankLongPress(event);
    startBoxSelection(event);
    return;
  }
  const entry = entryFromTile(tile);
  if (entry) {
    scheduleEntryLongPress(event, entry);
  }
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
  if (state.authRole === "admin") {
    notifyBackendTaskStarted();
  }
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
  if (event.cancelable) {
    event.preventDefault();
  }
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

function shouldSuppressNativeTouchMenu(event) {
  const target = event.target;
  if (!target?.closest?.(".grid, .tile, .tile-button")) {
    return false;
  }
  if (target.closest("input, textarea, select, .rating, .tile-select, button:not(.tile-button)")) {
    return false;
  }
  return true;
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
  updateSelectionModeChrome();
  updateSelectionBar();
  updateAllSelectionTiles();
}

function exitSelectionMode() {
  state.selectionMode = false;
  state.selectedPaths.clear();
  state.selectionAnchorPath = "";
  cancelBoxSelection();
  updateSelectionModeChrome();
  updateSelectionBar();
  updateAllSelectionTiles();
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
  updateAllSelectionTiles();
}

function handleCheckboxSelectionClick(event, path) {
  const checkbox = event.target.closest(".tile-select");
  if (!checkbox) {
    return;
  }
  event.stopPropagation();
  if (!state.selectionMode) {
    state.selectionMode = true;
    closeAllContextMenus();
    updateSelectionModeChrome();
  }
  if (event.shiftKey) {
    event.preventDefault();
    selectRangeTo(path, event.ctrlKey || event.metaKey);
  } else {
    toggleSelectedPath(path, checkbox.checked);
    state.selectionAnchorPath = path;
  }
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
    updateSelectionModeChrome();
  }
  if (range) {
    selectRangeTo(path, additive);
  } else {
    toggleSelectedPath(path);
    state.selectionAnchorPath = path;
  }
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
  updateAllSelectionTiles();
}

function updateSelectionTile(path) {
  const selected = state.selectedPaths.has(path);
  const tile = document.querySelector(`.tile[data-path="${CSS.escape(path)}"]`);
  tile?.classList.toggle("selected", selected);
  const checkbox = tile?.querySelector(".tile-select");
  if (checkbox) {
    checkbox.checked = selected;
    checkbox.toggleAttribute("checked", selected);
  }
}

function startBoxSelection(event) {
  if (event.pointerType !== "mouse" || event.button !== 0 || event.target.closest(".tile") || event.target.closest(".context-menu")) {
    return;
  }
  event.preventDefault();
  closeAllContextMenus();
  const replacingSelection = !event.ctrlKey && !event.metaKey && !event.shiftKey;
  state.boxSelect = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    active: false,
    base: replacingSelection ? new Set() : new Set(state.selectedPaths),
    committed: state.selectionMode,
    startedInSelectionMode: state.selectionMode,
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
    closeAllContextMenus();
  }
  updateSelectionBox(event.clientX, event.clientY);
  const next = selectedPathsInBox();
  if (!state.boxSelect.committed && next.size < 2) {
    return;
  }
  if (!state.selectionMode) {
    state.selectionMode = true;
    updateSelectionModeChrome();
  }
  state.boxSelect.committed = true;
  state.selectedPaths = next;
  updateAllSelectionTiles();
  requestAnimationFrame(updateAllSelectionTiles);
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
  if (!state.boxSelect.committed) {
    cancelBoxSelection();
    return;
  }
  if (!state.boxSelect.startedInSelectionMode && state.selectedPaths.size < 2) {
    state.selectionMode = false;
    state.selectedPaths.clear();
    state.selectionAnchorPath = "";
    updateSelectionModeChrome();
    updateSelectionBar();
    cancelBoxSelection();
    updateAllSelectionTiles();
    return;
  }
  const selected = Array.from(state.selectedPaths);
  state.selectionAnchorPath = selected[selected.length - 1] || state.selectionAnchorPath;
  cancelBoxSelection();
  updateAllSelectionTiles();
}

function selectedPathsInBox() {
  const rect = selectionBox.getBoundingClientRect();
  const next = new Set(state.boxSelect.base);
  document.querySelectorAll(".tile").forEach((tile) => {
    const tileRect = tile.getBoundingClientRect();
    const intersects = rect.left <= tileRect.right
      && rect.right >= tileRect.left
      && rect.top <= tileRect.bottom
      && rect.bottom >= tileRect.top;
    if (intersects && tile.dataset.path) {
      next.add(tile.dataset.path);
    }
  });
  return next;
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
      checkbox.toggleAttribute("checked", selected);
    }
  });
}

function updateSelectionModeChrome() {
  grid?.classList.toggle("selection-mode", state.selectionMode);
}

function updateSelectionBar() {
  if (!selectionBar) {
    return;
  }
  selectionBar.hidden = !state.selectionMode;
  breadcrumb.classList.toggle("selection-hidden", state.selectionMode);
  thumbModeControl.classList.toggle("selection-hidden", state.selectionMode);
  filterPanelToggleBtn.hidden = state.selectionMode;
  compactToggleBtn.hidden = state.selectionMode;
  selectionCount.textContent = `已选择 ${state.selectedPaths.size} 项`;
  const hasSelection = state.selectedPaths.size > 0;
  const canBatchRate = selectedEntriesAreAllPhotos();
  if (batchRatingControl) {
    batchRatingControl.hidden = !canBatchRate;
  }
  if (typeof updateSelectionPluginActions === "function") {
    updateSelectionPluginActions();
  }
  batchRatingButtons.forEach((button) => {
    button.disabled = !canBatchRate;
  });
  [copySelectedBtn, cutSelectedBtn, downloadSelectedBtn, deleteSelectedBtn, moveSelectedBtn].forEach((button) => {
    if (button) {
      button.disabled = !hasSelection;
    }
  });
}
