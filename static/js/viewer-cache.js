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


