async function loadThumbnail(entry, img, spinner, attempt = 0, mode = state.thumbMode) {
  if (!img.isConnected || mode !== state.thumbMode) {
    return;
  }
  const requestKey = `${entry.path}:${mode}:${attempt}:${Date.now()}`;
  const controller = new AbortController();
  state.thumbControllers.set(requestKey, controller);
  try {
    const response = await fetch(`/api/thumb-status/${encodePath(entry.path)}?mode=${mode}`, {
      cache: "no-store",
      signal: controller.signal,
    });
    const data = await response.json();
    if (!img.isConnected || mode !== state.thumbMode) {
      return;
    }
    if (response.status === 200) {
      img.loading = "eager";
      img.fetchPriority = "high";
      img.onload = () => {
        img.classList.add("loaded");
        spinner.hidden = true;
        entry.thumbUrl = img.src;
        scheduleNeighborThumbnailPrefetch();
      };
      img.onerror = () => {
        showThumbnailFallback(entry, img, spinner);
      };
      img.src = withVersion(data.url, entry.mtime);
      if (img.complete && img.naturalWidth > 0) {
        img.classList.add("loaded");
        spinner.hidden = true;
        entry.thumbUrl = img.src;
        scheduleNeighborThumbnailPrefetch();
      }
      return;
    }
    if (response.status !== 202) {
      showThumbnailFallback(entry, img, spinner);
      return;
    }
  } catch {
    if (!controller.signal.aborted) {
      scheduleThumbnailRetry(entry, img, spinner, attempt, mode);
    }
    return;
  } finally {
    state.thumbControllers.delete(requestKey);
  }

  scheduleThumbnailRetry(entry, img, spinner, attempt, mode);
}

function scheduleThumbnailRetry(entry, img, spinner, attempt, mode) {
  if (!img.isConnected || mode !== state.thumbMode) {
    return;
  }
  if (attempt >= 8) {
    if (isThumbnailStillNeeded(img)) {
      scheduleThumbnailRequeue(entry, img, spinner, mode);
      return;
    }
    showThumbnailFallback(entry, img, spinner);
    return;
  }
  const delay = Math.min(3000, 450 + attempt * 250);
  const timer = window.setTimeout(() => {
    state.thumbTimers.delete(entry.path);
    queueThumbnail(entry, img, spinner, attempt + 1);
  }, delay);
  state.thumbTimers.set(entry.path, timer);
}

function showThumbnailFallback(entry, img, spinner) {
  if (entry.browserRenderable === false) {
    if (isThumbnailStillNeeded(img)) {
      scheduleThumbnailRequeue(entry, img, spinner, state.thumbMode);
      return;
    }
    spinner.classList.add("failed");
    return;
  }
  img.loading = "eager";
  img.fetchPriority = "high";
  img.onload = () => {
    img.classList.add("loaded");
    spinner.hidden = true;
    entry.thumbUrl = img.src;
    scheduleNeighborThumbnailPrefetch();
  };
  img.onerror = () => {
    if (isThumbnailStillNeeded(img)) {
      scheduleThumbnailRequeue(entry, img, spinner, state.thumbMode);
      return;
    }
    spinner.classList.add("failed");
  };
  img.src = `/api/image/${encodePath(entry.path)}`;
  if (img.complete && img.naturalWidth > 0) {
    img.classList.add("loaded");
    spinner.hidden = true;
    entry.thumbUrl = img.src;
    scheduleNeighborThumbnailPrefetch();
  }
}

function isThumbnailStillNeeded(img) {
  const holder = img.closest(".thumb-holder");
  return Boolean(holder && img.isConnected && !img.classList.contains("loaded") && isNearViewport(holder, 420));
}

function scheduleThumbnailRequeue(entry, img, spinner, mode) {
  if (!img.isConnected || mode !== state.thumbMode || img.classList.contains("loaded")) {
    return;
  }
  spinner.hidden = false;
  spinner.classList.remove("failed");
  const key = `${entry.path}:requeue`;
  if (state.thumbTimers.has(key)) {
    return;
  }
  const timer = window.setTimeout(() => {
    state.thumbTimers.delete(key);
    if (isThumbnailStillNeeded(img) && mode === state.thumbMode) {
      img.removeAttribute("src");
      queueThumbnail(entry, img, spinner, 0);
    }
  }, 700);
  state.thumbTimers.set(key, timer);
}

function getStoredThumbMode() {
  const value = window.localStorage.getItem("thumbMode");
  return THUMB_MODES.includes(value) ? value : "medium";
}

function setThumbMode(mode) {
  if (!THUMB_MODES.includes(mode) || mode === state.thumbMode) {
    return;
  }
  state.thumbMode = mode;
  window.localStorage.setItem("thumbMode", mode);
  renderGrid();
}

function withVersion(url, mtime) {
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}v=${mtime}`;
}

function observeThumbnail(entry, img, spinner, index = -1) {
  if (!state.thumbObserver) {
    state.thumbObserver = new IntersectionObserver(
      (items) => {
        items.forEach((item) => {
          if (!item.isIntersecting) {
            state.visibleThumbHolders.delete(item.target);
            return;
          }
          state.visibleThumbHolders.add(item.target);
          const payload = item.target.__thumbPayload;
          if (payload) {
            queueThumbnail(payload.entry, payload.img, payload.spinner);
            scheduleNeighborThumbnailPrefetch();
          }
        });
      },
      { rootMargin: "360px 0px" },
    );
  }
  img.parentElement.__thumbPayload = { entry, img, spinner, index };
  state.thumbPayloads.set(entry.path, { entry, img, spinner, index });
  state.thumbObserver.observe(img.parentElement);
}

function isNearViewport(element, margin) {
  const rect = element.getBoundingClientRect();
  return rect.bottom >= -margin && rect.top <= window.innerHeight + margin;
}

function scanVisibleWork() {
  state.visibleScanTimer = null;
  for (const holder of Array.from(state.visibleThumbHolders)) {
    if (!holder.isConnected) {
      state.visibleThumbHolders.delete(holder);
      continue;
    }
    const payload = holder.__thumbPayload;
    if (payload) {
      queueThumbnail(payload.entry, payload.img, payload.spinner);
    }
  }
  for (const ratingWrap of Array.from(state.visibleRatingWraps)) {
    if (!ratingWrap.isConnected) {
      state.visibleRatingWraps.delete(ratingWrap);
      continue;
    }
    const payload = ratingWrap.__ratingPayload;
    if (payload) {
      queueEmbeddedRating(payload.entry, payload.ratingWrap);
    }
  }
  scheduleNeighborThumbnailPrefetch();
}

function scheduleVisibleWorkScan() {
  if (state.visibleScanTimer) {
    return;
  }
  state.visibleScanTimer = window.setTimeout(scanVisibleWork, 80);
}

function queueThumbnail(entry, img, spinner, attempt = 0, options = {}) {
  if (!img.isConnected || img.classList.contains("loaded")) {
    return;
  }
  const key = `${entry.path}:${state.thumbMode}`;
  if (state.thumbActiveKeys.has(key)) {
    return;
  }
  if (state.thumbQueued.has(key)) {
    if (options.priority === "neighbor") {
      return;
    }
    state.thumbQueue = state.thumbQueue.filter((item) => item.key !== key);
  }
  spinner.hidden = false;
  spinner.classList.remove("failed");
  state.thumbQueued.add(key);
  const payload = {
    entry,
    img,
    spinner,
    attempt,
    mode: state.thumbMode,
    key,
    priority: options.priority || "visible",
  };
  if (options.priority === "neighbor") {
    state.thumbQueue.push(payload);
  } else {
    state.thumbQueue.unshift(payload);
  }
  trimThumbQueue();
  runThumbQueue();
}

function trimThumbQueue() {
  const limit = THUMB_QUEUE_LIMITS[state.thumbMode] || THUMB_QUEUE_LIMITS.medium;
  while (state.thumbQueue.length > limit) {
    const dropIndex = findDroppableThumbQueueIndex();
    if (dropIndex < 0) {
      return;
    }
    const dropped = state.thumbQueue.splice(dropIndex, 1)[0];
    state.thumbQueued.delete(dropped.key);
  }
}

function findDroppableThumbQueueIndex() {
  for (let index = state.thumbQueue.length - 1; index >= 0; index -= 1) {
    const item = state.thumbQueue[index];
    if (item.priority === "neighbor" && !isQueuedThumbnailProtected(item)) {
      return index;
    }
  }
  for (let index = state.thumbQueue.length - 1; index >= 0; index -= 1) {
    const item = state.thumbQueue[index];
    if (!isQueuedThumbnailProtected(item)) {
      return index;
    }
  }
  return -1;
}

function isQueuedThumbnailProtected(item) {
  if (!item?.img?.isConnected || item.img.classList.contains("loaded") || item.mode !== state.thumbMode) {
    return false;
  }
  const holder = item.img.closest(".thumb-holder");
  return Boolean(holder && isNearViewport(holder, 0));
}

function runThumbQueue() {
  while (state.thumbActive < THUMB_LOAD_CONCURRENCY && state.thumbQueue.length > 0) {
    const payload = state.thumbQueue.shift();
    state.thumbQueued.delete(payload.key);
    if (
      !payload.img.isConnected
      || payload.img.classList.contains("loaded")
      || payload.mode !== state.thumbMode
      || state.thumbActiveKeys.has(payload.key)
    ) {
      continue;
    }
    state.thumbActive += 1;
    state.thumbActiveKeys.add(payload.key);
    loadThumbnail(payload.entry, payload.img, payload.spinner, payload.attempt, payload.mode)
      .catch(() => null)
      .finally(() => {
        state.thumbActiveKeys.delete(payload.key);
        state.thumbActive = Math.max(0, state.thumbActive - 1);
        if (isThumbnailStillNeeded(payload.img)) {
          scheduleThumbnailRequeue(payload.entry, payload.img, payload.spinner, payload.mode);
        }
        scheduleNeighborThumbnailPrefetch();
        runThumbQueue();
      });
  }
}

function scheduleNeighborThumbnailPrefetch() {
  if (state.thumbNeighborPrefetchTimer) {
    return;
  }
  state.thumbNeighborPrefetchTimer = window.setTimeout(() => {
    state.thumbNeighborPrefetchTimer = null;
    prefetchNeighborThumbnails();
  }, 120);
}

function prefetchNeighborThumbnails() {
  const visible = visibleLoadedThumbnailRange();
  if (!visible) {
    state.thumbNeighborPrefetchKey = "";
    dropQueuedNeighborThumbnails();
    return;
  }
  const key = `${state.thumbMode}:${visible.first}:${visible.last}`;
  if (key !== state.thumbNeighborPrefetchKey) {
    state.thumbNeighborPrefetchKey = key;
    dropQueuedNeighborThumbnails();
  }
  const paths = neighborThumbnailPaths(visible.first, visible.last, 20);
  paths.forEach((path) => {
    const payload = state.thumbPayloads.get(path);
    if (!payload || payload.img.classList.contains("loaded")) {
      return;
    }
    queueThumbnail(payload.entry, payload.img, payload.spinner, 0, { priority: "neighbor" });
  });
}

function dropQueuedNeighborThumbnails() {
  state.thumbQueue = state.thumbQueue.filter((item) => {
    if (item.priority !== "neighbor") {
      return true;
    }
    state.thumbQueued.delete(item.key);
    return false;
  });
}

function visibleLoadedThumbnailRange() {
  let first = Infinity;
  let last = -1;
  for (const holder of Array.from(state.visibleThumbHolders)) {
    if (!holder.isConnected) {
      state.visibleThumbHolders.delete(holder);
      continue;
    }
    if (!isNearViewport(holder, 0)) {
      continue;
    }
    const payload = holder.__thumbPayload;
    if (!payload) {
      continue;
    }
    if (!payload.img.classList.contains("loaded")) {
      return null;
    }
    const index = Number.isInteger(payload.index) ? payload.index : state.entries.findIndex((entry) => qualifyPath(entry.path) === payload.entry.path);
    if (index < 0) {
      continue;
    }
    first = Math.min(first, index);
    last = Math.max(last, index);
  }
  if (!Number.isFinite(first) || last < first) {
    return null;
  }
  return { first, last };
}

function neighborThumbnailPaths(first, last, radius) {
  const paths = [];
  let beforeCount = 0;
  for (let index = first - 1; index >= 0 && beforeCount < radius; index -= 1) {
    const entry = state.entries[index];
    if (entry?.type === "photo") {
      paths.push(qualifyPath(entry.path));
      beforeCount += 1;
    }
  }
  let afterCount = 0;
  for (let index = last + 1; index < state.entries.length && afterCount < radius; index += 1) {
    const entry = state.entries[index];
    if (entry?.type === "photo") {
      paths.push(qualifyPath(entry.path));
      afterCount += 1;
    }
  }
  return paths;
}

function resetThumbObserver() {
  if (state.thumbObserver) {
    state.thumbObserver.disconnect();
    state.thumbObserver = null;
  }
  state.visibleThumbHolders.clear();
  state.thumbPayloads.clear();
  state.thumbNeighborPrefetchKey = "";
}

function clearThumbTimers() {
  for (const timer of state.thumbTimers.values()) {
    window.clearTimeout(timer);
  }
  state.thumbTimers.clear();
  state.thumbQueue = [];
  state.thumbQueued.clear();
  state.thumbActiveKeys.clear();
  if (state.thumbNeighborPrefetchTimer) {
    window.clearTimeout(state.thumbNeighborPrefetchTimer);
    state.thumbNeighborPrefetchTimer = null;
  }
  for (const controller of state.thumbControllers.values()) {
    controller.abort();
  }
  state.thumbControllers.clear();
}

function clearRatingTimers() {
  for (const timer of state.ratingTimers.values()) {
    window.clearTimeout(timer);
  }
  state.ratingTimers.clear();
  state.ratingQueue = [];
  state.ratingQueued.clear();
}

function clearVisibleWorkScan() {
  if (state.visibleScanTimer) {
    window.clearTimeout(state.visibleScanTimer);
    state.visibleScanTimer = null;
  }
}

function resetRatingObserver() {
  if (state.ratingObserver) {
    state.ratingObserver.disconnect();
    state.ratingObserver = null;
  }
  state.visibleRatingWraps.clear();
}

