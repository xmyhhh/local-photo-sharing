function queueAdjacentOriginals() {
  state.originalPrefetchQueue = [];
  if (state.rapidNavDirection) {
    return;
  }
  if (!state.clientPrefetch.enabled || !state.clientPrefetch.originalPreviewEnabled) {
    updateServerMemoryPrefetch();
    return;
  }
  const photos = photosOnly();
  const index = currentPhotoIndex();
  const candidates = [
    ...Array.from({ length: state.clientPrefetch.originalForward }, (_, offset) => photos[index + offset + 1]),
    ...Array.from({ length: state.clientPrefetch.originalBackward }, (_, offset) => photos[index - offset - 1]),
  ].filter(Boolean);

  candidates.forEach((entry) => queueOriginalPrefetch(entry));
  runOriginalPrefetchQueue();
  updateServerMemoryPrefetch();
}

function getMemoryPrefetchClientId() {
  if (!state.memoryPrefetchClientId) {
    const random = window.crypto?.randomUUID ? window.crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
    state.memoryPrefetchClientId = `client-${random}`;
  }
  return state.memoryPrefetchClientId;
}

function updateServerMemoryPrefetch() {
  if (!state.currentPhoto || state.currentPhoto.type !== "photo") {
    return;
  }
  const photos = photosOnly().filter((entry) => entry.type === "photo" && entry.browserRenderable !== false);
  const index = photos.findIndex((entry) => entry.path === state.currentPhoto.path);
  if (index < 0) {
    return;
  }
  const start = Math.max(0, index - state.memoryPrefetchWindowBefore);
  const end = Math.min(photos.length, index + state.memoryPrefetchWindowAfter + 1);
  const paths = photos.slice(start, end).map((entry) => entry.path);
  fetch("/api/prefetch/originals", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ clientId: getMemoryPrefetchClientId(), paths }),
  }).catch(() => null);
}

function releaseServerMemoryPrefetch(useBeacon = false) {
  if (!state.memoryPrefetchClientId) {
    return;
  }
  const body = JSON.stringify({ clientId: state.memoryPrefetchClientId });
  if (useBeacon && navigator.sendBeacon) {
    navigator.sendBeacon("/api/prefetch/release", new Blob([body], { type: "application/json" }));
    return;
  }
  fetch("/api/prefetch/release", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    keepalive: true,
  }).catch(() => null);
}

function queueOriginalPrefetch(entry) {
  if (!state.clientPrefetch.enabled || !state.clientPrefetch.originalPreviewEnabled || state.clientPrefetch.originalQueueLimit <= 0) {
    return;
  }
  if (entry.browserRenderable === false) {
    return;
  }
  const entryKey = originalEntryKey(entry);
  if (getOriginalCache(entry) || state.originalFetches.has(entryKey)) {
    return;
  }
  if (state.originalPrefetchQueue.some((item) => originalEntryKey(item) === entryKey)) {
    return;
  }
  state.originalPrefetchQueue.push(entry);
  while (state.originalPrefetchQueue.length > state.clientPrefetch.originalQueueLimit) {
    state.originalPrefetchQueue.pop();
  }
}

function runOriginalPrefetchQueue() {
  if (!viewer.open || state.rapidNavDirection || !state.clientPrefetch.enabled || !state.clientPrefetch.originalPreviewEnabled) {
    return;
  }
  while (
    state.originalPrefetchActive < state.clientPrefetch.originalConcurrency
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

function scheduleCurrentOriginalLoad(entry) {
  if (!state.clientPrefetch.originalPreviewEnabled) {
    return;
  }
  if (state.originalLoadTimer) {
    window.clearTimeout(state.originalLoadTimer);
    state.originalLoadTimer = null;
  }
  const generation = state.viewerGeneration;
  const delay = state.rapidNavDirection ? 180 : 0;
  state.originalLoadTimer = window.setTimeout(() => {
    state.originalLoadTimer = null;
    if (state.currentPhoto?.path === entry.path && state.viewerGeneration === generation) {
      loadOriginalImage(entry, true, generation);
    }
  }, delay);
}

function cancelStaleOriginalLoads(keepKey = null) {
  if (state.originalLoadTimer) {
    window.clearTimeout(state.originalLoadTimer);
    state.originalLoadTimer = null;
  }
  state.originalPrefetchQueue = [];
  for (const [key, controller] of state.originalControllers.entries()) {
    if (key !== keepKey) {
      controller.abort();
    }
  }
}

function cancelViewerOriginalLoads() {
  state.viewerGeneration += 1;
  cancelStaleOriginalLoads();
}

function cancelClientOriginalPrefetches() {
  const keepKey = state.currentPhoto ? originalEntryKey(state.currentPhoto) : null;
  state.originalPrefetchQueue = [];
  for (const [key, controller] of state.originalControllers.entries()) {
    if (key !== keepKey) {
      controller.abort();
    }
  }
}

async function loadOriginalImage(entry, forceDisplay = false, generation = state.viewerGeneration) {
  if (forceDisplay && !state.clientPrefetch.originalPreviewEnabled) {
    return null;
  }
  if (entry.type !== "photo") {
    return null;
  }
  if (entry.browserRenderable === false) {
    return null;
  }
  const entryKey = originalEntryKey(entry);
  const cached = getOriginalCache(entry);
  if (cached) {
    if (forceDisplay || state.currentPhoto?.path === entry.path) {
      showOriginalUrl(entry, cached.url);
    }
    return cached.url;
  }
  if (state.originalFetches.has(entryKey)) {
    const url = await state.originalFetches.get(entryKey);
    if ((forceDisplay || state.currentPhoto?.path === entry.path) && url && state.viewerGeneration === generation) {
      showOriginalUrl(entry, url);
    }
    return url;
  }

  if (forceDisplay) {
    cancelStaleOriginalLoads(entryKey);
  }
  const controller = new AbortController();
  state.originalControllers.set(entryKey, controller);
  const promise = fetch(versionedMediaUrl(entry), { signal: controller.signal })
    .then((response) => {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      return response.blob();
    })
    .then(async (blob) => {
      const url = URL.createObjectURL(blob);
      const decoded = await decodeImageUrl(url);
      putOriginalCache(entry, url, blob.size, decoded);
      return url;
    })
    .catch(() => null)
    .finally(() => {
      state.originalFetches.delete(entryKey);
      state.originalControllers.delete(entryKey);
    });
  state.originalFetches.set(entryKey, promise);
  const url = await promise;
  if ((forceDisplay || state.currentPhoto?.path === entry.path) && url && state.viewerGeneration === generation) {
    showOriginalUrl(entry, url);
  }
  return url;
}

function showOriginalUrl(entry, url) {
  if (!viewer.open || entry.type !== "photo" || state.currentPhoto?.path !== entry.path) {
    return;
  }
  const cached = getOriginalCache(entry);
  const decoded = cached?.url === url && cached.decoded;
  entry.originalReady = true;
  entry.originalUrl = url;
  viewerImage.classList.remove("loading");
  if (!decoded) {
    viewerImage.classList.remove("ready");
  }
  viewerImage.onload = () => viewerImage.classList.add("ready");
  viewerImage.src = url;
  if (viewerImage.complete && viewerImage.naturalWidth > 0) {
    viewerImage.classList.add("ready");
  }
  queueAdjacentOriginals();
}

function originalEntryKey(entry) {
  return `${entry.path}:${entry.mtime || ""}`;
}

function getOriginalCache(entry) {
  const key = originalEntryKey(entry);
  const item = state.originalCache.get(key);
  if (!item) {
    return null;
  }
  item.lastUsed = Date.now();
  state.originalCache.delete(key);
  state.originalCache.set(key, item);
  return item;
}

function deleteOriginalCacheKey(key) {
  const item = state.originalCache.get(key);
  if (!item) {
    return;
  }
  state.originalCacheBytes -= item.bytes;
  URL.revokeObjectURL(item.url);
  state.originalCache.delete(key);
}

async function decodeImageUrl(url) {
  const image = new Image();
  image.decoding = "async";
  image.src = url;
  try {
    if (image.decode) {
      await image.decode();
    } else if (!image.complete) {
      await new Promise((resolve, reject) => {
        image.onload = resolve;
        image.onerror = reject;
      });
    }
    return true;
  } catch {
    return false;
  }
}

function putOriginalCache(entry, url, bytes, decoded = false) {
  const key = originalEntryKey(entry);
  const existing = state.originalCache.get(key);
  if (existing) {
    state.originalCacheBytes -= existing.bytes;
    URL.revokeObjectURL(existing.url);
    state.originalCache.delete(key);
  }
  state.originalCache.set(key, { url, bytes, decoded, lastUsed: Date.now() });
  state.originalCacheBytes += bytes;
  trimOriginalCache();
}

function trimOriginalCache() {
  while (
    (state.originalCacheBytes > ORIGINAL_CACHE_BYTES_LIMIT || state.originalCache.size > ORIGINAL_CACHE_COUNT_LIMIT)
    && state.originalCache.size > 0
  ) {
    const [path, item] = state.originalCache.entries().next().value;
    URL.revokeObjectURL(item.url);
    state.originalCacheBytes -= item.bytes;
    state.originalCache.delete(path);
  }
}

window.addEventListener("beforeunload", () => {
  releaseServerMemoryPrefetch(true);
  cancelStaleOriginalLoads();
  for (const item of state.originalCache.values()) {
    URL.revokeObjectURL(item.url);
  }
  state.originalCache.clear();
  state.originalCacheBytes = 0;
});


