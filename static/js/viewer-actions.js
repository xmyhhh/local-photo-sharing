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



