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
      };
      img.onerror = () => {
        showThumbnailFallback(entry, img, spinner);
      };
      img.src = withVersion(data.url, entry.mtime);
      if (img.complete && img.naturalWidth > 0) {
        img.classList.add("loaded");
        spinner.hidden = true;
        entry.thumbUrl = img.src;
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
  img.loading = "eager";
  img.fetchPriority = "high";
  img.onload = () => {
    img.classList.add("loaded");
    spinner.hidden = true;
    entry.thumbUrl = img.src;
  };
  img.onerror = () => {
    spinner.classList.add("failed");
  };
  img.src = `/api/image/${encodePath(entry.path)}`;
  if (img.complete && img.naturalWidth > 0) {
    img.classList.add("loaded");
    spinner.hidden = true;
    entry.thumbUrl = img.src;
  }
}

function getStoredThumbMode() {
  const value = window.localStorage.getItem("thumbMode");
  return ["small", "medium", "large"].includes(value) ? value : "medium";
}

function setThumbMode(mode) {
  if (!["small", "medium", "large"].includes(mode) || mode === state.thumbMode) {
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

function observeThumbnail(entry, img, spinner) {
  if (!state.thumbObserver) {
    state.thumbObserver = new IntersectionObserver(
      (items) => {
        items.forEach((item) => {
          if (!item.isIntersecting) {
            return;
          }
          const payload = item.target.__thumbPayload;
          if (payload) {
            queueThumbnail(payload.entry, payload.img, payload.spinner);
          }
        });
      },
      { rootMargin: "360px 0px" },
    );
  }
  img.parentElement.__thumbPayload = { entry, img, spinner };
  state.thumbObserver.observe(img.parentElement);
  if (isNearViewport(img.parentElement, 420)) {
    queueThumbnail(entry, img, spinner);
  }
}

function isNearViewport(element, margin) {
  const rect = element.getBoundingClientRect();
  return rect.bottom >= -margin && rect.top <= window.innerHeight + margin;
}

function scanVisibleWork() {
  state.visibleScanTimer = null;
  document.querySelectorAll(".thumb-holder").forEach((holder) => {
    const payload = holder.__thumbPayload;
    if (payload && isNearViewport(holder, 420)) {
      queueThumbnail(payload.entry, payload.img, payload.spinner);
    }
  });
  document.querySelectorAll(".rating").forEach((ratingWrap) => {
    const payload = ratingWrap.__ratingPayload;
    if (payload && isNearViewport(ratingWrap, 220)) {
      queueEmbeddedRating(payload.entry, payload.ratingWrap);
    }
  });
}

function scheduleVisibleWorkScan() {
  if (state.visibleScanTimer) {
    return;
  }
  state.visibleScanTimer = window.setTimeout(scanVisibleWork, 80);
}

function scheduleLoadMoreIfNeeded() {
  window.setTimeout(() => {
    if (state.nextCursor === null) {
      return;
    }
    const nearBottom = window.innerHeight + window.scrollY > document.documentElement.scrollHeight - 1200;
    const notFilled = document.documentElement.scrollHeight <= window.innerHeight + 400;
    if (nearBottom || notFilled) {
      loadMoreEntries();
    }
  }, 60);
}

function queueThumbnail(entry, img, spinner, attempt = 0) {
  if (!img.isConnected || img.classList.contains("loaded")) {
    return;
  }
  const key = `${entry.path}:${state.thumbMode}`;
  if (state.thumbQueued.has(key)) {
    state.thumbQueue = state.thumbQueue.filter((item) => item.key !== key);
  }
  state.thumbQueued.add(key);
  state.thumbQueue.unshift({ entry, img, spinner, attempt, mode: state.thumbMode, key });
  trimThumbQueue();
  runThumbQueue();
}

function trimThumbQueue() {
  while (state.thumbQueue.length > THUMB_QUEUE_LIMIT) {
    const dropped = state.thumbQueue.pop();
    if (dropped) {
      state.thumbQueued.delete(dropped.key);
    }
  }
}

function runThumbQueue() {
  while (state.thumbActive < THUMB_LOAD_CONCURRENCY && state.thumbQueue.length > 0) {
    const payload = state.thumbQueue.shift();
    state.thumbQueued.delete(payload.key);
    if (!payload.img.isConnected || payload.img.classList.contains("loaded") || payload.mode !== state.thumbMode) {
      continue;
    }
    state.thumbActive += 1;
    loadThumbnail(payload.entry, payload.img, payload.spinner, payload.attempt, payload.mode)
      .catch(() => null)
      .finally(() => {
        state.thumbActive = Math.max(0, state.thumbActive - 1);
        runThumbQueue();
      });
  }
}

function resetThumbObserver() {
  if (state.thumbObserver) {
    state.thumbObserver.disconnect();
    state.thumbObserver = null;
  }
}

function clearThumbTimers() {
  for (const timer of state.thumbTimers.values()) {
    window.clearTimeout(timer);
  }
  state.thumbTimers.clear();
  state.thumbQueue = [];
  state.thumbQueued.clear();
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
}

