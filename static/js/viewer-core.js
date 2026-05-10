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


