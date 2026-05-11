(() => {
  const PAGE_SIZE = 180;
  const DAY_COLLAPSE_LIMIT = 100;
  const TIMELINE_THUMB_MODES = ["small", "medium", "large", "xlarge"];
  const stateLocal = {
    featured: false,
    scale: "day",
    thumbMode: getStoredTimelineThumbMode(),
    expandedGroups: new Set(),
    cursor: 0,
    loading: false,
    done: false,
    items: [],
    statusTimer: 0,
    previousEntries: null,
    latestStatus: null,
    lastLoadedGeneration: -1,
    lastLoadedCount: -1,
    thumbObserver: null,
    thumbQueue: [],
    thumbQueued: new Set(),
    thumbActive: 0,
  };
  const TIMELINE_THUMB_CONCURRENCY = 6;

  const dialog = document.createElement("dialog");
  dialog.id = "timelineDialog";
  dialog.className = "timeline-dialog";
  dialog.innerHTML = `
    <div class="timeline-shell">
      <header class="timeline-header">
        <div>
          <div class="timeline-kicker">时间线</div>
          <h2>时间线</h2>
          <div class="timeline-status">正在读取时间线索引...</div>
          <div class="timeline-progress" hidden>
            <span></span>
          </div>
        </div>
        <button class="timeline-close" type="button" aria-label="关闭时间线">×</button>
      </header>
      <div class="timeline-toolbar">
        <div class="timeline-segment" role="group" aria-label="显示范围">
          <button class="active" type="button" data-timeline-featured="0">全部</button>
          <button type="button" data-timeline-featured="1">精选</button>
        </div>
        <div class="timeline-segment" role="group" aria-label="时间粒度">
          <button class="active" type="button" data-timeline-scale="day">日</button>
          <button type="button" data-timeline-scale="month">月</button>
          <button type="button" data-timeline-scale="year">年</button>
        </div>
        <label class="timeline-thumb-mode">
          <span>预览</span>
          <select aria-label="时间线预览尺寸">
            <option value="small">小</option>
            <option value="medium">中</option>
            <option value="large">大</option>
            <option value="xlarge">超大</option>
          </select>
        </label>
      </div>
      <div class="timeline-content">
        <aside class="timeline-axis" aria-label="时间线月份导航">
          <div class="timeline-axis-list"></div>
        </aside>
        <main class="timeline-main">
          <div class="timeline-groups"></div>
          <div class="timeline-sentinel"></div>
        </main>
      </div>
    </div>
  `;
  pluginDialogs.append(dialog);

  const shell = dialog.querySelector(".timeline-shell");
  const status = dialog.querySelector(".timeline-status");
  const progress = dialog.querySelector(".timeline-progress");
  const progressBar = dialog.querySelector(".timeline-progress span");
  const groups = dialog.querySelector(".timeline-groups");
  const content = dialog.querySelector(".timeline-main");
  const axisList = dialog.querySelector(".timeline-axis-list");
  const sentinel = dialog.querySelector(".timeline-sentinel");
  const thumbModeSelect = dialog.querySelector(".timeline-thumb-mode select");
  const observer = new IntersectionObserver((items) => {
    if (items.some((item) => item.isIntersecting)) {
      loadNextPage();
    }
  }, { root: content, rootMargin: "900px 0px" });
  stateLocal.thumbObserver = new IntersectionObserver((items) => {
    items.forEach((item) => {
      if (item.isIntersecting) {
        queueTimelineThumbnail(item.target);
      }
    });
  }, { root: content, rootMargin: "900px 0px" });

  registerPluginAction("timeline.open", () => openTimeline());

  dialog.querySelector(".timeline-close").addEventListener("click", () => dialog.close());
  thumbModeSelect.value = stateLocal.thumbMode;
  thumbModeSelect.addEventListener("change", () => {
    const mode = thumbModeSelect.value;
    if (!TIMELINE_THUMB_MODES.includes(mode) || mode === stateLocal.thumbMode) {
      thumbModeSelect.value = stateLocal.thumbMode;
      return;
    }
    stateLocal.thumbMode = mode;
    window.localStorage.setItem("timelineThumbMode", mode);
    applyTimelineThumbMode();
    resetTimelineThumbnailQueue();
    renderTimeline();
  });
  dialog.querySelectorAll("[data-timeline-featured]").forEach((button) => {
    button.addEventListener("click", () => {
      stateLocal.featured = button.dataset.timelineFeatured === "1";
      stateLocal.expandedGroups.clear();
      updateToolbar();
      resetAndLoad();
    });
  });
  dialog.querySelectorAll("[data-timeline-scale]").forEach((button) => {
    button.addEventListener("click", () => {
      stateLocal.scale = button.dataset.timelineScale;
      stateLocal.expandedGroups.clear();
      updateToolbar();
      renderTimeline();
    });
  });
  dialog.addEventListener("close", () => {
    stopStatusPolling();
    observer.unobserve(sentinel);
  });
  document.addEventListener("photoShare:backend-task-started", () => {
    if (dialog.open) {
      scheduleStatusPolling(800);
    }
  });
  viewer.addEventListener("close", restoreGalleryEntriesAfterTimelineViewer);

  async function openTimeline() {
    applyTimelineThumbMode();
    dialog.showModal();
    observer.observe(sentinel);
    await resetAndLoad();
  }

  async function resetAndLoad() {
    stateLocal.cursor = 0;
    stateLocal.done = false;
    stateLocal.items = [];
    stateLocal.expandedGroups.clear();
    stateLocal.lastLoadedGeneration = -1;
    stateLocal.lastLoadedCount = -1;
    groups.innerHTML = `<div class="timeline-empty"><span class="spinner inline-spinner"></span><span>正在打开时间线...</span></div>`;
    await Promise.all([refreshStatus({ prepare: true }), loadNextPage()]);
  }

  async function refreshStatus(options = {}) {
    try {
      const url = options.prepare ? "/api/timeline/status?prepare=1" : "/api/timeline/status";
      const data = await fetchJson(url, { cache: "no-store" });
      renderStatus(data);
      maybeReloadForStatus(data);
      if (dialog.open && data.indexing) {
        scheduleStatusPolling(1200);
      } else {
        stopStatusPolling();
      }
    } catch (error) {
      status.textContent = error.message;
      stopStatusPolling();
    }
  }

  function scheduleStatusPolling(delay = 1200) {
    if (stateLocal.statusTimer || !dialog.open) {
      return;
    }
    stateLocal.statusTimer = window.setTimeout(async () => {
      stateLocal.statusTimer = 0;
      await refreshStatus();
    }, delay);
  }

  function stopStatusPolling() {
    if (stateLocal.statusTimer) {
      window.clearTimeout(stateLocal.statusTimer);
      stateLocal.statusTimer = 0;
    }
  }

  function maybeReloadForStatus(data) {
    if (!dialog.open || stateLocal.loading) {
      return;
    }
    const generation = Number(data.generation || 0);
    const count = Number(data.count || 0);
    const loadedGeneration = stateLocal.lastLoadedGeneration;
    const loadedCount = stateLocal.lastLoadedCount;
    const hasNewGeneration = generation > loadedGeneration && !data.indexing;
    const hasNewPartialResults = data.indexing && count > loadedCount;
    const isEmptyWaitingForIndex = data.indexing && !stateLocal.items.length && !stateLocal.loading;
    if (!hasNewGeneration && !hasNewPartialResults && !isEmptyWaitingForIndex) {
      return;
    }
    stateLocal.cursor = 0;
    stateLocal.done = false;
    stateLocal.items = [];
    loadNextPage();
  }

  async function loadNextPage() {
    if (stateLocal.loading || stateLocal.done) {
      return;
    }
    stateLocal.loading = true;
    sentinel.classList.add("loading");
    try {
      const params = new URLSearchParams({
        cursor: String(stateLocal.cursor),
        limit: String(PAGE_SIZE),
        featured: stateLocal.featured ? "1" : "0",
      });
      const data = await fetchJson(`/api/timeline/items?${params.toString()}`, { cache: "no-store" });
      stateLocal.items.push(...(data.items || []));
      stateLocal.cursor = data.nextCursor || 0;
      if (data.status) {
        renderStatus(data.status);
      }
      if (data.status?.indexing && !(data.items || []).length) {
        stateLocal.done = false;
      } else {
        stateLocal.done = data.nextCursor === null || data.nextCursor === undefined;
      }
      if (data.status) {
        stateLocal.lastLoadedGeneration = Number(data.status.generation || 0);
        stateLocal.lastLoadedCount = Number(data.status.count || 0);
      }
      renderTimeline();
    } catch (error) {
      groups.innerHTML = `<div class="timeline-empty">${escapeHtml(error.message)}</div>`;
      stateLocal.done = true;
    } finally {
      stateLocal.loading = false;
      sentinel.classList.remove("loading");
    }
  }

  function renderStatus(data) {
    stateLocal.latestStatus = data;
    const indexedAt = data.indexedAt ? new Date(data.indexedAt * 1000).toLocaleTimeString() : "尚未完成";
    const suffix = data.error ? `，错误：${data.error}` : "";
    const progressText = data.indexing && data.estimatedTotal
      ? `，约 ${Math.round((data.progress || 0) * 100)}%`
      : "";
    status.textContent = data.indexing
      ? `正在建立索引，当前 ${data.count || 0} 项${progressText}${suffix}`
      : `已索引 ${data.count || 0} 项，精选 ${data.featuredCount || 0} 项，上次更新 ${indexedAt}${suffix}`;
    renderProgress(data);
  }

  function renderProgress(data) {
    if (!data.indexing) {
      progress.hidden = true;
      progress.classList.remove("indeterminate");
      progressBar.style.width = "0%";
      return;
    }
    progress.hidden = false;
    if (data.estimatedTotal && Number.isFinite(data.progress)) {
      progress.classList.remove("indeterminate");
      progressBar.style.width = `${Math.max(2, Math.min(100, Math.round(data.progress * 100)))}%`;
      return;
    }
    progress.classList.add("indeterminate");
    progressBar.style.width = "42%";
  }

  function renderTimeline() {
    groups.innerHTML = "";
    axisList.innerHTML = "";
    resetTimelineThumbnailQueue();
    if (!stateLocal.items.length) {
      const message = stateLocal.latestStatus?.indexing
        ? "正在建立索引，照片会陆续显示。"
        : (stateLocal.featured ? "还没有有评级的精选照片。" : "时间线里还没有照片。");
      groups.innerHTML = `<div class="timeline-empty">${message}</div>`;
      return;
    }
    applyTimelineThumbMode();
    const grouped = groupItems(stateLocal.items, stateLocal.scale);
    renderAxis(grouped);
    const fragment = document.createDocumentFragment();
    grouped.forEach((group) => {
      fragment.append(createTimelineGroup(group));
    });
    groups.append(fragment);
  }

  function renderAxis(grouped) {
    const buckets = new Map();
    grouped.forEach((group) => {
      const key = group.axis.id;
      if (!buckets.has(key)) {
        buckets.set(key, { ...group.axis, groupId: group.id, count: 0 });
      }
      buckets.get(key).count += group.items.length;
    });
    const fragment = document.createDocumentFragment();
    Array.from(buckets.values()).forEach((bucket) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "timeline-axis-item";
      button.innerHTML = `
        <span class="timeline-axis-year">${escapeHtml(bucket.year)}</span>
        <span class="timeline-axis-month">${escapeHtml(bucket.month)}</span>
        <span class="timeline-axis-count">${bucket.count}</span>
      `;
      button.addEventListener("click", () => scrollToTimelineGroup(bucket.groupId));
      fragment.append(button);
    });
    axisList.append(fragment);
  }

  function scrollToTimelineGroup(groupId) {
    const target = groups.querySelector(`[data-timeline-group="${CSS.escape(groupId)}"]`);
    if (!target) {
      return;
    }
    content.scrollTo({
      top: Math.max(0, target.offsetTop - 8),
      behavior: "smooth",
    });
  }

  function createTimelineGroup(group) {
    const section = document.createElement("section");
    section.className = "timeline-group";
    section.dataset.timelineGroup = group.id;
    const isCollapsible = group.scale === "day" && group.items.length > DAY_COLLAPSE_LIMIT;
    const isExpanded = stateLocal.expandedGroups.has(group.id);
    const visibleItems = isCollapsible && !isExpanded ? group.items.slice(0, DAY_COLLAPSE_LIMIT) : group.items;
    const hiddenCount = group.items.length - visibleItems.length;
    section.innerHTML = `
      <div class="timeline-group-head">
        <div>
          <div class="timeline-group-title">${escapeHtml(group.title)}</div>
          <div class="timeline-group-subtitle">${group.items.length} 项${hiddenCount > 0 ? `，已折叠 ${hiddenCount} 项` : ""}</div>
        </div>
        ${isCollapsible ? `<button class="timeline-fold-toggle" type="button">${isExpanded ? "收起" : `展开剩余 ${hiddenCount} 项`}</button>` : ""}
      </div>
      <div class="timeline-mosaic"></div>
    `;
    const mosaic = section.querySelector(".timeline-mosaic");
    visibleItems.forEach((item, index) => {
      const card = createTimelineCard(item, index);
      mosaic.append(card);
    });
    const toggle = section.querySelector(".timeline-fold-toggle");
    if (toggle) {
      toggle.addEventListener("click", () => {
        if (isExpanded) {
          stateLocal.expandedGroups.delete(group.id);
        } else {
          stateLocal.expandedGroups.add(group.id);
        }
        renderTimeline();
        window.requestAnimationFrame(() => scrollToTimelineGroup(group.id));
      });
    }
    return section;
  }

  function createTimelineCard(item, index) {
    item.path = item.path;
    const button = document.createElement("button");
    button.type = "button";
    button.className = `timeline-card ${item.type === "video" ? "video" : ""}`;
    button.dataset.path = item.path;
    button.style.setProperty("--span", String(cardSpan(item, index)));
    const rating = item.rating > 0 ? `<span class="timeline-rating">${"★".repeat(item.rating)}</span>` : "";
    button.innerHTML = `
      <span class="timeline-thumb">
        ${item.type === "video" ? `<span class="timeline-video-badge">VIDEO</span><span class="timeline-video-icon">▶</span>` : `<img alt="${escapeHtml(item.name)}" loading="eager" decoding="async" fetchpriority="high" />`}
        ${rating}
      </span>
      <span class="timeline-card-meta">
        <span>${escapeHtml(timeLabel(item.takenAt))}</span>
      </span>
    `;
    if (item.type === "photo") {
      const img = button.querySelector("img");
      button.classList.add("loading");
      button._timelineThumbPayload = { item, img };
      stateLocal.thumbObserver.observe(button);
    }
    button.addEventListener("click", () => openTimelineItem(item, button));
    return button;
  }

  function resetTimelineThumbnailQueue() {
    stateLocal.thumbQueue = [];
    stateLocal.thumbQueued.clear();
    stateLocal.thumbActive = 0;
    stateLocal.thumbObserver?.disconnect();
  }

  function queueTimelineThumbnail(card) {
    const payload = card?._timelineThumbPayload;
    if (!payload || !payload.img?.isConnected) {
      return;
    }
    stateLocal.thumbObserver.unobserve(card);
    const key = `${payload.item.path}|${stateLocal.thumbMode}`;
    if (stateLocal.thumbQueued.has(key)) {
      return;
    }
    stateLocal.thumbQueued.add(key);
    stateLocal.thumbQueue.push({ ...payload, key });
    pumpTimelineThumbQueue();
  }

  function pumpTimelineThumbQueue() {
    while (stateLocal.thumbActive < TIMELINE_THUMB_CONCURRENCY && stateLocal.thumbQueue.length) {
      const payload = stateLocal.thumbQueue.shift();
      stateLocal.thumbActive += 1;
      loadTimelineThumbnail(payload.item, payload.img)
        .catch(() => showTimelineImageFallback(payload.item, payload.img))
        .finally(() => {
          stateLocal.thumbActive = Math.max(0, stateLocal.thumbActive - 1);
          stateLocal.thumbQueued.delete(payload.key);
          pumpTimelineThumbQueue();
        });
    }
  }

  async function loadTimelineThumbnail(item, img, attempt = 0) {
    if (!img?.isConnected) {
      return;
    }
    const mode = stateLocal.thumbMode || state.thumbMode || "medium";
    if (attempt === 0 && item.thumbUrl) {
      setTimelineImageSource(item, img, item.thumbUrl);
    }
    try {
      const response = await fetch(`/api/thumb-status/${encodePath(item.path)}?mode=${mode}`, { cache: "no-store" });
      if (response.status === 200) {
        const data = await response.json();
        setTimelineImageSource(item, img, data.url || item.thumbUrl);
        return;
      }
      if (response.status !== 202) {
        showTimelineImageFallback(item, img);
        return;
      }
    } catch {
      showTimelineImageFallback(item, img);
      return;
    }
    if (attempt < 12) {
      await delay(450 + Math.min(attempt, 6) * 250);
      return loadTimelineThumbnail(item, img, attempt + 1);
    }
    showTimelineImageFallback(item, img);
  }

  function setTimelineImageSource(item, img, url) {
    if (!url || !img?.isConnected) {
      return;
    }
    const nextSrc = withVersion(url, item.mtime);
    if (img.src.endsWith(nextSrc)) {
      return;
    }
    img.onload = () => markTimelineImageLoaded(img);
    img.onerror = () => showTimelineImageFallback(item, img);
    img.src = nextSrc;
    if (img.complete && img.naturalWidth > 0) {
      markTimelineImageLoaded(img);
    }
  }

  function showTimelineImageFallback(item, img) {
    if (!img?.isConnected) {
      return;
    }
    if (item.browserRenderable === false) {
      markTimelineImageFailed(img);
      return;
    }
    setTimelineImageSource(item, img, item.originalUrl || `/api/image/${encodePath(item.path)}`);
  }

  function markTimelineImageLoaded(img) {
    img.classList.add("loaded");
    img.closest(".timeline-card")?.classList.remove("loading", "failed");
  }

  function markTimelineImageFailed(img) {
    img.removeAttribute("src");
    img.closest(".timeline-card")?.classList.remove("loading");
    img.closest(".timeline-card")?.classList.add("failed");
  }

  function openTimelineItem(item, origin) {
    if (!state.timelineViewerOpen) {
      stateLocal.previousEntries = state.entries;
    }
    const viewerItems = stateLocal.items.map((entry) => ({ ...entry }));
    state.entries = viewerItems;
    state.timelineViewerOpen = true;
    const selected = viewerItems.find((entry) => entry.path === item.path) || item;
    openViewer(selected, origin.querySelector("img") || origin);
  }

  function restoreGalleryEntriesAfterTimelineViewer() {
    if (!state.timelineViewerOpen) {
      return;
    }
    const current = state.currentPhoto;
    if (current) {
      const item = stateLocal.items.find((entry) => entry.path === current.path);
      if (item) {
        item.rating = current.rating;
        item.ratingPending = false;
      }
    }
    state.timelineViewerOpen = false;
    if (stateLocal.previousEntries) {
      state.entries = stateLocal.previousEntries;
      stateLocal.previousEntries = null;
    }
    renderTimeline();
  }

  function updateToolbar() {
    dialog.querySelectorAll("[data-timeline-featured]").forEach((button) => {
      button.classList.toggle("active", (button.dataset.timelineFeatured === "1") === stateLocal.featured);
    });
    dialog.querySelectorAll("[data-timeline-scale]").forEach((button) => {
      button.classList.toggle("active", button.dataset.timelineScale === stateLocal.scale);
    });
  }

  function groupItems(items, scale) {
    const map = new Map();
    items.forEach((item) => {
      const key = groupKey(item.takenAt, scale);
      if (!map.has(key.id)) {
        map.set(key.id, { id: key.id, title: key.title, axis: key.axis, scale, items: [] });
      }
      map.get(key.id).items.push(item);
    });
    return Array.from(map.values());
  }

  function groupKey(timestamp, scale) {
    const date = new Date(timestamp * 1000);
    const year = date.getFullYear();
    const month = date.getMonth() + 1;
    const day = date.getDate();
    const axis = {
      id: `${year}-${String(month).padStart(2, "0")}`,
      year: `${year}`,
      month: `${month}月`,
    };
    if (scale === "year") {
      return { id: String(year), title: `${year} 年`, axis: { id: String(year), year: `${year}`, month: "全年" } };
    }
    if (scale === "month") {
      return { id: `${year}-${month}`, title: `${year} 年 ${month} 月`, axis };
    }
    return { id: `${year}-${month}-${day}`, title: dayTitle(date), axis };
  }

  function dayTitle(date) {
    const today = new Date();
    const startToday = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime();
    const startDate = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
    const diff = Math.round((startToday - startDate) / 86400000);
    if (diff === 0) {
      return "今天";
    }
    if (diff === 1) {
      return "昨天";
    }
    return date.toLocaleDateString("zh-CN", { year: "numeric", month: "long", day: "numeric", weekday: "long" });
  }

  function timeLabel(timestamp) {
    return new Date(timestamp * 1000).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  }

  function cardSpan(item, index) {
    if (item.type === "video") {
      return 2;
    }
    return [2, 1, 1, 2, 1, 1, 1, 2][index % 8];
  }

  function getStoredTimelineThumbMode() {
    const stored = window.localStorage.getItem("timelineThumbMode");
    if (TIMELINE_THUMB_MODES.includes(stored)) {
      return stored;
    }
    return TIMELINE_THUMB_MODES.includes(state.thumbMode) ? state.thumbMode : "medium";
  }

  function applyTimelineThumbMode() {
    shell.dataset.thumbMode = TIMELINE_THUMB_MODES.includes(stateLocal.thumbMode) ? stateLocal.thumbMode : "medium";
  }

  function delay(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }
})();
