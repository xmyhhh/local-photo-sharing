function queueAdjacentOriginals() {
  state.originalPrefetchQueue = [];
  if (state.rapidNavDirection) {
    return;
  }
  const photos = photosOnly();
  const index = currentPhotoIndex();
  const candidates = [
    photos[index + 1],
    photos[index - 1],
    photos[index + 2],
    photos[index - 2],
    photos[index + 3],
    photos[index - 3],
  ].filter(Boolean);

  candidates.forEach((entry) => queueOriginalPrefetch(entry));
  runOriginalPrefetchQueue();
}

function queueOriginalPrefetch(entry) {
  if (entry.browserRenderable === false) {
    return;
  }
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
  if (state.rapidNavDirection) {
    return;
  }
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

function scheduleCurrentOriginalLoad(entry) {
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

function cancelStaleOriginalLoads(keepPath = null) {
  state.originalPrefetchQueue = [];
  for (const [path, controller] of state.originalControllers.entries()) {
    if (path !== keepPath) {
      controller.abort();
    }
  }
}

async function loadOriginalImage(entry, forceDisplay = false, generation = state.viewerGeneration) {
  if (entry.type !== "photo") {
    return null;
  }
  if (entry.browserRenderable === false) {
    return null;
  }
  const cached = getOriginalCache(entry.path);
  if (cached) {
    if (forceDisplay || state.currentPhoto?.path === entry.path) {
      showOriginalUrl(entry, cached.url);
    }
    return cached.url;
  }
  if (state.originalFetches.has(entry.path)) {
    const url = await state.originalFetches.get(entry.path);
    if ((forceDisplay || state.currentPhoto?.path === entry.path) && url && state.viewerGeneration === generation) {
      showOriginalUrl(entry, url);
    }
    return url;
  }

  if (forceDisplay) {
    cancelStaleOriginalLoads(entry.path);
  }
  const controller = new AbortController();
  state.originalControllers.set(entry.path, controller);
  const promise = fetch(`/api/image/${encodePath(entry.path)}`, { signal: controller.signal })
    .then((response) => {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      return response.blob();
    })
    .then(async (blob) => {
      const url = URL.createObjectURL(blob);
      const decoded = await decodeImageUrl(url);
      putOriginalCache(entry.path, url, blob.size, decoded);
      return url;
    })
    .catch(() => null)
    .finally(() => {
      state.originalFetches.delete(entry.path);
      state.originalControllers.delete(entry.path);
    });
  state.originalFetches.set(entry.path, promise);
  const url = await promise;
  if ((forceDisplay || state.currentPhoto?.path === entry.path) && url && state.viewerGeneration === generation) {
    showOriginalUrl(entry, url);
  }
  return url;
}

function showOriginalUrl(entry, url) {
  if (entry.type !== "photo" || state.currentPhoto?.path !== entry.path) {
    return;
  }
  const cached = getOriginalCache(entry.path);
  const decoded = cached?.url === url && cached.decoded;
  entry.originalReady = true;
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

function putOriginalCache(path, url, bytes, decoded = false) {
  const existing = state.originalCache.get(path);
  if (existing) {
    state.originalCacheBytes -= existing.bytes;
    URL.revokeObjectURL(existing.url);
    state.originalCache.delete(path);
  }
  state.originalCache.set(path, { url, bytes, decoded, lastUsed: Date.now() });
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
  cancelStaleOriginalLoads();
  for (const item of state.originalCache.values()) {
    URL.revokeObjectURL(item.url);
  }
  state.originalCache.clear();
  state.originalCacheBytes = 0;
});


