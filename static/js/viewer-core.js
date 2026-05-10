const VIEWER_TRANSITION_MS = 260;

function openViewer(entry, originElement = null) {
  showPhoto(entry);
  armViewerHistory();
  if (!originElement || prefersReducedMotion()) {
    viewer.showModal();
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

function showPhoto(entry) {
  if (!entry || (entry.type !== "photo" && entry.type !== "video")) {
    return;
  }
  state.viewerGeneration += 1;
  state.viewerLiveMode = false;
  cancelStaleOriginalLoads(entry.type === "photo" ? entry.path : null);
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
    updatePageButtons();
    updateZoom();
    updateDownloadButton();
    return;
  }

  viewerImage.hidden = false;

  if (entry.originalUrl) {
    viewerImage.classList.remove("loading");
    viewerImage.onload = () => viewerImage.classList.add("ready");
    viewerImage.src = entry.originalUrl;
    renderViewerRating();
    updatePageButtons();
    updateZoom();
    updateDownloadButton();
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
  updateZoom();
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
  if (state.currentPhoto?.path === entry.path) {
    scheduleCurrentOriginalLoad(entry);
  }
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
    removeGridEntry(entry);
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
  [closeBtn, prevBtn, nextBtn, livePhotoBtn, downloadBtn, deleteBtn, rotateBtn, viewerRatingBtn, zoomResetBtn].forEach((button) => {
    if (button) {
      button.disabled = locked;
    }
  });
  if (locked) {
    setViewerRatingMenuOpen(false);
  }
  if (!locked) {
    updatePageButtons();
  }
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

function closeViewerAnimated() {
  if (!viewer.open) {
    state.viewerHistoryArmed = false;
    state.closingViewerFromHistory = false;
    return;
  }
  stopRapidNavigation(false);
  cancelStaleOriginalLoads();
  const entry = state.currentPhoto;
  if (!entry || prefersReducedMotion()) {
    state.viewerHistoryArmed = false;
    state.closingViewerFromHistory = false;
    viewer.close();
    return;
  }
  const sourceRect = getViewerDisplayRect();
  const targetElement = getGridMediaElement(entry.path);
  const targetRect = targetElement ? targetElement.getBoundingClientRect() : null;
  if (!sourceRect || !targetRect || !isRectVisible(targetRect)) {
    state.viewerHistoryArmed = false;
    state.closingViewerFromHistory = false;
    viewer.close();
    return;
  }

  const ghost = buildViewerTransitionGhost(entry, targetElement, true);
  if (!ghost) {
    state.viewerHistoryArmed = false;
    state.closingViewerFromHistory = false;
    viewer.close();
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
    state.viewerHistoryArmed = false;
    state.closingViewerFromHistory = false;
    viewer.close();
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
