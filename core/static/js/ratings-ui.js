function observeRating(entry, ratingWrap) {
  if (entry.type !== "photo" || !entry.ratingPending) {
    return;
  }
  if (!state.ratingObserver) {
    state.ratingObserver = new IntersectionObserver(
      (items) => {
        items.forEach((item) => {
          if (!item.isIntersecting) {
            return;
          }
          const payload = item.target.__ratingPayload;
          if (payload) {
            queueEmbeddedRating(payload.entry, payload.ratingWrap);
          }
        });
      },
      { rootMargin: "180px 0px" },
    );
  }
  ratingWrap.__ratingPayload = { entry, ratingWrap };
  state.ratingObserver.observe(ratingWrap);
  if (isNearViewport(ratingWrap, 220)) {
    queueEmbeddedRating(entry, ratingWrap);
  }
}

function queueEmbeddedRating(entry, ratingWrap, attempt = 0) {
  if (entry.type !== "photo" || !entry.ratingPending || !ratingWrap.isConnected) {
    return;
  }
  const key = entry.path;
  if (state.ratingQueued.has(key)) {
    state.ratingQueue = state.ratingQueue.filter((item) => item.key !== key);
  }
  state.ratingQueued.add(key);
  state.ratingQueue.unshift({ entry, ratingWrap, attempt, key });
  trimRatingQueue();
  runRatingQueue();
}

function trimRatingQueue() {
  while (state.ratingQueue.length > RATING_QUEUE_LIMIT) {
    const dropped = state.ratingQueue.pop();
    if (dropped) {
      state.ratingQueued.delete(dropped.key);
    }
  }
}

function runRatingQueue() {
  while (state.ratingActive < RATING_STATUS_CONCURRENCY && state.ratingQueue.length > 0) {
    const payload = state.ratingQueue.shift();
    state.ratingQueued.delete(payload.key);
    if (payload.entry.type !== "photo" || !payload.entry.ratingPending || !payload.ratingWrap.isConnected) {
      continue;
    }
    state.ratingActive += 1;
    loadEmbeddedRating(payload.entry, payload.ratingWrap, payload.attempt)
      .catch(() => null)
      .finally(() => {
        state.ratingActive = Math.max(0, state.ratingActive - 1);
        runRatingQueue();
      });
  }
}

async function loadEmbeddedRating(entry, ratingWrap, attempt = 0) {
  if (entry.type !== "photo" || !entry.ratingPending || !ratingWrap.isConnected) {
    return;
  }
  try {
    const response = await fetch(`/api/rating-status/${encodePath(entry.path)}`, { cache: "no-store" });
    const data = await response.json();
    if (response.status === 200) {
      if (!ratingWrap.isConnected) {
        return;
      }
      entry.rating = data.rating;
      entry.ratingPending = false;
      ratingWrap.replaceWith(createRating(entry, false));
      if (state.currentPhoto?.path === entry.path) {
        state.currentPhoto.rating = data.rating;
        state.currentPhoto.ratingPending = false;
        renderViewerRating();
      }
      return;
    }
    if (response.status !== 202) {
      entry.ratingPending = false;
      return;
    }
  } catch {
    scheduleRatingRetry(entry, ratingWrap, attempt);
    return;
  }

  scheduleRatingRetry(entry, ratingWrap, attempt);
}

function scheduleRatingRetry(entry, ratingWrap, attempt) {
  if (entry.type !== "photo" || !entry.ratingPending || !ratingWrap.isConnected || attempt >= 12) {
    return;
  }
  const delay = Math.min(3000, 350 + attempt * 220);
  const timer = window.setTimeout(() => {
    state.ratingTimers.delete(entry.path);
    queueEmbeddedRating(entry, ratingWrap, attempt + 1);
  }, delay);
  state.ratingTimers.set(entry.path, timer);
}

function applyFilters() {
  state.filterGeneration += 1;
  clearFilterRefreshTimer();
  state.filters.ratings = getSelectedRatings();
  state.filters.dateFrom = dateFromFilter.value;
  state.filters.dateTo = dateToFilter.value;
  updateRatingFilterLabel();
  updateFilterPanelLabel();
  state.entries = [];
  state.indexing = state.filters.ratings.length > 0;
  renderBreadcrumb();
  renderGrid();
  loadFolder(state.folder);
}

function resetFiltersForFolderNavigation() {
  state.filterGeneration += 1;
  clearFilterRefreshTimer();
  state.filters.ratings = [];
  state.filters.dateFrom = "";
  state.filters.dateTo = "";
  state.indexing = false;
  ratingFilterInputs.forEach((input) => {
    input.checked = false;
  });
  dateFromFilter.value = "";
  dateToFilter.value = "";
  updateRatingFilterLabel();
  updateFilterPanelLabel();
  setFilterPanelOpen(false);
  setRatingMenuOpen(false);
}

function scheduleFilterRefresh(generation) {
  clearFilterRefreshTimer();
  state.filterRefreshTimer = window.setTimeout(() => {
    state.filterRefreshTimer = null;
    if (generation === state.filterGeneration) {
      loadFolder(state.folder);
    }
  }, 800);
}

function clearFilterRefreshTimer() {
  if (state.filterRefreshTimer) {
    window.clearTimeout(state.filterRefreshTimer);
    state.filterRefreshTimer = null;
  }
}

function getSelectedRatings() {
  return ratingFilterInputs.filter((input) => input.checked).map((input) => input.value);
}

function updateRatingFilterLabel() {
  const labels = state.filters.ratings.map((rating) => (rating === "0" ? "未评分" : `${rating} 星`));
  ratingFilterBtn.textContent = labels.length ? labels.join("、") : "全部";
}

function hasActiveFilters() {
  return Boolean(state.filters.ratings.length || state.filters.dateFrom || state.filters.dateTo);
}

function updateFilterPanelLabel() {
  const active = hasActiveFilters();
  filterPanelToggleBtn.textContent = active ? "已筛选" : "筛选";
  filterPanelToggleBtn.classList.toggle("active", active);
}

function setFilterPanelOpen(open) {
  filterPanel.hidden = !open;
  filterPanelToggleBtn.setAttribute("aria-expanded", String(open));
}

function setRatingMenuOpen(open) {
  ratingFilterMenu.hidden = !open;
  ratingFilterBtn.setAttribute("aria-expanded", String(open));
}

function createRating(entry, large) {
  const wrap = document.createElement("div");
  wrap.className = `rating ${large ? "rating-large" : ""}`;

  const off = document.createElement("button");
  off.type = "button";
  off.className = `rating-off ${entry.rating === 0 ? "active" : ""}`;
  off.textContent = "OFF";
  off.title = "取消评分";
  off.addEventListener("click", async (event) => {
    event.stopPropagation();
    await setRating(entry, 0);
  });
  wrap.append(off);

  for (let i = 1; i <= 5; i += 1) {
    const star = document.createElement("button");
    star.type = "button";
    star.className = `star ${i <= entry.rating ? "active" : ""}`;
    star.textContent = "★";
    star.title = `${i} 分`;
    if (large) {
      star.style.fontSize = "28px";
    }
    star.addEventListener("click", async (event) => {
      event.stopPropagation();
      const nextRating = entry.rating === i ? 0 : i;
      await setRating(entry, nextRating);
    });
    wrap.append(star);
  }
  return wrap;
}
