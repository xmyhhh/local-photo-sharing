async function deleteCurrentPhoto() {
  if (!state.currentPhoto) {
    return;
  }
  const entry = state.currentPhoto;
  const mediaEntries = photosOnly();
  const index = mediaEntries.findIndex((item) => item.path === entry.path);
  const nextEntry = index >= 0 ? mediaEntries[index + 1] || mediaEntries[index - 1] || null : null;

  await fetchJson(`/api/photo/${encodePath(entry.path)}`, { method: "DELETE" });

  state.entries = state.entries.filter((item) => item.path !== entry.path);
  renderGrid();

  if (nextEntry) {
    showPhoto(nextEntry);
    return;
  }

  state.currentPhoto = null;
  closeViewerFromUi();
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



