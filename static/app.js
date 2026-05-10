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
  previewTimer: null,
  thumbObserver: null,
  activeTouches: new Map(),
  pinchDistance: 0,
  pinchZoom: 1,
  swipeStart: null,
  swipeMoved: false,
  lastTapTime: 0,
  filters: {
    minRating: "",
    dateFrom: "",
    dateTo: "",
  },
};

const grid = document.querySelector("#grid");
const emptyState = document.querySelector("#emptyState");
const breadcrumb = document.querySelector("#breadcrumb");
const rootPath = document.querySelector("#rootPath");
const backBtn = document.querySelector("#backBtn");
const refreshBtn = document.querySelector("#refreshBtn");
const ratingFilter = document.querySelector("#ratingFilter");
const dateFromFilter = document.querySelector("#dateFromFilter");
const dateToFilter = document.querySelector("#dateToFilter");
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

async function loadConfig() {
  const config = await fetchJson("/api/config");
  rootPath.textContent = config.root;
}

async function loadFolder(folder = state.folder) {
  const params = new URLSearchParams();
  params.set("folder", folder);
  if (state.filters.minRating) {
    params.set("rating", state.filters.minRating);
  }
  if (state.filters.dateFrom) {
    params.set("date_from", state.filters.dateFrom);
  }
  if (state.filters.dateTo) {
    params.set("date_to", state.filters.dateTo);
  }
  const data = await fetchJson(`/api/photos?${params.toString()}`);
  state.folder = data.folder;
  state.parent = data.parent;
  state.entries = data.entries;
  renderBreadcrumb();
  renderGrid();
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
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = part;
    btn.addEventListener("click", () => loadFolder(current));
    breadcrumb.append(btn);
  });

  backBtn.disabled = !state.folder;
}

function renderGrid() {
  clearThumbTimers();
  resetThumbObserver();
  grid.innerHTML = "";
  emptyState.hidden = state.entries.length > 0;

  state.entries.forEach((entry) => {
    const tile = document.createElement("article");
    tile.className = "tile";

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
    } else {
      const holder = document.createElement("div");
      holder.className = "thumb-holder";
      const spinner = document.createElement("div");
      spinner.className = "spinner";
      spinner.setAttribute("aria-label", "正在生成预览");
      const img = document.createElement("img");
      img.className = "thumb";
      img.loading = "eager";
      img.decoding = "async";
      img.alt = entry.name;
      holder.append(spinner, img);
      button.append(holder);
      observeThumbnail(entry, img, spinner);
      button.addEventListener("click", () => openViewer(entry));
    }

    const meta = document.createElement("div");
    meta.className = "meta";
    const name = document.createElement("div");
    name.className = "name";
    name.textContent = entry.name;
    meta.append(name);

    if (entry.type === "photo") {
      const detail = document.createElement("div");
      detail.className = "detail";
      detail.textContent = formatDate(entry.mtime);
      meta.append(detail);
      meta.append(createRating(entry, false));
    }

    tile.append(button, meta);
    grid.append(tile);
  });
}

async function loadThumbnail(entry, img, spinner, attempt = 0) {
  try {
    const response = await fetch(`/api/thumb-status/${encodePath(entry.path)}`, { cache: "no-store" });
    const data = await response.json();
    if (response.status === 200) {
      img.loading = "eager";
      img.onload = () => {
        img.classList.add("loaded");
        spinner.hidden = true;
        entry.thumbUrl = img.src;
      };
      img.onerror = () => {
        showThumbnailFallback(entry, img, spinner);
      };
      img.src = `${data.url}?v=${entry.mtime}`;
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
    showThumbnailFallback(entry, img, spinner);
    return;
  }

  if (attempt >= 8) {
    showThumbnailFallback(entry, img, spinner);
    return;
  }
  const delay = Math.min(3000, 450 + attempt * 250);
  const timer = window.setTimeout(() => {
    state.thumbTimers.delete(entry.path);
    loadThumbnail(entry, img, spinner, attempt + 1);
  }, delay);
  state.thumbTimers.set(entry.path, timer);
}

function showThumbnailFallback(entry, img, spinner) {
  img.loading = "eager";
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

function observeThumbnail(entry, img, spinner) {
  if (!state.thumbObserver) {
    state.thumbObserver = new IntersectionObserver(
      (items) => {
        items.forEach((item) => {
          if (!item.isIntersecting) {
            return;
          }
          state.thumbObserver.unobserve(item.target);
          const payload = item.target.__thumbPayload;
          if (payload) {
            loadThumbnail(payload.entry, payload.img, payload.spinner);
          }
        });
      },
      { rootMargin: "900px 0px" },
    );
  }
  img.parentElement.__thumbPayload = { entry, img, spinner };
  state.thumbObserver.observe(img.parentElement);
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
}

function applyFilters() {
  state.filters.minRating = ratingFilter.value;
  state.filters.dateFrom = dateFromFilter.value;
  state.filters.dateTo = dateToFilter.value;
  loadFolder(state.folder);
}

function createRating(entry, large) {
  const wrap = document.createElement("div");
  wrap.className = "rating";
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
  viewerImage.classList.remove("ready");
  viewerImage.classList.add("loading");
  if (entry.thumbUrl) {
    viewerImage.src = entry.thumbUrl;
    viewerImage.classList.add("ready");
  } else {
    viewerImage.removeAttribute("src");
  }
  loadPreviewImage(entry);
  renderViewerRating();
  updatePageButtons();
  updateZoom();
  preloadAdjacentPhotos();
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
      viewerImage.classList.remove("ready");
      viewerImage.classList.remove("loading");
      viewerImage.onload = () => viewerImage.classList.add("ready");
      viewerImage.src = `${data.url}?v=${entry.mtime}`;
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
  if (state.currentPhoto?.path !== entry.path) {
    return;
  }
  viewerImage.classList.remove("ready");
  viewerImage.classList.remove("loading");
  viewerImage.onload = () => viewerImage.classList.add("ready");
  viewerImage.src = `/api/image/${encodePath(entry.path)}`;
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

function preloadAdjacentPhotos() {
  const photos = photosOnly();
  const index = currentPhotoIndex();
  [photos[index - 1], photos[index + 1]].forEach((entry) => {
    if (!entry) {
      return;
    }
    fetch(`/api/preview-status/${encodePath(entry.path)}`, { cache: "no-store" }).catch(() => {});
  });
}

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

function downloadCurrentPhoto() {
  if (!state.currentPhoto) {
    return;
  }
  window.location.href = `/api/download/${encodePath(state.currentPhoto.path)}`;
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
ratingFilter.addEventListener("change", applyFilters);
dateFromFilter.addEventListener("change", applyFilters);
dateToFilter.addEventListener("change", applyFilters);
clearFiltersBtn.addEventListener("click", () => {
  ratingFilter.value = "";
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
