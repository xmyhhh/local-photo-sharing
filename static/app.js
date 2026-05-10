const state = {
  folder: "",
  parent: "",
  entries: [],
  currentPhoto: null,
  zoom: 1,
  panX: 0,
  panY: 0,
  isDragging: false,
  dragStart: null,
  thumbTimers: new Map(),
  thumbQueue: [],
  thumbQueued: new Set(),
  thumbActive: 0,
  thumbControllers: new Map(),
  ratingTimers: new Map(),
  ratingObserver: null,
  ratingQueue: [],
  ratingQueued: new Set(),
  ratingActive: 0,
  filterGeneration: 0,
  filterRefreshTimer: null,
  previewTimer: null,
  originalCache: new Map(),
  originalCacheBytes: 0,
  originalFetches: new Map(),
  originalPrefetchQueue: [],
  originalPrefetchActive: 0,
  thumbObserver: null,
  thumbMode: getStoredThumbMode(),
  activeTouches: new Map(),
  pinchDistance: 0,
  pinchZoom: 1,
  swipeStart: null,
  swipeMoved: false,
  lastTapTime: 0,
  visibleScanTimer: null,
  contextFolder: null,
  filters: {
    ratings: [],
    dateFrom: "",
    dateTo: "",
  },
};

const ORIGINAL_CACHE_LIMIT = 1024 * 1024 * 1024;
const ORIGINAL_PREFETCH_CONCURRENCY = 2;
const ORIGINAL_PREFETCH_QUEUE_LIMIT = 25;
const THUMB_LOAD_CONCURRENCY = 6;
const THUMB_QUEUE_LIMIT = 50;
const RATING_STATUS_CONCURRENCY = 3;
const RATING_QUEUE_LIMIT = 50;

const grid = document.querySelector("#grid");
const emptyState = document.querySelector("#emptyState");
const breadcrumb = document.querySelector("#breadcrumb");
const rootPath = document.querySelector("#rootPath");
const backBtn = document.querySelector("#backBtn");
const refreshBtn = document.querySelector("#refreshBtn");
const ratingFilterBtn = document.querySelector("#ratingFilterBtn");
const ratingFilterMenu = document.querySelector("#ratingFilterMenu");
const ratingFilterInputs = Array.from(document.querySelectorAll("#ratingFilterMenu input"));
const dateFromFilter = document.querySelector("#dateFromFilter");
const dateToFilter = document.querySelector("#dateToFilter");
const thumbModeSelect = document.querySelector("#thumbModeSelect");
const clearFiltersBtn = document.querySelector("#clearFiltersBtn");
const viewer = document.querySelector("#viewer");
const viewerTitle = document.querySelector("#viewerTitle");
const viewerImage = document.querySelector("#viewerImage");
const viewerRating = document.querySelector("#viewerRating");
const imageStage = document.querySelector("#imageStage");
const zoomOutBtn = document.querySelector("#zoomOutBtn");
const zoomResetBtn = document.querySelector("#zoomResetBtn");
const zoomInBtn = document.querySelector("#zoomInBtn");
const downloadBtn = document.querySelector("#downloadBtn");
const deleteBtn = document.querySelector("#deleteBtn");
const closeBtn = document.querySelector("#closeBtn");
const prevBtn = document.querySelector("#prevBtn");
const nextBtn = document.querySelector("#nextBtn");
const deleteDialog = document.querySelector("#deleteDialog");
const deleteDialogPath = document.querySelector("#deleteDialogPath");
const cancelDeleteBtn = document.querySelector("#cancelDeleteBtn");
const confirmDeleteBtn = document.querySelector("#confirmDeleteBtn");
const folderContextMenu = document.querySelector("#folderContextMenu");
const detectBracketsBtn = document.querySelector("#detectBracketsBtn");
const bracketDialog = document.querySelector("#bracketDialog");
const bracketDialogPath = document.querySelector("#bracketDialogPath");
const bracketStatus = document.querySelector("#bracketStatus");
const bracketResults = document.querySelector("#bracketResults");
const closeBracketDialogBtn = document.querySelector("#closeBracketDialogBtn");
const isAppleMobileBrowser = /iPhone|iPad|iPod/i.test(navigator.userAgent);

async function loadConfig() {
  const config = await fetchJson("/api/config");
  rootPath.textContent = config.root;
}

async function loadFolder(folder = state.folder) {
  const generation = state.filterGeneration;
  const params = new URLSearchParams();
  params.set("folder", folder);
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
  renderBreadcrumb();
  renderGrid();
  if (data.indexing && state.filters.ratings.length) {
    scheduleFilterRefresh(generation);
  }
}

function renderBreadcrumb() {
  breadcrumb.innerHTML = "";
  const root = document.createElement("button");
  root.type = "button";
  root.textContent = "根目录";
  root.addEventListener("click", () => loadFolder(""));
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
    btn.addEventListener("click", () => loadFolder(pathAtLevel));
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
  emptyState.hidden = state.entries.length > 0;

  state.entries.forEach((entry) => {
    appendGridEntry(entry);
  });
  scheduleVisibleWorkScan();
}

function scheduleFilterRefresh(generation) {
  clearFilterRefreshTimer();
  state.filterRefreshTimer = window.setTimeout(() => {
    state.filterRefreshTimer = null;
    if (generation === state.filterGeneration) {
      loadFolder(state.folder);
    }
  }, 800);
}

function clearFilterRefreshTimer() {
  if (state.filterRefreshTimer) {
    window.clearTimeout(state.filterRefreshTimer);
    state.filterRefreshTimer = null;
  }
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
  emptyState.hidden = state.entries.length > 0;
  scheduleVisibleWorkScan();
}

function createGridTile(entry) {
  const tile = document.createElement("article");
  tile.className = "tile";
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
    icon.textContent = "DIR";
    button.append(icon);
    button.addEventListener("click", () => loadFolder(entry.path));
    button.addEventListener("contextmenu", (event) => openFolderContextMenu(event, entry));
  } else {
    const holder = document.createElement("div");
    holder.className = "thumb-holder";
    const spinner = document.createElement("div");
    spinner.className = "spinner";
    spinner.setAttribute("aria-label", "正在生成预览");
    const img = document.createElement("img");
    img.className = "thumb";
    img.loading = "lazy";
    img.decoding = "async";
    img.alt = entry.name;
    holder.append(spinner, img);
    button.append(holder);
    thumbPayload = { entry, img, spinner };
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
  }

  tile.append(button, meta);
  return { element: tile, thumbPayload, ratingPayload };
}

function observeRating(entry, ratingWrap) {
  if (!entry.ratingPending) {
    return;
  }
  if (!state.ratingObserver) {
    state.ratingObserver = new IntersectionObserver(
      (items) => {
        items.forEach((item) => {
          if (!item.isIntersecting) {
            return;
          }
          const payload = item.target.__ratingPayload;
          if (payload) {
            queueEmbeddedRating(payload.entry, payload.ratingWrap);
          }
        });
      },
      { rootMargin: "180px 0px" },
    );
  }
  ratingWrap.__ratingPayload = { entry, ratingWrap };
  state.ratingObserver.observe(ratingWrap);
  if (isNearViewport(ratingWrap, 220)) {
    queueEmbeddedRating(entry, ratingWrap);
  }
}

function queueEmbeddedRating(entry, ratingWrap, attempt = 0) {
  if (!entry.ratingPending) {
    return;
  }
  if (!ratingWrap.isConnected) {
    return;
  }
  const key = entry.path;
  if (state.ratingQueued.has(key)) {
    state.ratingQueue = state.ratingQueue.filter((item) => item.key !== key);
  }
  state.ratingQueued.add(key);
  state.ratingQueue.unshift({ entry, ratingWrap, attempt, key });
  trimRatingQueue();
  runRatingQueue();
}

function trimRatingQueue() {
  while (state.ratingQueue.length > RATING_QUEUE_LIMIT) {
    const dropped = state.ratingQueue.pop();
    if (dropped) {
      state.ratingQueued.delete(dropped.key);
    }
  }
}

function runRatingQueue() {
  while (state.ratingActive < RATING_STATUS_CONCURRENCY && state.ratingQueue.length > 0) {
    const payload = state.ratingQueue.shift();
    state.ratingQueued.delete(payload.key);
    if (!payload.entry.ratingPending || !payload.ratingWrap.isConnected) {
      continue;
    }
    state.ratingActive += 1;
    loadEmbeddedRating(payload.entry, payload.ratingWrap, payload.attempt)
      .catch(() => null)
      .finally(() => {
        state.ratingActive = Math.max(0, state.ratingActive - 1);
        runRatingQueue();
      });
  }
}

async function loadEmbeddedRating(entry, ratingWrap, attempt = 0) {
  if (!entry.ratingPending || !ratingWrap.isConnected) {
    return;
  }
  try {
    const response = await fetch(`/api/rating-status/${encodePath(entry.path)}`, { cache: "no-store" });
    const data = await response.json();
    if (response.status === 200) {
      if (!ratingWrap.isConnected) {
        return;
      }
      entry.rating = data.rating;
      entry.ratingPending = false;
      ratingWrap.replaceWith(createRating(entry, false));
      if (state.currentPhoto?.path === entry.path) {
        state.currentPhoto.rating = data.rating;
        state.currentPhoto.ratingPending = false;
        renderViewerRating();
      }
      return;
    }
    if (response.status !== 202) {
      entry.ratingPending = false;
      return;
    }
  } catch {
    scheduleRatingRetry(entry, ratingWrap, attempt);
    return;
  }

  scheduleRatingRetry(entry, ratingWrap, attempt);
}

function scheduleRatingRetry(entry, ratingWrap, attempt) {
  if (!entry.ratingPending || !ratingWrap.isConnected || attempt >= 12) {
    return;
  }
  const delay = Math.min(3000, 350 + attempt * 220);
  const timer = window.setTimeout(() => {
    state.ratingTimers.delete(entry.path);
    queueEmbeddedRating(entry, ratingWrap, attempt + 1);
  }, delay);
  state.ratingTimers.set(entry.path, timer);
}

function openFolderContextMenu(event, entry) {
  event.preventDefault();
  state.contextFolder = entry;
  folderContextMenu.hidden = false;
  const menuRect = folderContextMenu.getBoundingClientRect();
  const left = Math.min(event.clientX, window.innerWidth - menuRect.width - 8);
  const top = Math.min(event.clientY, window.innerHeight - menuRect.height - 8);
  folderContextMenu.style.left = `${Math.max(8, left)}px`;
  folderContextMenu.style.top = `${Math.max(8, top)}px`;
}

function closeFolderContextMenu() {
  folderContextMenu.hidden = true;
}

async function detectBracketsInContextFolder() {
  const folder = state.contextFolder;
  closeFolderContextMenu();
  if (!folder) {
    return;
  }
  bracketDialogPath.textContent = folder.path || "根目录";
  bracketStatus.textContent = "正在扫描 JPG 文件...";
  bracketResults.innerHTML = "";
  bracketDialog.showModal();

  try {
    const params = new URLSearchParams();
    params.set("folder", folder.path);
    const result = await fetchJson(`/api/bracket-detection?${params.toString()}`);
    renderBracketDetection(result);
  } catch (error) {
    bracketStatus.textContent = error.message;
  }
}

function renderBracketDetection(result) {
  bracketResults.innerHTML = "";
  if (!result.groups.length) {
    const pendingText = result.queued ? ` ${result.queued} 张照片还没有缩略图，先打开或滚动浏览该目录后再检测会更完整。` : "";
    bracketStatus.textContent = `没有发现明显的包围曝光组。${pendingText}`;
    return;
  }
  const truncatedText = result.truncated ? ` 已扫描前 ${result.scanned} 张，目录过大，结果可能不完整。` : "";
  const pendingText = result.queued ? ` ${result.queued} 张照片没有缩略图，尚未纳入本次检测。` : "";
  bracketStatus.textContent = `发现 ${result.groups.length} 组疑似包围曝光。${truncatedText}${pendingText}`;

  result.groups.forEach((group) => {
    const section = document.createElement("section");
    section.className = "bracket-group";

    const title = document.createElement("div");
    title.className = "bracket-group-title";
    const exposureText = group.exposureRangeEv === null ? "无 EXIF 曝光跨度" : `曝光跨度 ${group.exposureRangeEv} EV`;
    title.textContent = `第 ${group.id} 组 · ${group.size} 张 · 亮度跨度 ${group.brightnessRange} · 相似度 ${group.averageSimilarity} · ${exposureText}`;
    section.append(title);

    const strip = document.createElement("div");
    strip.className = "bracket-strip";
    group.photos.forEach((photo) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "bracket-photo";
      item.title = photo.path;
      const img = document.createElement("img");
      img.alt = photo.name;
      img.src = withVersion(photo.thumbUrl, photo.mtime);
      img.onerror = () => {
        img.src = `/api/image/${encodePath(photo.path)}`;
      };
      const name = document.createElement("span");
      name.className = "bracket-photo-name";
      name.textContent = photo.name;
      const info = document.createElement("span");
      info.className = "bracket-photo-info";
      info.textContent = formatBracketPhotoInfo(photo);
      item.append(img, name, info);
      item.addEventListener("click", () => {
        bracketDialog.close();
        openViewer(photoToEntry(photo));
      });
      strip.append(item);
    });
    section.append(strip);
    bracketResults.append(section);
  });
}

function formatBracketPhotoInfo(photo) {
  const exposure = photo.exposureTime ? ` · ${formatExposureTime(photo.exposureTime)}` : "";
  return `亮度 ${photo.brightness}${exposure}`;
}

function formatExposureTime(seconds) {
  if (seconds <= 0) {
    return "";
  }
  if (seconds < 1) {
    const denominator = Math.round(1 / seconds);
    return `1/${denominator}s`;
  }
  return `${seconds.toFixed(seconds >= 10 ? 0 : 1)}s`;
}

function photoToEntry(photo) {
  return {
    type: "photo",
    name: photo.name,
    path: photo.path,
    mtime: photo.mtime,
    rating: 0,
  };
}

async function loadThumbnail(entry, img, spinner, attempt = 0, mode = state.thumbMode) {
  if (!img.isConnected || mode !== state.thumbMode) {
    return;
  }
  const requestKey = `${entry.path}:${mode}:${attempt}:${Date.now()}`;
  const controller = new AbortController();
  state.thumbControllers.set(requestKey, controller);
  try {
    const response = await fetch(`/api/thumb-status/${encodePath(entry.path)}?mode=${mode}`, {
      cache: "no-store",
      signal: controller.signal,
    });
    const data = await response.json();
    if (!img.isConnected || mode !== state.thumbMode) {
      return;
    }
    if (response.status === 200) {
      img.loading = "eager";
      img.fetchPriority = "high";
      img.onload = () => {
        img.classList.add("loaded");
        spinner.hidden = true;
        entry.thumbUrl = img.src;
      };
      img.onerror = () => {
        showThumbnailFallback(entry, img, spinner);
      };
      img.src = withVersion(data.url, entry.mtime);
      if (img.complete && img.naturalWidth > 0) {
        img.classList.add("loaded");
        spinner.hidden = true;
        entry.thumbUrl = img.src;
      }
      return;
    }
    if (response.status !== 202) {
      showThumbnailFallback(entry, img, spinner);
      return;
    }
  } catch {
    if (!controller.signal.aborted) {
      scheduleThumbnailRetry(entry, img, spinner, attempt, mode);
    }
    return;
  } finally {
    state.thumbControllers.delete(requestKey);
  }

  scheduleThumbnailRetry(entry, img, spinner, attempt, mode);
}

function scheduleThumbnailRetry(entry, img, spinner, attempt, mode) {
  if (!img.isConnected || mode !== state.thumbMode) {
    return;
  }
  if (attempt >= 8) {
    showThumbnailFallback(entry, img, spinner);
    return;
  }
  const delay = Math.min(3000, 450 + attempt * 250);
  const timer = window.setTimeout(() => {
    state.thumbTimers.delete(entry.path);
    queueThumbnail(entry, img, spinner, attempt + 1);
  }, delay);
  state.thumbTimers.set(entry.path, timer);
}

function showThumbnailFallback(entry, img, spinner) {
  img.loading = "eager";
  img.fetchPriority = "high";
  img.onload = () => {
    img.classList.add("loaded");
    spinner.hidden = true;
    entry.thumbUrl = img.src;
  };
  img.onerror = () => {
    spinner.classList.add("failed");
  };
  img.src = `/api/image/${encodePath(entry.path)}`;
  if (img.complete && img.naturalWidth > 0) {
    img.classList.add("loaded");
    spinner.hidden = true;
    entry.thumbUrl = img.src;
  }
}

function getStoredThumbMode() {
  const value = window.localStorage.getItem("thumbMode");
  return ["small", "medium", "large"].includes(value) ? value : "medium";
}

function setThumbMode(mode) {
  if (!["small", "medium", "large"].includes(mode) || mode === state.thumbMode) {
    return;
  }
  state.thumbMode = mode;
  window.localStorage.setItem("thumbMode", mode);
  renderGrid();
}

function withVersion(url, mtime) {
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}v=${mtime}`;
}

function observeThumbnail(entry, img, spinner) {
  if (!state.thumbObserver) {
    state.thumbObserver = new IntersectionObserver(
      (items) => {
        items.forEach((item) => {
          if (!item.isIntersecting) {
            return;
          }
          const payload = item.target.__thumbPayload;
          if (payload) {
            queueThumbnail(payload.entry, payload.img, payload.spinner);
          }
        });
      },
      { rootMargin: "360px 0px" },
    );
  }
  img.parentElement.__thumbPayload = { entry, img, spinner };
  state.thumbObserver.observe(img.parentElement);
  if (isNearViewport(img.parentElement, 420)) {
    queueThumbnail(entry, img, spinner);
  }
}

function isNearViewport(element, margin) {
  const rect = element.getBoundingClientRect();
  return rect.bottom >= -margin && rect.top <= window.innerHeight + margin;
}

function scanVisibleWork() {
  state.visibleScanTimer = null;
  document.querySelectorAll(".thumb-holder").forEach((holder) => {
    const payload = holder.__thumbPayload;
    if (payload && isNearViewport(holder, 420)) {
      queueThumbnail(payload.entry, payload.img, payload.spinner);
    }
  });
  document.querySelectorAll(".rating").forEach((ratingWrap) => {
    const payload = ratingWrap.__ratingPayload;
    if (payload && isNearViewport(ratingWrap, 220)) {
      queueEmbeddedRating(payload.entry, payload.ratingWrap);
    }
  });
}

function scheduleVisibleWorkScan() {
  if (state.visibleScanTimer) {
    return;
  }
  state.visibleScanTimer = window.setTimeout(scanVisibleWork, 80);
}

function queueThumbnail(entry, img, spinner, attempt = 0) {
  if (!img.isConnected || img.classList.contains("loaded")) {
    return;
  }
  const key = `${entry.path}:${state.thumbMode}`;
  if (state.thumbQueued.has(key)) {
    state.thumbQueue = state.thumbQueue.filter((item) => item.key !== key);
  }
  state.thumbQueued.add(key);
  state.thumbQueue.unshift({ entry, img, spinner, attempt, mode: state.thumbMode, key });
  trimThumbQueue();
  runThumbQueue();
}

function trimThumbQueue() {
  while (state.thumbQueue.length > THUMB_QUEUE_LIMIT) {
    const dropped = state.thumbQueue.pop();
    if (dropped) {
      state.thumbQueued.delete(dropped.key);
    }
  }
}

function runThumbQueue() {
  while (state.thumbActive < THUMB_LOAD_CONCURRENCY && state.thumbQueue.length > 0) {
    const payload = state.thumbQueue.shift();
    state.thumbQueued.delete(payload.key);
    if (!payload.img.isConnected || payload.img.classList.contains("loaded") || payload.mode !== state.thumbMode) {
      continue;
    }
    state.thumbActive += 1;
    loadThumbnail(payload.entry, payload.img, payload.spinner, payload.attempt, payload.mode)
      .catch(() => null)
      .finally(() => {
        state.thumbActive = Math.max(0, state.thumbActive - 1);
        runThumbQueue();
      });
  }
}

function resetThumbObserver() {
  if (state.thumbObserver) {
    state.thumbObserver.disconnect();
    state.thumbObserver = null;
  }
}

function clearThumbTimers() {
  for (const timer of state.thumbTimers.values()) {
    window.clearTimeout(timer);
  }
  state.thumbTimers.clear();
  state.thumbQueue = [];
  state.thumbQueued.clear();
  for (const controller of state.thumbControllers.values()) {
    controller.abort();
  }
  state.thumbControllers.clear();
}

function clearRatingTimers() {
  for (const timer of state.ratingTimers.values()) {
    window.clearTimeout(timer);
  }
  state.ratingTimers.clear();
  state.ratingQueue = [];
  state.ratingQueued.clear();
}

function clearVisibleWorkScan() {
  if (state.visibleScanTimer) {
    window.clearTimeout(state.visibleScanTimer);
    state.visibleScanTimer = null;
  }
}

function resetRatingObserver() {
  if (state.ratingObserver) {
    state.ratingObserver.disconnect();
    state.ratingObserver = null;
  }
}

function applyFilters() {
  state.filterGeneration += 1;
  clearFilterRefreshTimer();
  state.filters.ratings = getSelectedRatings();
  state.filters.dateFrom = dateFromFilter.value;
  state.filters.dateTo = dateToFilter.value;
  updateRatingFilterLabel();
  state.entries = [];
  renderBreadcrumb();
  renderGrid();
  loadFolder(state.folder);
}

function getSelectedRatings() {
  return ratingFilterInputs.filter((input) => input.checked).map((input) => input.value);
}

function updateRatingFilterLabel() {
  const labels = state.filters.ratings.map((rating) => (rating === "0" ? "未评分" : `${rating} 星`));
  ratingFilterBtn.textContent = labels.length ? labels.join("、") : "全部";
}

function setRatingMenuOpen(open) {
  ratingFilterMenu.hidden = !open;
  ratingFilterBtn.setAttribute("aria-expanded", String(open));
}

function createRating(entry, large) {
  const wrap = document.createElement("div");
  wrap.className = `rating ${large ? "rating-large" : ""}`;

  const off = document.createElement("button");
  off.type = "button";
  off.className = `rating-off ${entry.rating === 0 ? "active" : ""}`;
  off.textContent = "OFF";
  off.title = "取消评分";
  off.addEventListener("click", async (event) => {
    event.stopPropagation();
    await setRating(entry, 0);
  });
  wrap.append(off);

  for (let i = 1; i <= 5; i += 1) {
    const star = document.createElement("button");
    star.type = "button";
    star.className = `star ${i <= entry.rating ? "active" : ""}`;
    star.textContent = "★";
    star.title = `${i} 分`;
    if (large) {
      star.style.fontSize = "28px";
    }
    star.addEventListener("click", async (event) => {
      event.stopPropagation();
      const nextRating = entry.rating === i ? 0 : i;
      await setRating(entry, nextRating);
    });
    wrap.append(star);
  }
  return wrap;
}

function openViewer(entry) {
  showPhoto(entry);
  viewer.showModal();
}

function showPhoto(entry) {
  if (!entry || entry.type !== "photo") {
    return;
  }
  state.currentPhoto = entry;
  state.zoom = 1;
  state.panX = 0;
  state.panY = 0;
  state.isDragging = false;
  state.dragStart = null;
  state.activeTouches.clear();
  state.pinchDistance = 0;
  state.swipeStart = null;
  viewerTitle.textContent = entry.path;
  viewerImage.alt = entry.name;

  const cachedOriginal = getOriginalCache(entry.path);
  entry.originalReady = Boolean(cachedOriginal);
  if (cachedOriginal) {
    showOriginalUrl(entry, cachedOriginal.url);
  } else if (state.originalFetches.has(entry.path)) {
    viewerImage.classList.add("loading");
    loadOriginalImage(entry, true);
  } else if (entry.thumbUrl) {
    viewerImage.classList.remove("ready");
    viewerImage.classList.add("loading");
    viewerImage.src = entry.thumbUrl;
    viewerImage.classList.add("ready");
    loadOriginalImage(entry);
    loadPreviewImage(entry);
  } else {
    viewerImage.classList.remove("ready");
    viewerImage.classList.add("loading");
    viewerImage.removeAttribute("src");
    loadOriginalImage(entry);
    loadPreviewImage(entry);
  }
  renderViewerRating();
  updatePageButtons();
  updateZoom();
  updateDownloadButton();
  preloadAdjacentPreviews();
}

function updateDownloadButton() {
  if (isAppleMobileBrowser) {
    downloadBtn.textContent = "保存到相册";
    downloadBtn.title = "优先调起系统分享，失败时请长按图片存储到相册";
    return;
  }
  downloadBtn.textContent = "下载";
  downloadBtn.title = "下载原图";
}

async function loadPreviewImage(entry, attempt = 0) {
  if (state.previewTimer) {
    window.clearTimeout(state.previewTimer);
    state.previewTimer = null;
  }
  try {
    const response = await fetch(`/api/preview-status/${encodePath(entry.path)}`, { cache: "no-store" });
    const data = await response.json();
    if (response.status === 200) {
      if (state.currentPhoto?.path !== entry.path) {
        return;
      }
      if (entry.originalReady || getOriginalCache(entry.path)) {
        return;
      }
      viewerImage.classList.remove("ready");
      viewerImage.classList.remove("loading");
      viewerImage.onload = () => viewerImage.classList.add("ready");
      viewerImage.src = `${data.url}?v=${entry.mtime}`;
      entry.previewUrl = viewerImage.src;
      return;
    }
    if (response.status !== 202) {
      showOriginalImageFallback(entry);
      return;
    }
  } catch {
    showOriginalImageFallback(entry);
    return;
  }

  if (attempt >= 8) {
    showOriginalImageFallback(entry);
    return;
  }
  const delay = Math.min(2500, 350 + attempt * 220);
  state.previewTimer = window.setTimeout(() => {
    loadPreviewImage(entry, attempt + 1);
  }, delay);
}

function showOriginalImageFallback(entry) {
  loadOriginalImage(entry, true);
}

function renderViewerRating() {
  viewerRating.innerHTML = "";
  if (state.currentPhoto) {
    viewerRating.append(createRating(state.currentPhoto, true));
  }
}

async function setRating(entry, rating) {
  const updated = await fetchJson(`/api/rating/${encodePath(entry.path)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rating }),
  });
  entry.rating = updated.rating;
  if (state.currentPhoto?.path === entry.path) {
    state.currentPhoto.rating = updated.rating;
    renderViewerRating();
  } else {
    renderGrid();
  }
}

function updateZoom() {
  viewerImage.style.transform = `translate3d(${state.panX}px, ${state.panY}px, 0) scale(${state.zoom})`;
  zoomResetBtn.textContent = `${Math.round(state.zoom * 100)}%`;
  imageStage.classList.toggle("is-zoomed", state.zoom > 1);
}

function currentPhotoIndex() {
  if (!state.currentPhoto) {
    return -1;
  }
  return photosOnly().findIndex((entry) => entry.path === state.currentPhoto.path);
}

function photosOnly() {
  return state.entries.filter((entry) => entry.type === "photo");
}

function showAdjacentPhoto(direction) {
  const photos = photosOnly();
  const current = currentPhotoIndex();
  const next = current + direction;
  if (next < 0 || next >= photos.length) {
    return;
  }
  showPhoto(photos[next]);
}

function updatePageButtons() {
  const index = currentPhotoIndex();
  const last = photosOnly().length - 1;
  prevBtn.disabled = index <= 0;
  nextBtn.disabled = index < 0 || index >= last;
}

function preloadAdjacentPreviews() {
  const photos = photosOnly();
  const index = currentPhotoIndex();
  [photos[index - 1], photos[index + 1]].forEach((entry) => {
    if (!entry) {
      return;
    }
    fetch(`/api/preview-status/${encodePath(entry.path)}`, { cache: "no-store" }).catch(() => {});
  });
}

function queueAdjacentOriginals() {
  const photos = photosOnly();
  const index = currentPhotoIndex();
  const candidates = [
    photos[index + 1],
    photos[index - 1],
    photos[index + 2],
    photos[index - 2],
  ].filter(Boolean);

  candidates.forEach((entry) => queueOriginalPrefetch(entry));
  runOriginalPrefetchQueue();
}

function queueOriginalPrefetch(entry) {
  if (getOriginalCache(entry.path) || state.originalFetches.has(entry.path)) {
    return;
  }
  if (state.originalPrefetchQueue.some((item) => item.path === entry.path)) {
    return;
  }
  state.originalPrefetchQueue.unshift(entry);
  while (state.originalPrefetchQueue.length > ORIGINAL_PREFETCH_QUEUE_LIMIT) {
    state.originalPrefetchQueue.pop();
  }
}

function runOriginalPrefetchQueue() {
  while (
    state.originalPrefetchActive < ORIGINAL_PREFETCH_CONCURRENCY
    && state.originalPrefetchQueue.length > 0
  ) {
    const entry = state.originalPrefetchQueue.shift();
    state.originalPrefetchActive += 1;
    loadOriginalImage(entry, false)
      .catch(() => null)
      .finally(() => {
        state.originalPrefetchActive -= 1;
        runOriginalPrefetchQueue();
      });
  }
}

async function loadOriginalImage(entry, forceDisplay = false) {
  const cached = getOriginalCache(entry.path);
  if (cached) {
    if (forceDisplay || state.currentPhoto?.path === entry.path) {
      showOriginalUrl(entry, cached.url);
    }
    return cached.url;
  }
  if (state.originalFetches.has(entry.path)) {
    const url = await state.originalFetches.get(entry.path);
    if ((forceDisplay || state.currentPhoto?.path === entry.path) && url) {
      showOriginalUrl(entry, url);
    }
    return url;
  }

  const promise = fetch(`/api/image/${encodePath(entry.path)}`)
    .then((response) => {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      return response.blob();
    })
    .then((blob) => {
      const url = URL.createObjectURL(blob);
      putOriginalCache(entry.path, url, blob.size);
      return url;
    })
    .catch(() => null)
    .finally(() => {
      state.originalFetches.delete(entry.path);
    });
  state.originalFetches.set(entry.path, promise);
  const url = await promise;
  if ((forceDisplay || state.currentPhoto?.path === entry.path) && url) {
    showOriginalUrl(entry, url);
  }
  return url;
}

function showOriginalUrl(entry, url) {
  if (state.currentPhoto?.path !== entry.path) {
    return;
  }
  entry.originalReady = true;
  viewerImage.classList.remove("ready");
  viewerImage.classList.remove("loading");
  viewerImage.onload = () => viewerImage.classList.add("ready");
  viewerImage.src = url;
  if (viewerImage.complete && viewerImage.naturalWidth > 0) {
    viewerImage.classList.add("ready");
  }
  queueAdjacentOriginals();
}

function getOriginalCache(path) {
  const item = state.originalCache.get(path);
  if (!item) {
    return null;
  }
  item.lastUsed = Date.now();
  state.originalCache.delete(path);
  state.originalCache.set(path, item);
  return item;
}

function putOriginalCache(path, url, bytes) {
  const existing = state.originalCache.get(path);
  if (existing) {
    state.originalCacheBytes -= existing.bytes;
    URL.revokeObjectURL(existing.url);
    state.originalCache.delete(path);
  }
  state.originalCache.set(path, { url, bytes, lastUsed: Date.now() });
  state.originalCacheBytes += bytes;
  trimOriginalCache();
}

function trimOriginalCache() {
  while (state.originalCacheBytes > ORIGINAL_CACHE_LIMIT && state.originalCache.size > 0) {
    const [path, item] = state.originalCache.entries().next().value;
    URL.revokeObjectURL(item.url);
    state.originalCacheBytes -= item.bytes;
    state.originalCache.delete(path);
  }
}

window.addEventListener("beforeunload", () => {
  for (const item of state.originalCache.values()) {
    URL.revokeObjectURL(item.url);
  }
  state.originalCache.clear();
  state.originalCacheBytes = 0;
});

function distanceBetweenTouches() {
  const touches = Array.from(state.activeTouches.values());
  if (touches.length < 2) {
    return 0;
  }
  const [first, second] = touches;
  return Math.hypot(first.x - second.x, first.y - second.y);
}

function midpointBetweenTouches() {
  const touches = Array.from(state.activeTouches.values());
  if (touches.length < 2) {
    return { x: 0, y: 0 };
  }
  const [first, second] = touches;
  return { x: (first.x + second.x) / 2, y: (first.y + second.y) / 2 };
}

function clampPan() {
  if (state.zoom <= 1) {
    state.panX = 0;
    state.panY = 0;
    return;
  }
  const maxX = (imageStage.clientWidth * (state.zoom - 1)) / 2;
  const maxY = (imageStage.clientHeight * (state.zoom - 1)) / 2;
  state.panX = Math.max(-maxX, Math.min(maxX, state.panX));
  state.panY = Math.max(-maxY, Math.min(maxY, state.panY));
}

function setZoom(nextZoom, centerX = imageStage.clientWidth / 2, centerY = imageStage.clientHeight / 2) {
  const previousZoom = state.zoom;
  state.zoom = Math.max(1, Math.min(6, nextZoom));
  if (state.zoom === 1) {
    state.panX = 0;
    state.panY = 0;
  } else if (previousZoom !== state.zoom) {
    const rect = imageStage.getBoundingClientRect();
    const dx = centerX - rect.left - rect.width / 2;
    const dy = centerY - rect.top - rect.height / 2;
    const scale = state.zoom / previousZoom;
    state.panX = state.panX * scale - dx * (scale - 1);
    state.panY = state.panY * scale - dy * (scale - 1);
    clampPan();
  }
  updateZoom();
}

async function deleteCurrentPhoto() {
  if (!state.currentPhoto) {
    return;
  }
  await fetchJson(`/api/photo/${encodePath(state.currentPhoto.path)}`, { method: "DELETE" });
  viewer.close();
  state.currentPhoto = null;
  await loadFolder(state.folder);
}

function requestDeleteCurrentPhoto() {
  if (!state.currentPhoto) {
    return;
  }
  deleteDialogPath.textContent = state.currentPhoto.path;
  deleteDialog.showModal();
}

async function downloadCurrentPhoto() {
  if (!state.currentPhoto) {
    return;
  }
  if (isAppleMobileBrowser) {
    await saveCurrentPhotoForAppleMobile();
    return;
  }
  window.location.href = `/api/download/${encodePath(state.currentPhoto.path)}`;
}

async function saveCurrentPhotoForAppleMobile() {
  const entry = state.currentPhoto;
  if (!entry) {
    return;
  }

  try {
    const blob = await fetchPhotoBlob(entry);
    const file = new File([blob], entry.name, {
      type: blob.type || "image/jpeg",
      lastModified: Date.now(),
    });

    if (navigator.share && (!navigator.canShare || navigator.canShare({ files: [file] }))) {
      await navigator.share({
        files: [file],
        title: entry.name,
        text: "保存原图",
      });
      return;
    }
  } catch {
    // Fall through to the long-press guidance below.
  }

  window.alert("请长按当前图片，然后点“存储到照片”或“存储图像”。");
}

async function fetchPhotoBlob(entry) {
  const cached = getOriginalCache(entry.path);
  if (cached) {
    const response = await fetch(cached.url);
    return response.blob();
  }

  const response = await fetch(`/api/image/${encodePath(entry.path)}`);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.blob();
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json();
}

function encodePath(path) {
  return path.split("/").map(encodeURIComponent).join("/");
}

function formatDate(timestamp) {
  const date = new Date(timestamp * 1000);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

backBtn.addEventListener("click", () => {
  if (state.folder) {
    loadFolder(state.parent);
  }
});
refreshBtn.addEventListener("click", () => loadFolder(state.folder));
window.addEventListener("scroll", scheduleVisibleWorkScan, { passive: true });
ratingFilterBtn.addEventListener("click", (event) => {
  event.stopPropagation();
  setRatingMenuOpen(ratingFilterMenu.hidden);
});
ratingFilterMenu.addEventListener("click", (event) => event.stopPropagation());
ratingFilterInputs.forEach((input) => {
  input.addEventListener("change", applyFilters);
});
dateFromFilter.addEventListener("change", applyFilters);
dateToFilter.addEventListener("change", applyFilters);
thumbModeSelect.value = state.thumbMode;
thumbModeSelect.addEventListener("change", () => setThumbMode(thumbModeSelect.value));
detectBracketsBtn.addEventListener("click", detectBracketsInContextFolder);
closeBracketDialogBtn.addEventListener("click", () => bracketDialog.close());
document.addEventListener("click", (event) => {
  if (!ratingFilterMenu.hidden && !ratingFilterMenu.contains(event.target) && event.target !== ratingFilterBtn) {
    setRatingMenuOpen(false);
  }
  if (!folderContextMenu.hidden && !folderContextMenu.contains(event.target)) {
    closeFolderContextMenu();
  }
});
document.addEventListener("contextmenu", (event) => {
  if (!event.target.closest(".tile-button")) {
    closeFolderContextMenu();
  }
});
clearFiltersBtn.addEventListener("click", () => {
  ratingFilterInputs.forEach((input) => {
    input.checked = false;
  });
  dateFromFilter.value = "";
  dateToFilter.value = "";
  applyFilters();
});
closeBtn.addEventListener("click", () => viewer.close());
prevBtn.addEventListener("click", () => showAdjacentPhoto(-1));
nextBtn.addEventListener("click", () => showAdjacentPhoto(1));
downloadBtn.addEventListener("click", downloadCurrentPhoto);
deleteBtn.addEventListener("click", requestDeleteCurrentPhoto);
cancelDeleteBtn.addEventListener("click", () => deleteDialog.close());
confirmDeleteBtn.addEventListener("click", async () => {
  deleteDialog.close();
  await deleteCurrentPhoto();
});
zoomInBtn.addEventListener("click", () => {
  setZoom(state.zoom + 0.25);
});
zoomOutBtn.addEventListener("click", () => {
  setZoom(state.zoom - 0.25);
});
zoomResetBtn.addEventListener("click", () => {
  setZoom(1);
});
imageStage.addEventListener("wheel", (event) => {
  event.preventDefault();
  const factor = event.deltaY < 0 ? 1.12 : 0.88;
  setZoom(state.zoom * factor, event.clientX, event.clientY);
}, { passive: false });
imageStage.addEventListener("pointerdown", (event) => {
  if (event.pointerType !== "mouse" || state.zoom <= 1) {
    return;
  }
  event.preventDefault();
  imageStage.setPointerCapture(event.pointerId);
  state.isDragging = true;
  state.dragStart = { x: event.clientX, y: event.clientY, panX: state.panX, panY: state.panY };
});
imageStage.addEventListener("pointermove", (event) => {
  if (!state.isDragging || !state.dragStart) {
    return;
  }
  event.preventDefault();
  state.panX = state.dragStart.panX + event.clientX - state.dragStart.x;
  state.panY = state.dragStart.panY + event.clientY - state.dragStart.y;
  clampPan();
  updateZoom();
});
imageStage.addEventListener("pointerup", () => {
  state.isDragging = false;
  state.dragStart = null;
});
imageStage.addEventListener("pointercancel", () => {
  state.isDragging = false;
  state.dragStart = null;
});
imageStage.addEventListener("dblclick", (event) => {
  event.preventDefault();
  setZoom(state.zoom > 1 ? 1 : 2, event.clientX, event.clientY);
});
imageStage.addEventListener("touchstart", (event) => {
  event.preventDefault();
  for (const touch of event.changedTouches) {
    state.activeTouches.set(touch.identifier, { x: touch.clientX, y: touch.clientY });
  }
  if (state.activeTouches.size >= 2) {
    state.pinchDistance = distanceBetweenTouches();
    state.pinchZoom = state.zoom;
    const middle = midpointBetweenTouches();
    state.dragStart = { x: middle.x, y: middle.y, panX: state.panX, panY: state.panY };
  } else if (event.changedTouches.length === 1) {
    const touch = event.changedTouches[0];
    state.swipeStart = { x: touch.clientX, y: touch.clientY, time: Date.now() };
    state.dragStart = { x: touch.clientX, y: touch.clientY, panX: state.panX, panY: state.panY };
    state.swipeMoved = false;
  }
}, { passive: false });
imageStage.addEventListener(
  "touchmove",
  (event) => {
    event.preventDefault();
    for (const touch of event.changedTouches) {
      state.activeTouches.set(touch.identifier, { x: touch.clientX, y: touch.clientY });
    }
    if (state.activeTouches.size >= 2 && state.pinchDistance > 0) {
      const nextDistance = distanceBetweenTouches();
      const middle = midpointBetweenTouches();
      state.zoom = Math.max(1, Math.min(6, state.pinchZoom * (nextDistance / state.pinchDistance)));
      if (state.dragStart) {
        state.panX = state.dragStart.panX + middle.x - state.dragStart.x;
        state.panY = state.dragStart.panY + middle.y - state.dragStart.y;
        clampPan();
      }
      updateZoom();
    } else if (state.zoom > 1 && state.dragStart && event.changedTouches.length === 1) {
      const touch = event.changedTouches[0];
      state.panX = state.dragStart.panX + touch.clientX - state.dragStart.x;
      state.panY = state.dragStart.panY + touch.clientY - state.dragStart.y;
      clampPan();
      updateZoom();
    } else if (state.swipeStart && state.zoom === 1 && event.changedTouches.length === 1) {
      const touch = event.changedTouches[0];
      const dx = touch.clientX - state.swipeStart.x;
      const dy = touch.clientY - state.swipeStart.y;
      if (Math.abs(dx) > 12 && Math.abs(dx) > Math.abs(dy) * 1.4) {
        state.swipeMoved = true;
      }
    }
  },
  { passive: false },
);
imageStage.addEventListener("touchend", (event) => {
  const wasSingleTouch = state.activeTouches.size === 1 && event.changedTouches.length === 1;
  if (state.swipeStart && state.zoom === 1 && event.changedTouches.length === 1) {
    const touch = event.changedTouches[0];
    const dx = touch.clientX - state.swipeStart.x;
    const dy = touch.clientY - state.swipeStart.y;
    const elapsed = Date.now() - state.swipeStart.time;
    if (Math.abs(dx) > 70 && Math.abs(dx) > Math.abs(dy) * 1.4 && elapsed < 900) {
      showAdjacentPhoto(dx < 0 ? 1 : -1);
    }
  }
  if (wasSingleTouch && state.swipeStart && !state.swipeMoved) {
    const now = Date.now();
    const touch = event.changedTouches[0];
    if (now - state.lastTapTime < 300) {
      setZoom(state.zoom > 1 ? 1 : 2, touch.clientX, touch.clientY);
      state.lastTapTime = 0;
    } else {
      state.lastTapTime = now;
    }
  }
  clearEndedTouches(event);
  state.swipeStart = null;
  state.dragStart = null;
});
imageStage.addEventListener("touchcancel", clearEndedTouches);
document.addEventListener("keydown", (event) => {
  if (!viewer.open) {
    return;
  }
  if (event.key === "ArrowLeft") {
    showAdjacentPhoto(-1);
  } else if (event.key === "ArrowRight") {
    showAdjacentPhoto(1);
  } else if (event.key === "Escape") {
    viewer.close();
  }
});

function clearEndedTouches(event) {
  for (const touch of event.changedTouches) {
    state.activeTouches.delete(touch.identifier);
  }
  if (state.activeTouches.size < 2) {
    state.pinchDistance = 0;
  }
}

loadConfig()
  .then(() => loadFolder(""))
  .catch((error) => {
    emptyState.hidden = false;
    emptyState.textContent = error.message;
  });
