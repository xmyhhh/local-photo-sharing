(() => {
  const PAGE_SIZE = 180;
  const COLLAPSE_ROWS = 5;
  const RENDER_CHUNK_SIZE = 6;
  const PAGE_LOAD_ROOT_MARGIN = window.matchMedia("(max-width: 720px)").matches ? "180px 0px" : "260px 0px";
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
    applyingChanges: false,
    thumbObserver: null,
    thumbQueue: [],
    thumbQueued: new Set(),
    thumbActive: 0,
    renderToken: 0,
    renderedCount: 0,
  };
  const TIMELINE_THUMB_CONCURRENCY = 3;

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
  }, { root: content, rootMargin: PAGE_LOAD_ROOT_MARGIN });
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
    stateLocal.renderedCount = 0;
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
    if (!dialog.open || stateLocal.loading || stateLocal.applyingChanges) {
      return;
    }
    const generation = Number(data.generation || 0);
    const count = Number(data.count || 0);
    const loadedGeneration = stateLocal.lastLoadedGeneration;
    const loadedCount = stateLocal.lastLoadedCount;
    const hasNewGeneration = generation > loadedGeneration && !data.indexing;
    const hasNewPartialResults = data.indexing && count > loadedCount;
    const isEmptyWaitingForIndex = data.indexing && !stateLocal.items.length && !stateLocal.loading;
    const looksLikeDeletion = loadedCount > 0 && count < loadedCount;
    if (hasNewGeneration && !looksLikeDeletion && stateLocal.items.length) {
      applyTimelineChanges(data);
      return;
    }
    if (!hasNewGeneration && !hasNewPartialResults && !isEmptyWaitingForIndex) {
      return;
    }
    if (hasNewPartialResults && stateLocal.items.length) {
      return;
    }
    stateLocal.cursor = 0;
    stateLocal.done = false;
    stateLocal.items = [];
    stateLocal.renderedCount = 0;
    loadNextPage();
  }

  async function applyTimelineChanges(statusData) {
    const since = Number(statusData.changedSince || 0);
    if (!since) {
      resetAndLoad();
      return;
    }
    stateLocal.applyingChanges = true;
    try {
      const params = new URLSearchParams({
        since: String(since),
        limit: "240",
        featured: stateLocal.featured ? "1" : "0",
      });
      const data = await fetchJson(`/api/timeline/changes?${params.toString()}`, { cache: "no-store" });
      if (data.truncated || !Array.isArray(data.items)) {
        await resetAndLoad();
        return;
      }
      const changedItems = dedupeTimelineItems(data.items);
      if (changedItems.length) {
        mergeTimelineItems(changedItems);
        insertChangedTimelineItems(changedItems);
      }
      if (data.status) {
        renderStatus(data.status);
        stateLocal.lastLoadedGeneration = Number(data.status.generation || stateLocal.lastLoadedGeneration);
        stateLocal.lastLoadedCount = Number(data.status.count || stateLocal.lastLoadedCount);
      }
    } catch {
      await resetAndLoad();
    } finally {
      stateLocal.applyingChanges = false;
    }
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
      const previousCount = stateLocal.items.length;
      const nextItems = data.items || [];
      stateLocal.items.push(...nextItems);
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
      if (previousCount && nextItems.length && stateLocal.scale === "day") {
        appendTimelineItems(previousCount);
      } else {
        renderTimeline();
      }
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
    stateLocal.renderToken += 1;
    const token = stateLocal.renderToken;
    groups.innerHTML = "";
    axisList.innerHTML = "";
    resetTimelineThumbnailQueue();
    stateLocal.renderedCount = 0;
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
    renderTimelineGroupsChunked(grouped, token);
  }

  function appendTimelineItems(startIndex) {
    const token = ++stateLocal.renderToken;
    const nextItems = stateLocal.items.slice(startIndex);
    if (!nextItems.length) {
      return;
    }
    const allGrouped = groupItems(stateLocal.items, stateLocal.scale);
    const grouped = groupItems(nextItems, stateLocal.scale);
    const totals = new Map(allGrouped.map((group) => [group.id, group.items.length]));
    renderAxis(allGrouped);
    appendTimelineGroupsChunked(grouped, token, totals);
  }

  function appendTimelineGroupsChunked(grouped, token, totals) {
    let index = 0;
    const renderChunk = () => {
      if (token !== stateLocal.renderToken) {
        return;
      }
      const fragment = document.createDocumentFragment();
      const end = Math.min(grouped.length, index + RENDER_CHUNK_SIZE);
      for (; index < end; index += 1) {
        const group = grouped[index];
        const existing = groups.querySelector(`[data-timeline-group="${CSS.escape(group.id)}"]`);
        if (existing) {
          refreshTimelineGroup(existing, group.id, totals.get(group.id) || group.items.length);
        } else {
          fragment.append(createTimelineGroup({ ...group, totalCount: totals.get(group.id) || group.items.length }));
        }
      }
      groups.append(fragment);
      if (index < grouped.length) {
        window.requestAnimationFrame(renderChunk);
      }
    };
    renderChunk();
  }

  function refreshTimelineGroup(section, groupId, totalCount = 0) {
    if (!section?.isConnected) {
      return;
    }
    const groupedAll = groupItems(stateLocal.items, stateLocal.scale);
    const group = groupedAll.find((item) => item.id === groupId);
    if (!group) {
      section.remove();
      renderAxis(groupedAll);
      return;
    }
    section.replaceWith(createTimelineGroup({ ...group, totalCount: totalCount || group.items.length }));
  }

  function insertChangedTimelineItems(items) {
    if (!items.length) {
      return;
    }
    const groupedAll = groupItems(stateLocal.items, stateLocal.scale);
    const totals = new Map(groupedAll.map((group) => [group.id, group.items.length]));
    renderAxis(groupedAll);
    const changedGroups = new Set();
    dedupeTimelineItems(items).forEach((item) => {
      const key = groupKey(item.takenAt, stateLocal.scale);
      if (key.id) {
        changedGroups.add(key.id);
      }
    });
    changedGroups.forEach((groupId) => {
      const fullGroup = groupedAll.find((group) => group.id === groupId);
      if (!fullGroup) {
        return;
      }
      let section = groups.querySelector(`[data-timeline-group="${CSS.escape(groupId)}"]`);
      if (!section) {
        section = createTimelineGroup({ ...fullGroup, totalCount: totals.get(groupId) || fullGroup.items.length });
        insertTimelineGroupElement(section, fullGroup);
        return;
      }
      refreshTimelineGroup(section, groupId, totals.get(groupId) || fullGroup.items.length);
    });
  }

  function insertTimelineGroupElement(section, group) {
    const groupedAll = groupItems(stateLocal.items, stateLocal.scale);
    const byId = new Map(groupedAll.map((item) => [item.id, item]));
    const existing = Array.from(groups.querySelectorAll(".timeline-group"));
    const before = existing.find((node) => {
      const current = byId.get(node.dataset.timelineGroup);
      return current && compareTimelineGroups(group, current) < 0;
    });
    groups.insertBefore(section, before || null);
  }

  function compareTimelineGroups(left, right) {
    const leftMax = left.items[0]?.takenAt || 0;
    const rightMax = right.items[0]?.takenAt || 0;
    return leftMax === rightMax ? left.id.localeCompare(right.id) : rightMax - leftMax;
  }

  function renderTimelineGroupsChunked(grouped, token, options = {}) {
    let index = 0;
    const renderChunk = () => {
      if (token !== stateLocal.renderToken) {
        return;
      }
      const fragment = document.createDocumentFragment();
      const end = Math.min(grouped.length, index + RENDER_CHUNK_SIZE);
      for (; index < end; index += 1) {
        fragment.append(createTimelineGroup(grouped[index], options));
      }
      groups.append(fragment);
      if (index < grouped.length) {
        window.requestAnimationFrame(renderChunk);
      }
    };
    renderChunk();
  }

  function renderAxis(grouped) {
    axisList.innerHTML = "";
    const buckets = new Map();
    grouped.forEach((group) => {
      const key = group.axis.id;
      if (!buckets.has(key)) {
        buckets.set(key, { ...group.axis, count: 0 });
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
      button.addEventListener("click", () => scrollToTimelineAxis(bucket.id));
      fragment.append(button);
    });
    axisList.append(fragment);
  }

  function scrollToTimelineAxis(axisId) {
    const target = groups.querySelector(`[data-timeline-axis="${CSS.escape(axisId)}"]`);
    if (!target) {
      return;
    }
    scrollTimelineTargetIntoView(target);
  }

  function scrollToTimelineGroup(groupId) {
    const target = groups.querySelector(`[data-timeline-group="${CSS.escape(groupId)}"]`);
    if (!target) {
      return;
    }
    scrollTimelineTargetIntoView(target);
  }

  function scrollTimelineTargetIntoView(target) {
    const targetRect = target.getBoundingClientRect();
    const contentRect = content.getBoundingClientRect();
    content.scrollTo({
      top: Math.max(0, content.scrollTop + targetRect.top - contentRect.top - 8),
      behavior: "smooth",
    });
  }

  function createTimelineGroup(group) {
    const section = document.createElement("section");
    section.className = "timeline-group";
    section.dataset.timelineGroup = group.id;
    section.dataset.timelineAxis = group.axis.id;
    const isCollapsible = group.scale === "day" && group.items.length > 0;
    const isExpanded = stateLocal.expandedGroups.has(group.id);
    const visibleItems = isCollapsible && !isExpanded ? visibleItemsForCollapsedRows(group.items) : group.items;
    const totalCount = group.totalCount || group.items.length;
    const hiddenCount = totalCount - visibleItems.length;
    const showToggle = isCollapsible && (hiddenCount > 0 || isExpanded);
    section.innerHTML = `
      <div class="timeline-group-head">
        <div>
          <div class="timeline-group-title">${escapeHtml(group.title)}</div>
          <div class="timeline-group-subtitle">${totalCount} 项${hiddenCount > 0 ? `，已折叠 ${hiddenCount} 项` : ""}</div>
        </div>
        ${showToggle ? `<button class="timeline-fold-toggle" type="button">${isExpanded ? "收起" : `展开剩余 ${hiddenCount} 项`}</button>` : ""}
      </div>
      <div class="timeline-mosaic"></div>
    `;
    const mosaic = section.querySelector(".timeline-mosaic");
    visibleItems.forEach((item, index) => {
      const card = createTimelineCard(item, index, index === visibleItems.length - 1 ? hiddenCount : 0, group.id);
      mosaic.append(card);
    });
    const toggle = section.querySelector(".timeline-fold-toggle");
    if (toggle) {
      toggle.addEventListener("click", () => {
        if (stateLocal.expandedGroups.has(group.id)) {
          stateLocal.expandedGroups.delete(group.id);
        } else {
          stateLocal.expandedGroups.add(group.id);
        }
        updateTimelineGroupExpansion(group.id);
      });
    }
    return section;
  }

  function updateTimelineGroupExpansion(groupId) {
    const section = groups.querySelector(`[data-timeline-group="${CSS.escape(groupId)}"]`);
    if (!section) {
      return;
    }
    refreshTimelineGroup(section, groupId);
  }

  function visibleItemsForCollapsedRows(items) {
    const columns = estimateTimelineColumns();
    if (!items.length || columns <= 0) {
      return items.slice(0, Math.min(items.length, 1));
    }
    const occupied = [];
    const visible = [];
    for (let index = 0; index < items.length; index += 1) {
      const span = cardSpan(items[index], index);
      const width = Math.max(1, Math.min(columns, span.x || 1));
      const height = Math.max(1, span.y || 1);
      const position = findTimelineGridSlot(occupied, columns, width, height);
      if (position.row + height > COLLAPSE_ROWS) {
        break;
      }
      occupyTimelineGridSlot(occupied, position.row, position.col, width, height);
      visible.push(items[index]);
    }
    return visible.length ? visible : items.slice(0, 1);
  }

  function estimateTimelineColumns() {
    const width = Math.max(0, groups.clientWidth || content.clientWidth || window.innerWidth);
    const styles = window.getComputedStyle(shell);
    const tile = Number.parseFloat(styles.getPropertyValue("--timeline-tile-size")) || 118;
    const gap = window.matchMedia("(max-width: 720px)").matches ? 6 : 8;
    return Math.max(1, Math.floor((width + gap) / (tile + gap)));
  }

  function findTimelineGridSlot(occupied, columns, width, height) {
    for (let row = 0; row < COLLAPSE_ROWS; row += 1) {
      for (let col = 0; col <= columns - width; col += 1) {
        if (timelineGridSlotFree(occupied, row, col, width, height)) {
          return { row, col };
        }
      }
    }
    return { row: COLLAPSE_ROWS, col: 0 };
  }

  function timelineGridSlotFree(occupied, row, col, width, height) {
    for (let y = row; y < row + height; y += 1) {
      for (let x = col; x < col + width; x += 1) {
        if (occupied[y]?.[x]) {
          return false;
        }
      }
    }
    return true;
  }

  function occupyTimelineGridSlot(occupied, row, col, width, height) {
    for (let y = row; y < row + height; y += 1) {
      if (!occupied[y]) {
        occupied[y] = [];
      }
      for (let x = col; x < col + width; x += 1) {
        occupied[y][x] = true;
      }
    }
  }

  function createTimelineCard(item, index, hiddenCount = 0, groupId = "") {
    item.path = item.path;
    const button = document.createElement("button");
    button.type = "button";
    button.className = `timeline-card ${item.type === "video" ? "video" : ""} ${hiddenCount > 0 ? "timeline-more-card" : ""}`;
    button.dataset.path = item.path;
    const span = cardSpan(item, index);
    button.style.setProperty("--span-x", String(span.x));
    button.style.setProperty("--span-y", String(span.y));
    const rating = item.rating > 0 ? `<span class="timeline-rating">${"★".repeat(item.rating)}</span>` : "";
    button.innerHTML = `
      <span class="timeline-thumb">
        ${item.type === "video" ? `<span class="timeline-video-badge">VIDEO</span><span class="timeline-video-icon">▶</span>` : `<img alt="${escapeHtml(item.name)}" loading="lazy" decoding="async" fetchpriority="low" />`}
        ${rating}
      </span>
      ${hiddenCount > 0 ? `<span class="timeline-more-badge" aria-hidden="true"><span class="timeline-more-icon">▦</span><span>还有 ${hiddenCount} 张</span></span>` : ""}
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
    if (hiddenCount > 0 && groupId) {
      button.setAttribute("aria-label", `展开剩余 ${hiddenCount} 张照片`);
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        stateLocal.expandedGroups.add(groupId);
        updateTimelineGroupExpansion(groupId);
      });
    } else {
      button.addEventListener("click", () => openTimelineItem(item, button));
    }
    return button;
  }

  function resetTimelineThumbnailQueue() {
    stateLocal.thumbQueue = [];
    stateLocal.thumbQueued.clear();
    stateLocal.thumbActive = 0;
    stateLocal.thumbObserver?.disconnect();
    stateLocal.thumbObserver = new IntersectionObserver((items) => {
      items.forEach((item) => {
        if (item.isIntersecting) {
          queueTimelineThumbnail(item.target);
        }
      });
    }, { root: content, rootMargin: "900px 0px" });
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

  function mergeTimelineItems(items) {
    const byPath = new Map(stateLocal.items.map((item) => [item.path, item]));
    items.forEach((item) => byPath.set(item.path, item));
    stateLocal.items = Array.from(byPath.values()).sort(compareTimelineItems);
  }

  function dedupeTimelineItems(items) {
    const byPath = new Map();
    items.forEach((item) => {
      if (item?.path) {
        byPath.set(item.path, item);
      }
    });
    return Array.from(byPath.values()).sort(compareTimelineItems);
  }

  function compareTimelineItems(left, right) {
    return (Number(right.takenAt || 0) - Number(left.takenAt || 0))
      || String(left.root || "").localeCompare(String(right.root || ""))
      || String(left.rel || left.path || "").localeCompare(String(right.rel || right.path || ""));
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
      return { x: 2, y: 1 };
    }
    const width = Number(item.width || 0);
    const height = Number(item.height || 0);
    if (width > 0 && height > 0) {
      const ratio = width / height;
      if (ratio >= 1.42) {
        return { x: 2, y: 1 };
      }
      if (ratio <= 0.72) {
        return { x: 1, y: 2 };
      }
      return { x: 1, y: 1 };
    }
    return { x: 1, y: 1 };
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
