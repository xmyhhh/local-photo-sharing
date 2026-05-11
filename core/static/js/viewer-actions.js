async function deleteCurrentPhoto() {
  if (!state.currentPhoto) {
    return;
  }
  state.deleteInProgress = true;
  updateViewerControlsLock();
  const entry = state.currentPhoto;
  const mediaEntries = photosOnly();
  const index = mediaEntries.findIndex((item) => item.path === entry.path);
  const nextEntry = index >= 0 ? mediaEntries[index + 1] || mediaEntries[index - 1] || null : null;

  try {
    releaseCurrentVideo();
    await fetchJson(`/api/photo/${encodePath(entry.path)}`, { method: "DELETE" });

    state.entries = state.entries.filter((item) => item.path !== entry.path);
    renderGrid();

    if (nextEntry) {
      showPhoto(nextEntry);
      return;
    }

    state.currentPhoto = null;
    closeViewerFromUi();
  } finally {
    state.deleteInProgress = false;
    updateViewerControlsLock();
  }
}

async function rotateCurrentPhoto() {
  const entry = state.currentPhoto;
  if (!entry || entry.type !== "photo" || state.viewerLiveMode) {
    return;
  }
  rotateBtn.disabled = true;
  try {
    const updated = await fetchJson(`/api/rotate/${encodePath(entry.path)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ direction: "right" }),
    });
    entry.mtime = updated.mtime;
    entry.originalUrl = "";
    entry.previewUrl = "";
    entry.originalReady = false;
    state.originalCache.delete(entry.path);
    state.originalFetches.delete(entry.path);
    state.viewerGeneration += 1;
    cancelStaleOriginalLoads();
    viewerImage.classList.remove("ready");
    viewerImage.classList.add("loading");
    viewerImage.onload = () => {
      viewerImage.classList.remove("loading");
      viewerImage.classList.add("ready");
      entry.originalReady = true;
    };
    viewerImage.src = `${updated.imageUrl}?v=${updated.mtime}`;
    renderGrid();
  } finally {
    rotateBtn.disabled = false;
  }
}

function requestDeleteCurrentPhoto() {
  if (!state.currentPhoto) {
    return;
  }
  deleteDialogMode.textContent = deleteModeMessage();
  deleteDialogPath.textContent = state.currentPhoto.path;
  deleteDialog.showModal();
  updateViewerControlsLock();
}

function recycleBinEnabled() {
  return state.enabledPlugins?.has("recycle_bin");
}

function deleteModeMessage() {
  return recycleBinEnabled()
    ? "回收站已启用：删除后会放入回收站，可在回收站中还原。"
    : "回收站未启用：删除后会直接永久删除，无法撤销。";
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
      type: blob.type || (entry.type === "video" ? "video/mp4" : "image/jpeg"),
      lastModified: Date.now(),
    });

    if (navigator.share && (!navigator.canShare || navigator.canShare({ files: [file] }))) {
      await navigator.share({
        files: [file],
        title: entry.name,
        text: entry.type === "video" ? "保存视频" : "保存原图",
      });
      return;
    }
  } catch {
    // Fall through to the long-press guidance below.
  }

  window.alert(entry.type === "video" ? "请使用系统分享或浏览器下载功能保存当前视频。" : "请长按当前图片，然后点“存储到照片”或“存储图像”。");
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

function releaseCurrentVideo() {
  viewerVideo.pause();
  viewerVideo.hidden = true;
  viewerVideo.removeAttribute("src");
  viewerVideo.load();
  state.viewerLiveMode = false;
}



