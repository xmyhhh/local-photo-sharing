const VIEWER_TRANSITION_MS = 260;

function openViewer(entry, originElement = null) {
  showPhoto(entry);
  armViewerHistory();
  showViewerControls({ autoHide: true });
  if (!originElement || prefersReducedMotion()) {
    viewer.showModal();
    enterViewerFullscreen();
    viewer.classList.remove("is-transitioning", "is-fading-out");
    return;
  }
  startViewerEnterTransition(entry, originElement);
}

function armViewerHistory() {
  if (state.viewerHistoryArmed) {
    return;
  }
  window.history.pushState({ viewerOpen: true }, "", window.location.href);
  state.viewerHistoryArmed = true;
  state.closingViewerFromHistory = false;
}

function closeViewerFromUi() {
  if (!viewer.open) {
    return;
  }
  if (state.viewerHistoryArmed && !state.closingViewerFromHistory) {
    state.closingViewerFromHistory = true;
    window.history.back();
    return;
  }
  closeViewerAnimated();
}

function enterViewerFullscreen() {
  if (document.fullscreenElement || !viewer.requestFullscreen) {
    return;
  }
  viewer.requestFullscreen({ navigationUI: "hide" })
    .then(() => {
      state.viewerRequestedFullscreen = true;
    })
    .catch(() => {
      state.viewerRequestedFullscreen = false;
    });
}

function exitViewerFullscreen() {
  if (!state.viewerRequestedFullscreen || document.fullscreenElement !== viewer || !document.exitFullscreen) {
    state.viewerRequestedFullscreen = false;
    return;
  }
  document.exitFullscreen().catch(() => null);
  state.viewerRequestedFullscreen = false;
}

function finishViewerClose() {
  cancelViewerOriginalLoads();
  releaseServerMemoryPrefetch();
  closePhotoInfoPanel();
  setViewerRatingMenuOpen(false);
  state.viewerHistoryArmed = false;
  state.closingViewerFromHistory = false;
  state.currentPhoto = null;
  viewer.close();
  exitViewerFullscreen();
}

function setViewerControlsVisible(visible) {
  state.viewerControlsVisible = visible;
  viewer.classList.toggle("controls-hidden", !visible);
  if (!visible) {
    setViewerRatingMenuOpen(false);
  }
}

function showViewerControls({ autoHide = false } = {}) {
  if (!viewer.open && !state.currentPhoto) {
    return;
  }
  setViewerControlsVisible(true);
  scheduleViewerControlsAutoHide(autoHide);
}

function hideViewerControls() {
  if (isViewerLocked()) {
    return;
  }
  setViewerControlsVisible(false);
}

function toggleViewerControls() {
  if (isViewerLocked()) {
    return;
  }
  if (state.viewerControlsVisible) {
    hideViewerControls();
  } else {
    showViewerControls({ autoHide: false });
  }
}

function scheduleViewerControlsAutoHide(enabled = true) {
  if (state.viewerControlsTimer) {
    window.clearTimeout(state.viewerControlsTimer);
    state.viewerControlsTimer = null;
  }
  if (!enabled || isViewerLocked() || !photoInfoPanel.hidden) {
    return;
  }
  state.viewerControlsTimer = window.setTimeout(() => {
    state.viewerControlsTimer = null;
    hideViewerControls();
  }, 2600);
}

function isCoarsePointer() {
  return window.matchMedia("(pointer: coarse)").matches;
}

function showPhoto(entry) {
  if (!entry || (entry.type !== "photo" && entry.type !== "video")) {
    return;
  }
  state.viewerGeneration += 1;
  state.viewerLiveMode = false;
  cancelStaleOriginalLoads(entry.type === "photo" ? entry.path : null);
  state.currentPhoto = entry;
  updateServerMemoryPrefetch();
  state.zoom = 1;
  state.panX = 0;
  state.panY = 0;
  state.isDragging = false;
  state.dragStart = null;
  state.activeTouches.clear();
  state.pinchDistance = 0;
  state.swipeStart = null;
  setViewerRatingMenuOpen(false);
  refreshPhotoInfoForCurrentEntry();
  viewerTitle.textContent = entry.path;
  viewerImage.alt = entry.name;
  viewerVideo.pause();
  viewerVideo.hidden = true;
  viewerVideo.removeAttribute("src");
  viewerVideo.load();
  livePhotoBtn.hidden = !(entry.type === "photo" && entry.isLive);
  livePhotoBtn.textContent = "播放实况";
  viewerImage.hidden = entry.type === "video";

  if (entry.type === "video") {
    viewerImage.classList.remove("ready", "loading");
    viewerImage.removeAttribute("src");
    viewerVideo.hidden = false;
    viewerVideo.currentTime = 0;
    viewerVideo.src = `/api/image/${encodePath(entry.path)}`;
    viewerVideo.load();
    renderViewerRating();
    updateViewerModeControls();
    updatePageButtons();
    updateZoom();
    updateDownloadButton();
    return;
  }

  viewerImage.hidden = false;
  updateViewerModeControls();

  if (entry.browserRenderable === false) {
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
    updateDownloadButton();
    preloadAdjacentPreviews();
    return;
  }

  if (state.clientPrefetch.originalPreviewEnabled && entry.originalUrl) {
    viewerImage.classList.remove("loading");
    viewerImage.onload = () => viewerImage.classList.add("ready");
    viewerImage.src = entry.originalUrl;
    renderViewerRating();
    updatePageButtons();
    updateZoom();
    updateDownloadButton();
    return;
  }

  if (!state.clientPrefetch.originalPreviewEnabled) {
    entry.originalReady = false;
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
    updateDownloadButton();
    preloadAdjacentPreviews();
    return;
  }

  const cachedOriginal = getOriginalCache(entry.path);
  entry.originalReady = Boolean(cachedOriginal);
  if (cachedOriginal) {
    showOriginalUrl(entry, cachedOriginal.url);
  } else if (state.originalFetches.has(entry.path)) {
    viewerImage.classList.add("loading");
    scheduleCurrentOriginalLoad(entry);
  } else if (entry.thumbUrl) {
    viewerImage.classList.remove("ready");
    viewerImage.classList.add("loading");
    viewerImage.src = entry.thumbUrl;
    viewerImage.classList.add("ready");
    scheduleCurrentOriginalLoad(entry);
    loadPreviewImage(entry);
  } else {
    viewerImage.classList.remove("ready");
    viewerImage.classList.add("loading");
    viewerImage.removeAttribute("src");
    scheduleCurrentOriginalLoad(entry);
    loadPreviewImage(entry);
  }
  renderViewerRating();
  updatePageButtons();
  updateZoom();
  updateDownloadButton();
  preloadAdjacentPreviews();
}

function togglePhotoInfoPanel() {
  if (state.currentPhoto?.type !== "photo" || state.viewerLiveMode) {
    return;
  }
  if (photoInfoPanel.hidden) {
    openPhotoInfoPanel();
    return;
  }
  closePhotoInfoPanel();
}

function openPhotoInfoPanel() {
  if (!state.currentPhoto || state.currentPhoto.type !== "photo" || state.viewerLiveMode) {
    return;
  }
  photoInfoPanel.hidden = false;
  infoBtn.classList.add("active");
  showViewerControls({ autoHide: false });
  loadPhotoInfo(state.currentPhoto);
}

function closePhotoInfoPanel() {
  photoInfoPanel.hidden = true;
  infoBtn.classList.remove("active");
  state.photoInfoPath = "";
  if (state.photoInfoController) {
    state.photoInfoController.abort();
    state.photoInfoController = null;
  }
}

function refreshPhotoInfoForCurrentEntry() {
  if (photoInfoPanel.hidden) {
    return;
  }
  loadPhotoInfo(state.currentPhoto);
}

async function loadPhotoInfo(entry) {
  if (!entry) {
    closePhotoInfoPanel();
    return;
  }
  if (state.photoInfoController) {
    state.photoInfoController.abort();
  }
  state.photoInfoPath = entry.path;
  state.photoInfoController = new AbortController();
  photoInfoBody.innerHTML = '<div class="photo-info-status">正在读取信息...</div>';
  try {
    const info = await fetchJson(`/api/info/${encodePath(entry.path)}`, {
      signal: state.photoInfoController.signal,
      cache: "no-store",
    });
    if (state.photoInfoPath !== entry.path || photoInfoPanel.hidden) {
      return;
    }
    renderPhotoInfo(info);
  } catch (error) {
    if (error.name === "AbortError") {
      return;
    }
    photoInfoBody.innerHTML = '<div class="photo-info-status error">信息读取失败</div>';
  } finally {
    if (state.photoInfoPath === entry.path) {
      state.photoInfoController = null;
    }
  }
}

function renderPhotoInfo(info) {
  photoInfoBody.innerHTML = "";
  const rows = [
    ["文件名", info.name],
    ["格式", info.type],
    ["大小", formatFileSize(info.size)],
    ["尺寸", formatDimensions(info.width, info.height)],
    ["拍照时间", formatExifDate(info.takenAt)],
    ["修改时间", formatTimestamp(info.modified)],
    ["相机", info.camera],
    ["镜头", info.lens],
    ["快门", info.exposureTime],
    ["光圈", info.fNumber],
    ["ISO", info.iso],
    ["焦距", info.focalLength],
    ["曝光补偿", info.exposureBias],
  ].filter(([, value]) => value !== null && value !== undefined && value !== "");

  if (!rows.length) {
    photoInfoBody.innerHTML = '<div class="photo-info-status">没有可显示的信息</div>';
    return;
  }

  rows.forEach(([label, value]) => {
    const row = document.createElement("div");
    row.className = "photo-info-row";
    const name = document.createElement("div");
    name.className = "photo-info-label";
    name.textContent = label;
    const data = document.createElement("div");
    data.className = "photo-info-value";
    data.textContent = String(value);
    row.append(name, data);
    photoInfoBody.append(row);
  });
}

function formatFileSize(bytes) {
  if (!Number.isFinite(bytes)) {
    return "";
  }
  const units = ["B", "KB", "MB", "GB"];
  let size = bytes;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  const digits = unit === 0 || size >= 100 ? 0 : 1;
  return `${size.toFixed(digits)} ${units[unit]}`;
}

function formatDimensions(width, height) {
  return width && height ? `${width} x ${height}` : "";
}

function formatTimestamp(timestamp) {
  if (!timestamp) {
    return "";
  }
  return new Date(timestamp * 1000).toLocaleString();
}

function formatExifDate(value) {
  if (!value) {
    return "";
  }
  const match = String(value).match(/^(\d{4}):(\d{2}):(\d{2})\s+(.*)$/);
  return match ? `${match[1]}-${match[2]}-${match[3]} ${match[4]}` : value;
}

function toggleLivePhotoPlayback() {
  const entry = state.currentPhoto;
  if (!entry || entry.type !== "photo" || !entry.isLive) {
    return;
  }
  if (state.viewerLiveMode) {
    state.viewerLiveMode = false;
    viewerVideo.pause();
    viewerVideo.hidden = true;
    viewerVideo.removeAttribute("src");
    viewerVideo.load();
    viewerImage.hidden = false;
    livePhotoBtn.textContent = "播放实况";
    updateViewerModeControls();
    updateZoom();
    return;
  }
  state.viewerLiveMode = true;
  viewerImage.hidden = true;
  viewerVideo.hidden = false;
  viewerVideo.currentTime = 0;
  viewerVideo.src = `/api/live-video/${encodePath(entry.path)}`;
  viewerVideo.load();
  viewerVideo.play().catch(() => null);
  livePhotoBtn.textContent = "显示照片";
  updateViewerModeControls();
  updateZoom();
}

function updateViewerModeControls() {
  const imageControlsVisible = Boolean(state.currentPhoto?.type === "photo" && !state.viewerLiveMode);
  zoomResetBtn.hidden = !imageControlsVisible;
  rotateBtn.hidden = !imageControlsVisible;
  infoBtn.hidden = !imageControlsVisible;
  if (!imageControlsVisible) {
    closePhotoInfoPanel();
  }
}

function updateDownloadButton() {
  if (isAppleMobileBrowser) {
    downloadBtn.textContent = "保存到相册";
    downloadBtn.title = state.currentPhoto?.type === "video" ? "优先调起系统分享保存视频" : "优先调起系统分享，失败时请长按图片存储到相册";
    return;
  }
  downloadBtn.textContent = "下载";
  downloadBtn.title = state.currentPhoto?.type === "video" ? "下载视频" : "下载原图";
}

async function loadPreviewImage(entry, attempt = 0) {
  if (state.previewTimer) {
    window.clearTimeout(state.previewTimer);
    state.previewTimer = null;
  }
  try {
    const response = await fetch(viewerPreviewStatusUrl(entry), { cache: "no-store" });
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
      viewerImage.src = withVersion(data.url, entry.mtime);
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
  if (state.currentPhoto?.path === entry.path && state.clientPrefetch.originalPreviewEnabled) {
    scheduleCurrentOriginalLoad(entry);
  }
}

function viewerPreviewStatusUrl(entry) {
  if (entry.browserRenderable === false) {
    return `/api/thumb-status/${encodePath(entry.path)}?mode=xlarge`;
  }
  return `/api/preview-status/${encodePath(entry.path)}`;
}

function renderViewerRating() {
  viewerRatingMenu.innerHTML = "";
  const isPhoto = Boolean(state.currentPhoto && state.currentPhoto.type === "photo");
  viewerRatingBtn.hidden = !isPhoto;
  viewerRatingMenu.hidden = true;
  viewerRatingBtn.setAttribute("aria-expanded", "false");
  if (!isPhoto) {
    viewerRatingBtn.textContent = "☆";
    return;
  }

  updateViewerRatingButton();
  [
    { value: 0, label: "Off" },
    { value: 1, label: "1 星" },
    { value: 2, label: "2 星" },
    { value: 3, label: "3 星" },
    { value: 4, label: "4 星" },
    { value: 5, label: "5 星" },
  ].forEach((item) => {
    const option = document.createElement("button");
    option.type = "button";
    option.textContent = item.label;
    option.className = state.currentPhoto.rating === item.value ? "active" : "";
    option.addEventListener("click", async () => {
      await setRating(state.currentPhoto, item.value);
      setViewerRatingMenuOpen(false);
    });
    viewerRatingMenu.append(option);
  });
}

function updateViewerRatingButton() {
  const rating = state.currentPhoto?.rating || 0;
  viewerRatingBtn.textContent = rating > 0 ? `${rating} ★` : "☆";
  viewerRatingBtn.classList.toggle("active", rating > 0);
  viewerRatingBtn.title = rating > 0 ? `${rating} 星` : "未评分";
}

function setViewerRatingMenuOpen(open) {
  if (viewerRatingBtn.hidden) {
    open = false;
  }
  viewerRatingMenu.hidden = !open;
  viewerRatingBtn.setAttribute("aria-expanded", String(open));
  if (open) {
    positionViewerRatingMenu();
  } else {
    viewerRatingMenu.style.removeProperty("left");
    viewerRatingMenu.style.removeProperty("top");
  }
}

async function setRating(entry, rating) {
  if (entry.type !== "photo") {
    return;
  }
  const updated = await fetchJson(`/api/rating/${encodePath(entry.path)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rating }),
  });
  entry.rating = updated.rating;
  entry.ratingPending = false;
  if (state.currentPhoto?.path === entry.path) {
    state.currentPhoto.rating = updated.rating;
    state.currentPhoto.ratingPending = false;
    updateViewerRatingButton();
    if (!viewerRatingMenu.hidden) {
      renderViewerRating();
      setViewerRatingMenuOpen(true);
    }
  }
  if (!entryMatchesActiveRatingFilter(entry)) {
    if (!state.timelineViewerOpen) {
      removeGridEntry(entry);
    }
    return;
  }
  updateGridRating(entry);
}

function entryMatchesActiveRatingFilter(entry) {
  if (!state.filters.ratings.length) {
    return true;
  }
  return state.filters.ratings.includes(String(entry.rating));
}

function removeGridEntry(entry) {
  state.entries = state.entries.filter((item) => item.path !== entry.path);
  state.entryByPath.delete(entry.path);
  document.querySelector(`.tile[data-path="${CSS.escape(entry.path)}"]`)?.remove();
  updateEmptyState();
}

function updateGridRating(entry) {
  const tile = document.querySelector(`.tile[data-path="${CSS.escape(entry.path)}"]`);
  const currentRating = tile?.querySelector(".rating");
  if (!currentRating) {
    return;
  }
  currentRating.replaceWith(createRating(entry, false));
}

function updateZoom() {
  if (state.currentPhoto?.type === "video" || state.viewerLiveMode) {
    zoomResetBtn.textContent = "100%";
    imageStage.classList.remove("is-zoomed");
    viewerVideo.style.transform = "";
    return;
  }
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
  return state.entries.filter((entry) => entry.type === "photo" || entry.type === "video");
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

function startRapidNavigation(direction, pointerId = null) {
  if (!viewer.open || state.rapidNavDirection === direction) {
    return;
  }
  stopRapidNavigation(false);
  state.rapidNavDirection = direction;
  state.rapidNavPointerId = pointerId;
  state.rapidNavStarted = false;
  state.rapidNavSuppressClick = false;
  state.rapidNavDelay = 320;
  state.rapidNavTimer = window.setTimeout(() => runRapidNavigationStep(), 280);
}

function runRapidNavigationStep() {
  if (!state.rapidNavDirection || !viewer.open) {
    stopRapidNavigation(false);
    return;
  }
  state.rapidNavStarted = true;
  state.rapidNavSuppressClick = true;
  showAdjacentPhoto(state.rapidNavDirection);
  state.rapidNavDelay = Math.max(125, state.rapidNavDelay * 0.86);
  state.rapidNavTimer = window.setTimeout(() => runRapidNavigationStep(), state.rapidNavDelay);
}

function stopRapidNavigation(runCurrentLoad = true) {
  if (state.rapidNavTimer) {
    window.clearTimeout(state.rapidNavTimer);
    state.rapidNavTimer = null;
  }
  if (state.rapidNavStopTimer) {
    window.clearTimeout(state.rapidNavStopTimer);
    state.rapidNavStopTimer = null;
  }
  const wasRapid = state.rapidNavStarted;
  state.rapidNavDirection = 0;
  state.rapidNavPointerId = null;
  state.rapidNavStarted = false;
  state.rapidNavDelay = 0;
  if (runCurrentLoad && state.currentPhoto?.type === "photo") {
    scheduleCurrentOriginalLoad(state.currentPhoto);
    queueAdjacentOriginals();
  }
  if (wasRapid || state.rapidNavSuppressClick) {
    state.rapidNavSuppressClick = true;
    state.rapidNavStopTimer = window.setTimeout(() => {
      state.rapidNavSuppressClick = false;
      state.rapidNavStopTimer = null;
    }, 0);
  }
}

function updatePageButtons() {
  if (isViewerLocked()) {
    prevBtn.disabled = true;
    nextBtn.disabled = true;
    return;
  }
  const index = currentPhotoIndex();
  const last = photosOnly().length - 1;
  prevBtn.disabled = index <= 0;
  nextBtn.disabled = index < 0 || index >= last;
}

function isViewerLocked() {
  return deleteDialog.open || state.deleteInProgress;
}

function updateViewerControlsLock() {
  const locked = isViewerLocked();
  [closeBtn, prevBtn, nextBtn, livePhotoBtn, infoBtn, downloadBtn, deleteBtn, rotateBtn, viewerRatingBtn, zoomResetBtn].forEach((button) => {
    if (button) {
      button.disabled = locked;
    }
  });
  if (locked) {
    showViewerControls({ autoHide: false });
    setViewerRatingMenuOpen(false);
  }
  if (!locked) {
    updatePageButtons();
  }
}

function positionViewerRatingMenu() {
  if (viewerRatingMenu.hidden || viewerRatingBtn.hidden || !viewer.open) {
    return;
  }
  const buttonRect = viewerRatingBtn.getBoundingClientRect();
  const shellRect = viewer.querySelector(".viewer-shell")?.getBoundingClientRect() || viewer.getBoundingClientRect();
  const menuWidth = viewerRatingMenu.offsetWidth || 108;
  const menuHeight = viewerRatingMenu.offsetHeight || 0;
  const centerX = buttonRect.left + (buttonRect.width / 2) - shellRect.left;
  const minLeft = 12;
  const maxLeft = Math.max(minLeft, shellRect.width - menuWidth - 12);
  const left = Math.max(minLeft, Math.min(maxLeft, centerX - (menuWidth / 2)));
  const top = buttonRect.top - shellRect.top - menuHeight - 10;
  viewerRatingMenu.style.left = `${left}px`;
  viewerRatingMenu.style.top = `${Math.max(12, top)}px`;
}

function preloadAdjacentPreviews() {
  const photos = photosOnly();
  const index = currentPhotoIndex();
  [photos[index - 1], photos[index + 1]].forEach((entry) => {
    if (!entry) {
      return;
    }
    fetch(viewerPreviewStatusUrl(entry), { cache: "no-store" }).catch(() => {});
  });
}

function closeViewerAnimated() {
  if (!viewer.open) {
    state.viewerHistoryArmed = false;
    state.closingViewerFromHistory = false;
    exitViewerFullscreen();
    return;
  }
  stopRapidNavigation(false);
  cancelViewerOriginalLoads();
  const entry = state.currentPhoto;
  if (!entry) {
    finishViewerClose();
    return;
  }
  const sourceRect = getViewerDisplayRect();
  scrollGridToEntry(entry.path);
  if (!sourceRect || prefersReducedMotion()) {
    finishViewerClose();
    return;
  }
  requestAnimationFrame(() => {
    closeViewerAnimatedToGrid(entry, sourceRect);
  });
}

function closeViewerAnimatedToGrid(entry, sourceRect) {
  if (!viewer.open || state.currentPhoto?.path !== entry.path) {
    return;
  }
  const targetElement = getGridMediaElement(entry.path);
  const targetRect = targetElement ? targetElement.getBoundingClientRect() : null;
  if (!targetRect || !isRectVisible(targetRect)) {
    finishViewerClose();
    return;
  }

  const ghost = buildViewerTransitionGhost(entry, targetElement, true);
  if (!ghost) {
    finishViewerClose();
    return;
  }

  viewer.classList.add("is-transitioning");
  viewer.classList.remove("is-fading-out");
  document.body.append(ghost);
  setGhostRect(ghost, sourceRect);
  requestAnimationFrame(() => {
    ghost.classList.add("is-animating");
    setGhostRect(ghost, targetRect);
    viewer.classList.add("is-fading-out");
  });

  window.setTimeout(() => {
    ghost.remove();
    viewer.classList.remove("is-transitioning", "is-fading-out");
    finishViewerClose();
  }, VIEWER_TRANSITION_MS);
}

function startViewerEnterTransition(entry, originElement) {
  const sourceRect = originElement.getBoundingClientRect();
  const ghost = buildViewerTransitionGhost(entry, originElement, false);
  if (!ghost) {
    viewer.showModal();
    return;
  }
  const targetRect = getViewerTargetRect(originElement);
  viewer.classList.add("is-transitioning");
  viewer.classList.remove("is-fading-out");
  document.body.append(ghost);
  setGhostRect(ghost, sourceRect);
  viewer.showModal();
  enterViewerFullscreen();
  requestAnimationFrame(() => {
    ghost.classList.add("is-animating");
    setGhostRect(ghost, targetRect);
  });
  window.setTimeout(() => {
    ghost.remove();
    viewer.classList.remove("is-transitioning", "is-fading-out");
  }, VIEWER_TRANSITION_MS);
}

function buildViewerTransitionGhost(entry, referenceElement, fromViewer) {
  const ghost = document.createElement("div");
  ghost.className = "viewer-transition-ghost";
  if (entry.type === "video" || (fromViewer && state.viewerLiveMode)) {
    const icon = document.createElement("div");
    icon.className = "viewer-transition-video";
    icon.textContent = "▶";
    ghost.append(icon);
    return ghost;
  }

  const image = document.createElement("img");
  image.alt = "";
  image.draggable = false;
  image.src = fromViewer ? viewerImage.currentSrc || viewerImage.src : getTransitionImageSource(referenceElement, entry);
  if (!image.src) {
    return null;
  }
  ghost.append(image);
  return ghost;
}

function getTransitionImageSource(referenceElement, entry) {
  const image = referenceElement.querySelector("img");
  if (image?.currentSrc || image?.src) {
    return image.currentSrc || image.src;
  }
  return entry.previewUrl || entry.thumbUrl || entry.originalUrl || "";
}

function getViewerTargetRect(referenceElement) {
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const maxWidth = viewportWidth * 0.82;
  const maxHeight = viewportHeight * 0.82;
  const rect = referenceElement.getBoundingClientRect();
  const aspectRatio = getReferenceAspectRatio(referenceElement);
  let width = maxWidth;
  let height = width / aspectRatio;
  if (height > maxHeight) {
    height = maxHeight;
    width = height * aspectRatio;
  }
  return {
    left: (viewportWidth - width) / 2,
    top: (viewportHeight - height) / 2,
    width,
    height,
  };
}

function getReferenceAspectRatio(referenceElement) {
  const image = referenceElement.querySelector("img");
  if (image?.naturalWidth && image?.naturalHeight) {
    return image.naturalWidth / image.naturalHeight;
  }
  const rect = referenceElement.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0 ? rect.width / rect.height : 1;
}

function getGridMediaElement(path) {
  return document.querySelector(`.tile[data-path="${CSS.escape(path)}"] .thumb-holder`);
}

function scrollGridToEntry(path) {
  const tile = document.querySelector(`.tile[data-path="${CSS.escape(path)}"]`);
  if (!tile) {
    return;
  }
  tile.scrollIntoView({ block: "center", inline: "nearest", behavior: "auto" });
  scheduleVisibleWorkScan();
}

function getViewerDisplayRect() {
  if ((state.currentPhoto?.type === "video" || state.viewerLiveMode) && !viewerVideo.hidden) {
    return viewerVideo.getBoundingClientRect();
  }
  if (!viewerImage.hidden && (viewerImage.currentSrc || viewerImage.src)) {
    return viewerImage.getBoundingClientRect();
  }
  return null;
}

function setGhostRect(element, rect) {
  element.style.left = `${rect.left}px`;
  element.style.top = `${rect.top}px`;
  element.style.width = `${rect.width}px`;
  element.style.height = `${rect.height}px`;
}

function isRectVisible(rect) {
  return rect.bottom > 0 && rect.right > 0 && rect.top < window.innerHeight && rect.left < window.innerWidth;
}

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
