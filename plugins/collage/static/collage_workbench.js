const collageState = {
  groups: [],
  pool: [],
  current: null,
  selectedItemId: "",
  selectedPoolPaths: new Set(),
  librarySelectedPaths: new Set(),
  libraryRoot: "",
  libraryFolder: "",
  libraryParent: "",
  pendingPaths: [],
  dirtyTimer: 0,
  dragging: null,
  canvasScale: 1,
  canvasRenderFrame: 0,
  saveSeq: 0,
};

const groupList = document.querySelector("#collageGroups");
const groupCount = document.querySelector("#collageGroupCount");
const statusNode = document.querySelector("#collageStatus");
const canvasWrap = document.querySelector("#collageCanvasWrap");
const canvas = document.querySelector("#collageCanvas");
const nameInput = document.querySelector("#collageNameInput");
const saveBtn = document.querySelector("#collageSaveBtn");
const newGroupBtn = document.querySelector("#collageNewGroupBtn");
const downloadBtn = document.querySelector("#collageDownloadBtn");
const photosNode = document.querySelector("#collagePhotos");
const photoCount = document.querySelector("#collagePhotoCount");
const browseBtn = document.querySelector("#collageBrowseBtn");
const poolNode = document.querySelector("#collagePool");
const poolCount = document.querySelector("#collagePoolCount");
const addPoolBtn = document.querySelector("#collageAddPoolBtn");
const libraryDialog = document.querySelector("#collageLibraryDialog");
const closeLibraryBtn = document.querySelector("#collageCloseLibraryBtn");
const libraryBackBtn = document.querySelector("#collageLibraryBackBtn");
const libraryAddBtn = document.querySelector("#collageLibraryAddBtn");
const libraryPath = document.querySelector("#collageLibraryPath");
const libraryGrid = document.querySelector("#collageLibraryGrid");
const layoutButtons = Array.from(document.querySelectorAll("[data-layout]"));
const sizeSelect = document.querySelector("#collageSizeSelect");
const columnsInput = document.querySelector("#collageColumnsInput");
const gapInput = document.querySelector("#collageGapInput");
const paddingInput = document.querySelector("#collagePaddingInput");
const radiusInput = document.querySelector("#collageRadiusInput");
const backgroundInput = document.querySelector("#collageBackgroundInput");
const shadowInput = document.querySelector("#collageShadowInput");
const fitSelect = document.querySelector("#collageFitSelect");

initCollageWorkbench();

async function initCollageWorkbench() {
  readPendingPaths();
  bindWorkbenchEvents();
  await loadGroups();
  await loadPool();
  if (collageState.pendingPaths.length) {
    await addPendingToPool();
  } else {
    selectGroup(collageState.groups[0] || null);
  }
}

function readPendingPaths() {
  try {
    const raw = window.sessionStorage.getItem("photoShare.collage.pendingPaths");
    const parsed = JSON.parse(raw || "[]");
    collageState.pendingPaths = Array.isArray(parsed) ? parsed.filter((item) => typeof item === "string") : [];
    window.sessionStorage.removeItem("photoShare.collage.pendingPaths");
  } catch {
    collageState.pendingPaths = [];
  }
}

function bindWorkbenchEvents() {
  newGroupBtn.addEventListener("click", () => createEmptyGroup());
  saveBtn.addEventListener("click", () => saveCurrentGroup(true));
  nameInput.addEventListener("input", () => {
    if (!collageState.current) {
      return;
    }
    collageState.current.name = nameInput.value.trim() || "未命名拼图";
    scheduleSave();
    renderGroups();
  });
  layoutButtons.forEach((button) => {
    button.addEventListener("click", () => updateSetting("layout", button.dataset.layout));
  });
  sizeSelect.addEventListener("change", () => {
    const [width, height] = sizeSelect.value.split("x").map((value) => Number.parseInt(value, 10));
    updateSettings({ width, height });
  });
  columnsInput.addEventListener("input", () => updateSetting("columns", Number.parseInt(columnsInput.value, 10)));
  gapInput.addEventListener("input", () => updateSetting("gap", Number.parseInt(gapInput.value, 10)));
  paddingInput.addEventListener("input", () => updateSetting("padding", Number.parseInt(paddingInput.value, 10)));
  radiusInput.addEventListener("input", () => updateSetting("radius", Number.parseInt(radiusInput.value, 10)));
  backgroundInput.addEventListener("input", () => updateSetting("background", backgroundInput.value));
  shadowInput.addEventListener("change", () => updateSetting("shadow", shadowInput.checked));
  fitSelect.addEventListener("change", () => updateSetting("fit", fitSelect.value));
  browseBtn.addEventListener("click", openLibraryBrowser);
  addPoolBtn.addEventListener("click", addSelectedPoolToGroup);
  closeLibraryBtn.addEventListener("click", () => libraryDialog.close());
  libraryBackBtn.addEventListener("click", navigateLibraryUp);
  libraryAddBtn.addEventListener("click", addSelectedLibraryPhotos);
  window.addEventListener("resize", renderCanvas);
  document.addEventListener("pointermove", dragSelectedItem);
  document.addEventListener("pointerup", finishDrag);
}

async function loadGroups() {
  setStatus("正在读取工作组...");
  const data = await fetchJson("/api/collage/groups", { cache: "no-store" });
  collageState.groups = data.groups || [];
  renderGroups();
  setStatus("");
}

async function loadPool() {
  const data = await fetchJson("/api/collage/pool", { cache: "no-store" });
  collageState.pool = data.items || [];
  renderPool();
}

async function addPendingToPool() {
  setStatus(`已将 ${collageState.pendingPaths.length} 张照片加入拼图素材池。`);
  const data = await fetchJson("/api/collage/pool", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paths: collageState.pendingPaths }),
  });
  collageState.pool = data.items || [];
  collageState.pendingPaths = [];
  renderPool();
  selectGroup(collageState.groups[0] || null);
}

async function createEmptyGroup() {
  const data = await fetchJson("/api/collage/groups", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paths: [] }),
  });
  collageState.groups.unshift(data.group);
  renderGroups();
  selectGroup(data.group);
}

function renderGroups() {
  groupList.innerHTML = "";
  groupCount.textContent = `${collageState.groups.length} 个拼图`;
  if (!collageState.groups.length) {
    const empty = document.createElement("div");
    empty.className = "collage-empty";
    empty.textContent = "还没有拼图工作组。";
    groupList.append(empty);
    return;
  }
  collageState.groups.forEach((group) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "collage-group";
    button.classList.toggle("active", group.id === collageState.current?.id);
    const preview = document.createElement("div");
    preview.className = "collage-group-preview";
    if (group.imageUrl) {
      const img = document.createElement("img");
      img.src = group.imageUrl;
      img.alt = "";
      preview.append(img);
    }
    const text = document.createElement("div");
    text.className = "collage-group-text";
    const title = document.createElement("div");
    title.textContent = group.name;
    const meta = document.createElement("span");
    meta.textContent = `${group.items.length} 张`;
    text.append(title, meta);
    button.append(preview, text);
    button.addEventListener("click", () => selectGroup(group));
    groupList.append(button);
  });
}

function selectGroup(group) {
  collageState.current = group;
  collageState.selectedItemId = group?.items?.[0]?.id || "";
  renderGroups();
  renderInspector();
  renderCanvas();
  renderPhotos();
}

function renderInspector() {
  const group = collageState.current;
  const settings = group?.settings || defaultSettings();
  nameInput.value = group?.name || "";
  nameInput.disabled = !group;
  saveBtn.disabled = !group;
  browseBtn.disabled = false;
  addPoolBtn.disabled = collageState.selectedPoolPaths.size === 0;
  layoutButtons.forEach((button) => button.classList.toggle("active", button.dataset.layout === settings.layout));
  sizeSelect.value = `${settings.width}x${settings.height}`;
  columnsInput.value = settings.columns;
  gapInput.value = settings.gap;
  paddingInput.value = settings.padding;
  radiusInput.value = settings.radius;
  backgroundInput.value = settings.background;
  shadowInput.checked = settings.shadow !== false;
  fitSelect.value = settings.fit || "cover";
  downloadBtn.href = group?.downloadUrl || "#";
  downloadBtn.classList.toggle("disabled", !group?.downloadUrl);
}

function renderPhotos() {
  photosNode.innerHTML = "";
  const group = collageState.current;
  const items = group?.items || [];
  photoCount.textContent = `${items.length} 张`;
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "collage-empty";
    empty.textContent = "点击“添加照片”，或先从素材池加入当前工作组。";
    photosNode.append(empty);
    return;
  }
  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "collage-photo";
    row.classList.toggle("active", item.id === collageState.selectedItemId);
    const img = document.createElement("img");
    img.src = item.thumbUrl;
    img.alt = item.name;
    const name = document.createElement("span");
    name.textContent = item.name;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "collage-photo-remove";
    remove.setAttribute("aria-label", `移除 ${item.name}`);
    remove.textContent = "×";
    remove.addEventListener("click", (event) => {
      event.stopPropagation();
      removePhoto(item.id);
    });
    row.append(img, name, remove);
    row.addEventListener("click", () => {
      selectPhoto(item.id);
    });
    photosNode.append(row);
  });
}

function renderPool() {
  poolNode.innerHTML = "";
  const items = collageState.pool || [];
  poolCount.textContent = `${items.length} 张待用`;
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "collage-empty";
    empty.textContent = "在照片库右键或多选添加后，会先放到这里。";
    poolNode.append(empty);
    renderInspector();
    return;
  }
  items.forEach((item) => {
    const row = document.createElement("label");
    row.className = "collage-pool-item";
    row.classList.toggle("active", collageState.selectedPoolPaths.has(item.path));
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = collageState.selectedPoolPaths.has(item.path);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        collageState.selectedPoolPaths.add(item.path);
      } else {
        collageState.selectedPoolPaths.delete(item.path);
      }
      renderPool();
    });
    const img = document.createElement("img");
    img.src = item.thumbUrl;
    img.alt = item.name;
    const name = document.createElement("span");
    name.textContent = item.name;
    const add = document.createElement("button");
    add.type = "button";
    add.className = "collage-mini-action";
    add.textContent = "+";
    add.setAttribute("aria-label", `加入 ${item.name}`);
    add.addEventListener("click", (event) => {
      event.preventDefault();
      addPathsToCurrentGroup([item.path]);
    });
    row.append(checkbox, img, name, add);
    poolNode.append(row);
  });
  renderInspector();
}

function renderCanvas() {
  canvas.innerHTML = "";
  const group = collageState.current;
  if (!group) {
    canvas.className = "collage-canvas empty";
    canvas.textContent = "新建一个工作组，然后从素材池或照片库添加照片。";
    return;
  }
  const settings = group.settings || defaultSettings();
  const scale = canvasScale(settings);
  collageState.canvasScale = scale;
  canvas.className = "collage-canvas";
  canvas.style.width = `${settings.width * scale}px`;
  canvas.style.height = `${settings.height * scale}px`;
  canvas.style.background = settings.background;
  const boxes = layoutBoxes(settings, group.items || []);
  group.items.forEach((item, index) => {
    const box = boxes[index];
    item.x = Math.round(box.x);
    item.y = Math.round(box.y);
    item.w = Math.round(box.w);
    item.h = Math.round(box.h);
    const node = document.createElement("div");
    node.className = "collage-frame";
    node.tabIndex = 0;
    node.setAttribute("role", "button");
    node.setAttribute("aria-label", item.name);
    node.classList.toggle("selected", item.id === collageState.selectedItemId);
    node.style.left = `${box.x * scale}px`;
    node.style.top = `${box.y * scale}px`;
    node.style.width = `${box.w * scale}px`;
    node.style.height = `${box.h * scale}px`;
    node.style.borderRadius = `${Math.min(settings.radius * scale, 28)}px`;
    node.style.padding = "0";
    node.dataset.itemId = item.id;
    const img = document.createElement("img");
    img.alt = item.name;
    img.decoding = "async";
    img.loading = "lazy";
    img.style.objectFit = settings.fit || "cover";
    setEditingImageSource(img, item);
    node.append(img);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "collage-frame-remove";
    remove.setAttribute("aria-label", `移除 ${item.name}`);
    remove.textContent = "×";
    remove.addEventListener("click", (event) => {
      event.stopPropagation();
      removePhoto(item.id);
    });
    remove.addEventListener("pointerdown", (event) => {
      event.stopPropagation();
    });
    node.append(remove);
    if (settings.layout === "free") {
      const handle = document.createElement("span");
      handle.className = "collage-resize-handle";
      handle.dataset.resize = "1";
      node.append(handle);
      node.addEventListener("pointerdown", startDrag);
    }
    node.addEventListener("click", () => {
      selectPhoto(item.id);
    });
    node.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectPhoto(item.id);
      }
    });
    canvas.append(node);
  });
}

function canvasScale(settings) {
  const wrapRect = canvasWrap.getBoundingClientRect();
  const maxWidth = Math.max(320, wrapRect.width - 48);
  const maxHeight = Math.max(320, wrapRect.height - 48);
  return Math.min(maxWidth / settings.width, maxHeight / settings.height, 0.72);
}

function updateSetting(key, value) {
  updateSettings({ [key]: value });
}

function updateSettings(patch) {
  if (!collageState.current) {
    return;
  }
  collageState.current.settings = { ...defaultSettings(), ...collageState.current.settings, ...patch };
  if (patch.layout && patch.layout !== "free") {
    collageState.current.items.forEach((item) => {
      item.x = 0;
      item.y = 0;
      item.w = 0;
      item.h = 0;
    });
  }
  renderInspector();
  scheduleCanvasRender();
  scheduleSave();
}

function scheduleSave() {
  window.clearTimeout(collageState.dirtyTimer);
  collageState.dirtyTimer = window.setTimeout(() => saveCurrentGroup(false), 1200);
}

async function saveCurrentGroup(explicit) {
  const group = collageState.current;
  if (!group) {
    return;
  }
  window.clearTimeout(collageState.dirtyTimer);
  const saveSeq = ++collageState.saveSeq;
  setStatus(explicit ? "正在保存并更新缓存..." : "正在更新缓存...");
  const data = await fetchJson(`/api/collage/groups/${encodeURIComponent(group.id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: group.name,
      settings: group.settings,
      items: group.items.map(({ id, path, x, y, w, h }) => ({ id, path, x, y, w, h })),
    }),
  });
  if (saveSeq !== collageState.saveSeq || collageState.current?.id !== data.group.id) {
    return;
  }
  replaceGroup(data.group);
  collageState.current = data.group;
  renderGroups();
  renderInspector();
  setStatus("缓存已更新。");
}

function replaceGroup(next) {
  const index = collageState.groups.findIndex((group) => group.id === next.id);
  if (index >= 0) {
    collageState.groups.splice(index, 1, next);
  } else {
    collageState.groups.unshift(next);
  }
}

async function removePhoto(itemId) {
  const group = collageState.current;
  if (!group || !itemId) {
    return;
  }
  group.items = group.items.filter((item) => item.id !== itemId);
  collageState.selectedItemId = group.items[0]?.id || "";
  renderCanvas();
  renderPhotos();
  renderInspector();
  await saveCurrentGroup(false);
}

async function addSelectedPoolToGroup() {
  await addPathsToCurrentGroup(Array.from(collageState.selectedPoolPaths));
  collageState.selectedPoolPaths.clear();
  renderPool();
}

async function addPathsToCurrentGroup(paths) {
  if (!paths.length) {
    return;
  }
  const group = collageState.current || await createGroupForIncomingPhotos();
  setStatus(`正在加入 ${paths.length} 张照片...`);
  const data = await fetchJson(`/api/collage/groups/${encodeURIComponent(group.id)}/items`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paths }),
  });
  replaceGroup(data.group);
  selectGroup(data.group);
  setStatus("已加入当前工作组。");
}

async function createGroupForIncomingPhotos() {
  setStatus("正在新建拼图工作组...");
  const data = await fetchJson("/api/collage/groups", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paths: [] }),
  });
  collageState.groups.unshift(data.group);
  selectGroup(data.group);
  return data.group;
}

async function openLibraryBrowser() {
  collageState.librarySelectedPaths.clear();
  libraryDialog.showModal();
  await loadLibrary("", "");
}

async function loadLibrary(root, folder) {
  const params = new URLSearchParams();
  if (root) {
    params.set("root", root);
  }
  if (folder) {
    params.set("folder", folder);
  }
  const data = await fetchJson(`/api/collage/library?${params.toString()}`, { cache: "no-store" });
  collageState.libraryRoot = data.root || "";
  collageState.libraryFolder = data.folder || "";
  collageState.libraryParent = data.parent || "";
  renderLibrary(data.entries || []);
}

function renderLibrary(entries) {
  libraryGrid.innerHTML = "";
  libraryPath.textContent = collageState.libraryRoot
    ? `${collageState.libraryRoot}${collageState.libraryFolder ? `/${collageState.libraryFolder}` : ""}`
    : "根目录";
  libraryBackBtn.disabled = !collageState.libraryRoot;
  libraryAddBtn.disabled = collageState.librarySelectedPaths.size === 0;
  if (!entries.length) {
    const empty = document.createElement("div");
    empty.className = "collage-empty";
    empty.textContent = "这里没有可添加的照片。";
    libraryGrid.append(empty);
    return;
  }
  entries.forEach((entry) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = `collage-library-item ${entry.type}`;
    item.classList.toggle("selected", collageState.librarySelectedPaths.has(entry.path));
    if (entry.type === "folder") {
      item.innerHTML = `<span class="collage-folder-icon">□</span><span>${escapeHtml(entry.name)}</span>`;
      item.addEventListener("click", () => {
        if (entry.root && !collageState.libraryRoot) {
          loadLibrary(entry.root, "");
        } else {
          loadLibrary(entry.root || collageState.libraryRoot, entry.folder || entry.path.split("/").slice(1).join("/"));
        }
      });
      libraryGrid.append(item);
      return;
    }
    const img = document.createElement("img");
    img.src = entry.thumbUrl;
    img.alt = entry.name;
    const check = document.createElement("span");
    check.className = "collage-library-check";
    check.textContent = collageState.librarySelectedPaths.has(entry.path) ? "✓" : "";
    const name = document.createElement("span");
    name.textContent = entry.name;
    item.append(img, check, name);
    item.addEventListener("click", () => {
      if (collageState.librarySelectedPaths.has(entry.path)) {
        collageState.librarySelectedPaths.delete(entry.path);
      } else {
        collageState.librarySelectedPaths.add(entry.path);
      }
      renderLibrary(entries);
    });
    libraryGrid.append(item);
  });
}

function navigateLibraryUp() {
  if (!collageState.libraryRoot) {
    return;
  }
  if (!collageState.libraryFolder) {
    loadLibrary("", "");
    return;
  }
  loadLibrary(collageState.libraryRoot, collageState.libraryParent);
}

async function addSelectedLibraryPhotos() {
  const paths = Array.from(collageState.librarySelectedPaths);
  await addPathsToCurrentGroup(paths);
  libraryDialog.close();
}

function startDrag(event) {
  if (collageState.current?.settings?.layout !== "free") {
    return;
  }
  const frame = event.currentTarget;
  const item = collageState.current.items.find((entry) => entry.id === frame.dataset.itemId);
  if (!item) {
    return;
  }
  event.preventDefault();
  frame.setPointerCapture(event.pointerId);
  frame.classList.add("dragging");
  selectPhoto(item.id, { renderCanvas: false });
  collageState.dragging = {
    item,
    frame,
    resize: Boolean(event.target.dataset.resize),
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    x: item.x,
    y: item.y,
    w: item.w,
    h: item.h,
    scale: collageState.canvasScale || canvasScale(collageState.current.settings),
    lastX: item.x,
    lastY: item.y,
    lastW: item.w,
    lastH: item.h,
  };
}

function dragSelectedItem(event) {
  const drag = collageState.dragging;
  if (!drag || drag.pointerId !== event.pointerId) {
    return;
  }
  const settings = collageState.current.settings;
  const dx = (event.clientX - drag.startX) / drag.scale;
  const dy = (event.clientY - drag.startY) / drag.scale;
  if (drag.resize) {
    drag.item.w = Math.max(80, Math.min(settings.width - drag.item.x, Math.round(drag.w + dx)));
    drag.item.h = Math.max(80, Math.min(settings.height - drag.item.y, Math.round(drag.h + dy)));
  } else {
    drag.item.x = Math.max(0, Math.min(settings.width - drag.item.w, Math.round(drag.x + dx)));
    drag.item.y = Math.max(0, Math.min(settings.height - drag.item.h, Math.round(drag.y + dy)));
  }
  updateDraggingFrame(drag);
}

function finishDrag(event) {
  const drag = collageState.dragging;
  if (!drag || drag.pointerId !== event.pointerId) {
    return;
  }
  collageState.dragging = null;
  updateFrameNode(drag.frame, drag.item, drag.scale);
  drag.frame?.classList.remove("dragging");
  scheduleSave();
}

function selectPhoto(itemId, options = {}) {
  collageState.selectedItemId = itemId;
  updateSelectedFrameClasses();
  renderPhotos();
  renderInspector();
}

function updateSelectedFrameClasses() {
  canvas.querySelectorAll(".collage-frame").forEach((frame) => {
    frame.classList.toggle("selected", frame.dataset.itemId === collageState.selectedItemId);
  });
}

function updateFrameNode(frame, item, scale = collageState.canvasScale || 1) {
  if (!frame) {
    return;
  }
  frame.style.transform = "";
  frame.style.left = `${item.x * scale}px`;
  frame.style.top = `${item.y * scale}px`;
  frame.style.width = `${item.w * scale}px`;
  frame.style.height = `${item.h * scale}px`;
}

function updateDraggingFrame(drag) {
  if (!drag.frame) {
    return;
  }
  if (drag.resize) {
    drag.frame.style.width = `${drag.item.w * drag.scale}px`;
    drag.frame.style.height = `${drag.item.h * drag.scale}px`;
    return;
  }
  const dx = (drag.item.x - drag.x) * drag.scale;
  const dy = (drag.item.y - drag.y) * drag.scale;
  drag.frame.style.transform = `translate3d(${dx}px, ${dy}px, 0)`;
}

function scheduleCanvasRender() {
  if (collageState.canvasRenderFrame) {
    return;
  }
  collageState.canvasRenderFrame = window.requestAnimationFrame(() => {
    collageState.canvasRenderFrame = 0;
    renderCanvas();
  });
}

function editingImageUrl(item) {
  if (item.thumbUrl) {
    return item.thumbUrl.replace("mode=small", "mode=large");
  }
  return item.imageUrl;
}

function setEditingImageSource(img, item) {
  img.onerror = () => {
    if (img.dataset.fallback === "1" || !item.imageUrl) {
      return;
    }
    img.dataset.fallback = "1";
    img.src = item.imageUrl;
  };
  img.src = editingImageUrl(item);
}

function layoutBoxes(settings, items) {
  if (settings.layout === "free") {
    return items.map((item, index) => {
      if (item.w > 0 && item.h > 0) {
        return { x: item.x, y: item.y, w: item.w, h: item.h };
      }
      const fallback = gridBoxes({ ...settings, columns: Math.min(3, Math.max(1, items.length)) }, items.length)[index];
      return fallback;
    });
  }
  if (settings.layout === "hero") {
    return heroBoxes(settings, items.length);
  }
  if (settings.layout === "film") {
    return filmBoxes(settings, items.length);
  }
  if (settings.layout === "masonry") {
    return masonryBoxes(settings, items);
  }
  return gridBoxes(settings, items.length);
}

function gridBoxes(settings, count) {
  const columns = Math.min(settings.columns || 3, Math.max(1, count));
  const rows = Math.ceil(count / columns);
  const pad = settings.padding || 0;
  const gap = settings.gap || 0;
  const cellW = (settings.width - pad * 2 - gap * (columns - 1)) / columns;
  const cellH = (settings.height - pad * 2 - gap * (rows - 1)) / rows;
  return Array.from({ length: count }, (_, index) => ({
    x: pad + (index % columns) * (cellW + gap),
    y: pad + Math.floor(index / columns) * (cellH + gap),
    w: cellW,
    h: cellH,
  }));
}

function heroBoxes(settings, count) {
  if (count <= 1) {
    return [{ x: settings.padding, y: settings.padding, w: settings.width - settings.padding * 2, h: settings.height - settings.padding * 2 }];
  }
  const pad = settings.padding;
  const gap = settings.gap;
  const sideW = Math.max(220, (settings.width - pad * 2 - gap) * 0.32);
  const heroW = settings.width - pad * 2 - gap - sideW;
  const boxes = [{ x: pad, y: pad, w: heroW, h: settings.height - pad * 2 }];
  const sideH = (settings.height - pad * 2 - gap * (count - 2)) / (count - 1);
  for (let index = 0; index < count - 1; index += 1) {
    boxes.push({ x: pad + heroW + gap, y: pad + index * (sideH + gap), w: sideW, h: sideH });
  }
  return boxes;
}

function filmBoxes(settings, count) {
  const pad = settings.padding;
  const gap = settings.gap;
  const cellW = (settings.width - pad * 2 - gap * (count - 1)) / Math.max(1, count);
  const height = settings.height - pad * 2;
  return Array.from({ length: count }, (_, index) => {
    const stagger = height * 0.08 * (index % 2 ? 1 : -1);
    return { x: pad + index * (cellW + gap), y: pad + Math.max(0, stagger), w: cellW, h: height - Math.abs(stagger) };
  });
}

function masonryBoxes(settings, items) {
  const columns = Math.min(settings.columns || 3, Math.max(1, items.length));
  const pad = settings.padding;
  const gap = settings.gap;
  const colW = (settings.width - pad * 2 - gap * (columns - 1)) / columns;
  const colY = Array.from({ length: columns }, () => pad);
  return items.map((item) => {
    const ratio = Math.max(0.45, Math.min(1.8, (item.height || 3) / (item.width || 4)));
    const h = Math.max(180, Math.min(settings.height * 0.62, colW * ratio));
    const col = colY.indexOf(Math.min(...colY));
    const box = { x: pad + col * (colW + gap), y: colY[col], w: colW, h };
    colY[col] += h + gap;
    return box;
  });
}

function defaultSettings() {
  return {
    layout: "grid",
    width: 2400,
    height: 1600,
    gap: 24,
    padding: 48,
    background: "#f7f3ea",
    fit: "cover",
    radius: 18,
    shadow: true,
    columns: 3,
  };
}

function setStatus(message) {
  statusNode.textContent = message || "";
}

function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}
