function openFolderContextMenu(event, entry) {
  event.preventDefault();
  closeAllContextMenus();
  state.contextFolder = entry;
  state.contextEntry = entry;
  folderContextMenu.querySelectorAll("[data-core-file-action='1']").forEach((item) => item.remove());
  folderContextMenu.prepend(
    menuButton("下载", () => downloadEntry(entry)),
    menuButton("重命名", () => renameEntry(entry)),
    menuButton("删除", () => deleteEntries([entry.path])),
    menuButton("进入多选模式", () => enterSelectionMode(entry.path)),
  );
  folderContextMenu.querySelectorAll("[data-core-file-action='1']").forEach((item) => {
    item.hidden = false;
  });
  updatePluginContextMenuVisibility("folder");
  if (!Array.from(folderContextMenu.children).some((item) => !item.hidden)) {
    return;
  }
  openContextMenuAt(folderContextMenu, event.clientX, event.clientY);
}

function openItemContextMenu(event, entry) {
  event.preventDefault();
  event.stopPropagation();
  closeAllContextMenus();
  state.contextEntry = entry;
  state.contextFolder = entry.type === "folder" ? entry : null;
  itemContextMenu.innerHTML = "";
  itemContextMenu.append(
    menuButton("下载", () => downloadEntry(entry)),
    menuButton("重命名", () => renameEntry(entry)),
    menuButton("删除", () => deleteEntries([entry.path])),
    menuButton("进入多选模式", () => enterSelectionMode(entry.path)),
  );
  openContextMenuAt(itemContextMenu, event.clientX, event.clientY);
}

function openBlankContextMenu(event) {
  if (event.target.closest(".tile") || event.target.closest(".context-menu")) {
    return;
  }
  event.preventDefault();
  closeAllContextMenus();
  blankContextMenu.innerHTML = "";
  blankContextMenu.append(
    menuButton("新建文件夹", createFolderInCurrentFolder),
    menuButton("进入多选模式", () => enterSelectionMode()),
  );
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

function menuButton(label, action) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.dataset.coreFileAction = "1";
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

function updatePluginContextMenuVisibility(target) {
  folderContextMenu.querySelectorAll("[data-plugin-trigger='1']").forEach((item) => {
    item.hidden = item.dataset.triggerTarget && item.dataset.triggerTarget !== target;
  });
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
  if (!isContextLongPressPointer(event) || event.target.closest(".tile-select") || event.target.closest(".rating")) {
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
  if (!isContextLongPressPointer(event) || event.target.closest(".tile") || event.target.closest(".context-menu")) {
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
  if (initialPath) {
    state.selectedPaths.add(initialPath);
  }
  updateSelectionBar();
  renderGrid();
}

function exitSelectionMode() {
  state.selectionMode = false;
  state.selectedPaths.clear();
  updateSelectionBar();
  renderGrid();
}

function toggleSelectedPath(path) {
  if (state.selectedPaths.has(path)) {
    state.selectedPaths.delete(path);
  } else {
    state.selectedPaths.add(path);
  }
  updateSelectionBar();
  document.querySelector(`.tile[data-path="${CSS.escape(path)}"]`)?.classList.toggle("selected", state.selectedPaths.has(path));
}

function updateSelectionBar() {
  if (!selectionBar) {
    return;
  }
  selectionBar.hidden = !state.selectionMode;
  selectionCount.textContent = `已选择 ${state.selectedPaths.size} 项`;
}
