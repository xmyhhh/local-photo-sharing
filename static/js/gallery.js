async function loadConfig() {
  const config = await fetchJson("/api/config");
  state.roots = config.roots || [];
  state.rootId = config.defaultRootId || state.roots[0]?.id || "root1";
  renderRootSelector();
  rootPath.textContent = state.roots.map((root) => `${root.id}: ${root.path}`).join(" | ");
}

async function loadFolder(folder = state.folder) {
  const generation = state.filterGeneration;
  state.nextCursor = null;
  const params = new URLSearchParams();
  params.set("root", state.rootId);
  params.set("folder", folder);
  params.set("limit", "80");
  state.filters.ratings.forEach((rating) => params.append("rating", rating));
  if (state.filters.dateFrom) {
    params.set("date_from", state.filters.dateFrom);
  }
  if (state.filters.dateTo) {
    params.set("date_to", state.filters.dateTo);
  }
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
  renderBreadcrumb();
  renderGrid();
  if (data.indexing && state.filters.ratings.length) {
    scheduleFilterRefresh(generation);
  }
}

function navigateFolder(folder) {
  const target = normalizeFolderPath(folder || "");
  if (target !== state.folder) {
    resetFiltersForFolderNavigation();
  }
  loadFolder(target);
}

function normalizeFolderPath(folder) {
  const prefix = `${state.rootId}/`;
  if (folder === state.rootId) {
    return "";
  }
  if (folder.startsWith(prefix)) {
    return folder.slice(prefix.length);
  }
  return folder;
}

function qualifyPath(path) {
  if (!path) {
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

function renderRootSelector() {
  const host = document.querySelector("#rootSelector");
  if (!host) {
    return;
  }
  host.innerHTML = "";
  state.roots.forEach((root) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = root.id === state.rootId ? "active" : "";
    button.textContent = root.id;
    button.addEventListener("click", () => {
      state.rootId = root.id;
      renderRootSelector();
      loadFolder("");
    });
    host.append(button);
  });
}

async function loadMoreEntries() {
  if (state.loadingMore || state.nextCursor === null) {
    return;
  }
  state.loadingMore = true;
  const generation = state.filterGeneration;
  const params = new URLSearchParams();
  params.set("root", state.rootId);
  params.set("folder", state.folder);
  params.set("cursor", String(state.nextCursor));
  params.set("limit", "80");
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
  } finally {
    state.loadingMore = false;
  }
}

function renderBreadcrumb() {
  breadcrumb.innerHTML = "";
  const root = document.createElement("button");
  root.type = "button";
  root.textContent = "根目录";
  root.addEventListener("click", () => navigateFolder(""));
  breadcrumb.append(root);

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

  backBtn.disabled = !state.folder;
}

function renderGrid() {
  clearVisibleWorkScan();
  clearThumbTimers();
  clearRatingTimers();
  resetThumbObserver();
  resetRatingObserver();
  grid.innerHTML = "";
  grid.className = `grid thumb-${state.thumbMode}`;
  updateEmptyState();

  state.entries.forEach((entry) => {
    entry.path = qualifyPath(entry.path);
    appendGridEntry(entry);
  });
  scheduleVisibleWorkScan();
  scheduleLoadMoreIfNeeded();
}
