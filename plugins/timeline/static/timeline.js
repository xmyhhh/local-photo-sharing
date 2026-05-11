(() => {
  const PAGE_SIZE = 180;
  const stateLocal = {
    featured: false,
    scale: "day",
    cursor: 0,
    loading: false,
    done: false,
    items: [],
    statusTimer: 0,
    previousEntries: null,
  };

  const dialog = document.createElement("dialog");
  dialog.id = "timelineDialog";
  dialog.className = "timeline-dialog";
  dialog.innerHTML = `
    <div class="timeline-shell">
      <header class="timeline-header">
        <div>
          <div class="timeline-kicker">时间线</div>
          <h2>照片流</h2>
          <div class="timeline-status">正在读取时间线索引...</div>
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
        <button class="timeline-refresh" type="button">刷新索引</button>
      </div>
      <div class="timeline-content">
        <div class="timeline-groups"></div>
        <div class="timeline-sentinel"></div>
      </div>
    </div>
  `;
  pluginDialogs.append(dialog);

  const status = dialog.querySelector(".timeline-status");
  const groups = dialog.querySelector(".timeline-groups");
  const content = dialog.querySelector(".timeline-content");
  const sentinel = dialog.querySelector(".timeline-sentinel");
  const observer = new IntersectionObserver((items) => {
    if (items.some((item) => item.isIntersecting)) {
      loadNextPage();
    }
  }, { root: content, rootMargin: "900px 0px" });

  registerPluginAction("timeline.open", () => openTimeline());

  dialog.querySelector(".timeline-close").addEventListener("click", () => dialog.close());
  dialog.querySelector(".timeline-refresh").addEventListener("click", async () => {
    status.textContent = "已请求刷新时间线索引...";
    await fetchJson("/api/timeline/refresh", { method: "POST" });
    resetAndLoad();
  });
  dialog.querySelectorAll("[data-timeline-featured]").forEach((button) => {
    button.addEventListener("click", () => {
      stateLocal.featured = button.dataset.timelineFeatured === "1";
      updateToolbar();
      resetAndLoad();
    });
  });
  dialog.querySelectorAll("[data-timeline-scale]").forEach((button) => {
    button.addEventListener("click", () => {
      stateLocal.scale = button.dataset.timelineScale;
      updateToolbar();
      renderTimeline();
    });
  });
  dialog.addEventListener("close", () => {
    window.clearInterval(stateLocal.statusTimer);
    stateLocal.statusTimer = 0;
    observer.unobserve(sentinel);
  });
  viewer.addEventListener("close", restoreGalleryEntriesAfterTimelineViewer);

  async function openTimeline() {
    dialog.showModal();
    observer.observe(sentinel);
    await resetAndLoad();
    if (!stateLocal.statusTimer) {
      stateLocal.statusTimer = window.setInterval(refreshStatus, 3000);
    }
  }

  async function resetAndLoad() {
    stateLocal.cursor = 0;
    stateLocal.done = false;
    stateLocal.items = [];
    groups.innerHTML = `<div class="timeline-empty"><span class="spinner inline-spinner"></span><span>正在打开时间线...</span></div>`;
    await Promise.all([refreshStatus(), loadNextPage()]);
  }

  async function refreshStatus() {
    try {
      const data = await fetchJson("/api/timeline/status", { cache: "no-store" });
      const indexedAt = data.indexedAt ? new Date(data.indexedAt * 1000).toLocaleTimeString() : "尚未完成";
      const suffix = data.error ? `，错误：${data.error}` : "";
      status.textContent = data.indexing
        ? `正在建立索引，当前 ${data.count || 0} 项${suffix}`
        : `已索引 ${data.count || 0} 项，精选 ${data.featuredCount || 0} 项，上次更新 ${indexedAt}${suffix}`;
    } catch (error) {
      status.textContent = error.message;
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
      stateLocal.items.push(...(data.items || []));
      stateLocal.cursor = data.nextCursor || 0;
      stateLocal.done = data.nextCursor === null || data.nextCursor === undefined;
      renderTimeline();
      if (data.status) {
        renderStatus(data.status);
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
    const indexedAt = data.indexedAt ? new Date(data.indexedAt * 1000).toLocaleTimeString() : "尚未完成";
    status.textContent = data.indexing
      ? `正在建立索引，当前 ${data.count || 0} 项`
      : `已索引 ${data.count || 0} 项，精选 ${data.featuredCount || 0} 项，上次更新 ${indexedAt}`;
  }

  function renderTimeline() {
    groups.innerHTML = "";
    if (!stateLocal.items.length) {
      groups.innerHTML = `<div class="timeline-empty">${stateLocal.featured ? "还没有有评级的精选照片。" : "时间线里还没有照片。"}</div>`;
      return;
    }
    const fragment = document.createDocumentFragment();
    groupItems(stateLocal.items, stateLocal.scale).forEach((group) => {
      fragment.append(createTimelineGroup(group));
    });
    groups.append(fragment);
  }

  function createTimelineGroup(group) {
    const section = document.createElement("section");
    section.className = "timeline-group";
    section.innerHTML = `
      <div class="timeline-group-head">
        <div>
          <div class="timeline-group-title">${escapeHtml(group.title)}</div>
          <div class="timeline-group-subtitle">${group.items.length} 项</div>
        </div>
      </div>
      <div class="timeline-mosaic"></div>
    `;
    const mosaic = section.querySelector(".timeline-mosaic");
    group.items.forEach((item, index) => {
      const card = createTimelineCard(item, index);
      mosaic.append(card);
    });
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
        ${item.type === "video" ? `<span class="timeline-video-badge">VIDEO</span><span class="timeline-video-icon">▶</span>` : `<img alt="${escapeHtml(item.name)}" loading="lazy" decoding="async" />`}
        ${rating}
      </span>
      <span class="timeline-card-meta">
        <span>${escapeHtml(timeLabel(item.takenAt))}</span>
      </span>
    `;
    if (item.type === "photo") {
      const img = button.querySelector("img");
      loadTimelineThumbnail(item, img);
    }
    button.addEventListener("click", () => openTimelineItem(item, button));
    return button;
  }

  async function loadTimelineThumbnail(item, img, attempt = 0) {
    if (!img?.isConnected) {
      return;
    }
    try {
      const response = await fetch(`/api/thumb-status/${encodePath(item.path)}?mode=${state.thumbMode || "medium"}`, { cache: "no-store" });
      if (response.status === 200) {
        const data = await response.json();
        img.onload = () => img.classList.add("loaded");
        img.onerror = () => showTimelineImageFallback(item, img);
        img.src = withVersion(data.url || item.thumbUrl, item.mtime);
        if (img.complete && img.naturalWidth > 0) {
          img.classList.add("loaded");
        }
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
    if (attempt < 10) {
      window.setTimeout(() => loadTimelineThumbnail(item, img, attempt + 1), Math.min(2800, 380 + attempt * 240));
    }
  }

  function showTimelineImageFallback(item, img) {
    if (!img?.isConnected) {
      return;
    }
    img.onload = () => img.classList.add("loaded");
    img.onerror = () => img.removeAttribute("src");
    img.src = `/api/image/${encodePath(item.path)}`;
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
        map.set(key.id, { title: key.title, items: [] });
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
    if (scale === "year") {
      return { id: String(year), title: `${year} 年` };
    }
    if (scale === "month") {
      return { id: `${year}-${month}`, title: `${year} 年 ${month} 月` };
    }
    return { id: `${year}-${month}-${day}`, title: dayTitle(date) };
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

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }
})();
