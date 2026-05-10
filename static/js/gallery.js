async function loadConfig() {
  const config = await fetchJson("/api/config");
  state.roots = config.roots || [];
  state.rootId = "";
  applyThumbnailQueueLimits(config.thumbnailQueueLimits);
}

function applyThumbnailQueueLimits(limits) {
  if (!limits || typeof limits !== "object") {
    return;
  }
  THUMB_MODES.forEach((mode) => {
    if (limits[mode] === undefined) {
      return;
    }
    const value = Number.parseInt(limits[mode], 10);
    if (Number.isFinite(value)) {
      THUMB_QUEUE_LIMITS[mode] = Math.max(10, value);
    }
  });
}

async function loadFolder(folder = state.folder) {
  const generation = state.filterGeneration;
  const targetFolder = normalizeFolderPath(folder || "");
  showFolderLoading(targetFolder);
  state.nextCursor = null;
  const params = new URLSearchParams();
  if (state.rootId) {
    params.set("root", state.rootId);
  }
  params.set("folder", targetFolder);
  params.set("limit", String(PHOTO_PAGE_LIMIT));
  state.filters.ratings.forEach((rating) => params.append("rating", rating));
  if (state.filters.dateFrom) {
    params.set("date_from", state.filters.dateFrom);
  }
  if (state.filters.dateTo) {
    params.set("date_to", state.filters.dateTo);
  }
  try {
    const data = await fetchJson(`/api/photos?${params.toString()}`);
    if (generation !== state.filterGeneration) {
      return;
    }
    clearFilterRefreshTimer();
    state.folder = data.folder;
    state.parent = data.parent;
    state.entries = data.entries;
    state.nextCursor = data.nextCursor;
    state.indexing = Boolean(data.indexing);
    state.loadingFolder = false;
    renderBreadcrumb();
    renderGrid();
    if (data.indexing && state.filters.ratings.length) {
      scheduleFilterRefresh(generation);
    }
    updateGalleryHistoryState();
  } catch (error) {
    if (generation !== state.filterGeneration) {
      return;
    }
    state.loadingFolder = false;
    state.entries = [];
    state.nextCursor = null;
    state.indexing = false;
    updateEmptyState(error.message || "加载文件夹失败。");
  }
}

function navigateFolder(folder) {
  const target = normalizeFolderPath(folder || "");
  if (target !== state.folder) {
    resetFiltersForFolderNavigation();
    window.scrollTo({ top: 0, behavior: "auto" });
  }
  loadFolder(target);
}

function armGalleryHistory() {
  if (state.galleryHistoryArmed) {
    return;
  }
  window.history.replaceState({ galleryBase: true }, "", window.location.href);
  window.history.pushState({ gallery: true, folder: state.folder || "" }, "", window.location.href);
  state.galleryHistoryArmed = true;
}

function updateGalleryHistoryState() {
  if (!state.galleryHistoryArmed || state.viewerHistoryArmed || state.handlingGalleryBack) {
    return;
  }
  window.history.replaceState({ gallery: true, folder: state.folder || "" }, "", window.location.href);
}

function handleGalleryBackNavigation() {
  if (viewer.open || bracketDialog.open) {
    return false;
  }
  if (!state.folder) {
    if (state.rootId) {
      navigateVirtualRoot();
      window.history.pushState({ gallery: true, folder: "" }, "", window.location.href);
      return true;
    }
    return false;
  }
  state.handlingGalleryBack = true;
  navigateFolder(state.parent);
  window.history.pushState({ gallery: true, folder: state.parent || "" }, "", window.location.href);
  window.setTimeout(() => {
    state.handlingGalleryBack = false;
  }, 0);
  return true;
}

function normalizeFolderPath(folder) {
  if (!state.rootId) {
    return normalizeVirtualRootPath(folder);
  }
  const prefix = `${state.rootId}/`;
  if (folder === state.rootId) {
    return "";
  }
  if (folder.startsWith(prefix)) {
    return folder.slice(prefix.length);
  }
  return folder;
}

function normalizeVirtualRootPath(folder) {
  const normalized = folder.replace(/^\/+/, "");
  const root = state.roots.find((item) => item.id === normalized || normalized.startsWith(`${item.id}/`));
  if (!root) {
    return normalized;
  }
  state.rootId = root.id;
  return normalized === root.id ? "" : normalized.slice(root.id.length + 1);
}

function qualifyPath(path) {
  if (!path) {
    return path;
  }
  if (!state.rootId) {
    return path;
  }
  if (path.startsWith(`${state.rootId}/`)) {
    return path;
  }
  if (path.startsWith("/")) {
    return path.slice(1);
  }
  return `${state.rootId}/${path}`;
}

async function loadMoreEntries() {
  if (state.loadingMore || state.nextCursor === null) {
    return;
  }
  state.loadingMore = true;
  const generation = state.filterGeneration;
  const params = new URLSearchParams();
  if (state.rootId) {
    params.set("root", state.rootId);
  }
  params.set("folder", state.folder);
  params.set("cursor", String(state.nextCursor));
  params.set("limit", String(PHOTO_PAGE_LIMIT));
  state.filters.ratings.forEach((rating) => params.append("rating", rating));
  if (state.filters.dateFrom) {
    params.set("date_from", state.filters.dateFrom);
  }
  if (state.filters.dateTo) {
    params.set("date_to", state.filters.dateTo);
  }
  try {
    const data = await fetchJson(`/api/photos?${params.toString()}`);
    if (generation !== state.filterGeneration) {
      return;
    }
    state.nextCursor = data.nextCursor;
    state.indexing = Boolean(data.indexing);
    data.entries.forEach((entry) => {
      entry.path = qualifyPath(entry.path);
      if (state.entries.some((existing) => existing.path === entry.path)) {
        return;
      }
      state.entries.push(entry);
      appendGridEntry(entry);
    });
    if (data.indexing && state.filters.ratings.length) {
      scheduleFilterRefresh(generation);
    }
    scheduleLoadMoreIfNeeded();
  } finally {
    state.loadingMore = false;
  }
}

function renderBreadcrumb() {
  breadcrumb.innerHTML = "";
  const root = document.createElement("button");
  root.type = "button";
  root.textContent = "根目录";
  root.addEventListener("click", () => navigateVirtualRoot());
  breadcrumb.append(root);

  if (!state.rootId) {
    backBtn.disabled = true;
    return;
  }

  const rootInfo = state.roots.find((item) => item.id === state.rootId);
  const sep = document.createElement("span");
  sep.textContent = "/";
  breadcrumb.append(sep);
  const rootBtn = document.createElement("button");
  rootBtn.type = "button";
  rootBtn.textContent = rootInfo?.name || rootDisplayName(rootInfo) || state.rootId;
  rootBtn.addEventListener("click", () => loadFolder(""));
  breadcrumb.append(rootBtn);

  const parts = state.folder ? state.folder.split("/") : [];
  let current = "";
  parts.forEach((part) => {
    const sep = document.createElement("span");
    sep.textContent = "/";
    breadcrumb.append(sep);

    current = current ? `${current}/${part}` : part;
    const pathAtLevel = current;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = part;
    btn.addEventListener("click", () => navigateFolder(pathAtLevel));
    breadcrumb.append(btn);
  });

  backBtn.disabled = false;
}

function navigateVirtualRoot() {
  state.rootId = "";
  navigateFolder("");
}

function rootDisplayName(root) {
  if (!root?.path) {
    return "";
  }
  return root.path.replace(/[\\/]+$/, "").split(/[\\/]/).pop();
}

function renderGrid() {
  clearVisibleWorkScan();
  clearThumbTimers();
  clearRatingTimers();
  resetThumbObserver();
  resetRatingObserver();
  grid.innerHTML = "";
  grid.className = `grid thumb-${state.thumbMode}`;
  grid.classList.toggle("compact-mode", state.compactMode);
  compactToggleBtn.textContent = state.compactMode ? "展开" : "精简";
  updateEmptyState();

  state.entries.forEach((entry) => {
    entry.path = qualifyPath(entry.path);
    appendGridEntry(entry);
  });
  scheduleVisibleWorkScan();
  scheduleLoadMoreIfNeeded();
}

function showFolderLoading(targetFolder) {
  clearVisibleWorkScan();
  clearThumbTimers();
  clearRatingTimers();
  resetThumbObserver();
  resetRatingObserver();
  state.loadingFolder = true;
  state.folder = targetFolder;
  state.parent = parentFolderPath(targetFolder);
  state.entries = [];
  state.indexing = false;
  grid.innerHTML = "";
  grid.className = `grid thumb-${state.thumbMode}`;
  grid.classList.toggle("compact-mode", state.compactMode);
  compactToggleBtn.textContent = state.compactMode ? "展开" : "精简";
  renderBreadcrumb();
  updateEmptyState();
  updateGalleryHistoryState();
}

function appendGridEntry(entry) {
  const tile = createGridTile(entry);
  grid.append(tile.element);
  if (tile.thumbPayload) {
    observeThumbnail(tile.thumbPayload.entry, tile.thumbPayload.img, tile.thumbPayload.spinner);
  }
  if (tile.ratingPayload) {
    observeRating(tile.ratingPayload.entry, tile.ratingPayload.ratingWrap);
  }
  updateEmptyState();
  scheduleVisibleWorkScan();
}

function updateEmptyState(message = "") {
  if (state.entries.length > 0) {
    emptyState.hidden = true;
    return;
  }
  emptyState.hidden = false;
  emptyState.classList.toggle("loading", state.loadingFolder);
  if (state.loadingFolder) {
    emptyState.innerHTML = '<span class="spinner inline-spinner" aria-hidden="true"></span><span>正在打开文件夹...</span>';
  } else if (message) {
    emptyState.textContent = message;
  } else if (state.filters.ratings.length && state.indexing) {
    emptyState.textContent = "正在执行筛选...";
  } else if (state.filters.ratings.length) {
    emptyState.textContent = "没有找到满足筛选条件的媒体文件。";
  } else {
    emptyState.textContent = "当前文件夹没有图片、视频或子文件夹。";
  }
}

function parentFolderPath(folder) {
  if (!folder) {
    return "";
  }
  const parts = folder.split("/").filter(Boolean);
  parts.pop();
  return parts.join("/");
}

function createGridTile(entry) {
  const tile = document.createElement("article");
  tile.className = "tile";
  if (entry.type !== "folder") {
    tile.classList.add("media-tile");
  }
  tile.classList.add(`${entry.type}-tile`);
  tile.dataset.path = entry.path;
  let thumbPayload = null;
  let ratingPayload = null;

  const button = document.createElement("button");
  button.className = "tile-button";
  button.type = "button";
  button.title = entry.name;

  if (entry.type === "folder") {
    const icon = document.createElement("div");
    icon.className = "folder-icon";
    icon.innerHTML = `
      <svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">
        <path d="M8 18a6 6 0 0 1 6-6h12l6 6h18a6 6 0 0 1 6 6v4H8z"></path>
        <path d="M8 24h48v20a8 8 0 0 1-8 8H16a8 8 0 0 1-8-8z"></path>
      </svg>
    `;
    button.append(icon);
    button.addEventListener("click", () => navigateFolder(entry.path));
    button.addEventListener("contextmenu", (event) => openFolderContextMenu(event, entry));
  } else {
    const holder = document.createElement("div");
    holder.className = "thumb-holder";
    const spinner = document.createElement("div");
    spinner.className = "spinner";
    spinner.setAttribute("aria-label", "正在生成预览");
    let img = null;
    if (entry.type === "video") {
      const videoBadge = document.createElement("div");
      videoBadge.className = "media-badge";
      videoBadge.textContent = "VIDEO";
      const icon = document.createElement("div");
      icon.className = "video-thumb";
      icon.textContent = "▶";
      spinner.hidden = true;
      holder.append(videoBadge, icon);
    } else {
      img = document.createElement("img");
      img.className = "thumb";
      img.loading = "lazy";
      img.decoding = "async";
      img.alt = entry.name;
      holder.append(spinner, img);
      if (entry.isLive) {
        const liveBadge = document.createElement("div");
        liveBadge.className = "media-badge live-badge";
        liveBadge.textContent = "LIVE";
        holder.append(liveBadge);
      }
    }
    button.append(holder);
    if (img) {
      thumbPayload = { entry, img, spinner };
    }
    button.addEventListener("click", () => openViewer(entry));
  }

  const meta = document.createElement("div");
  meta.className = "meta";
  const name = document.createElement("div");
  name.className = "name";
  name.textContent = entry.name;
  meta.append(name);

  if (entry.type === "photo") {
    const ratingWrap = createRating(entry, false);
    meta.append(ratingWrap);
    ratingPayload = { entry, ratingWrap };
  } else if (entry.type === "video") {
    const kind = document.createElement("div");
    kind.className = "folder-count";
    kind.textContent = "视频";
    meta.append(kind);
  } else if (entry.type === "folder") {
    const count = document.createElement("div");
    count.className = "folder-count";
    count.textContent = "文件夹";
    meta.append(count);
  }

  tile.append(button, meta);
  return { element: tile, thumbPayload, ratingPayload };
}
