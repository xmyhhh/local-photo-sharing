(() => {
  const dialog = document.createElement("dialog");
  dialog.id = "globalSearchDialog";
  dialog.className = "global-search-dialog";
  dialog.innerHTML = `
    <div class="global-search-panel">
      <header class="global-search-header">
        <div>
          <div class="global-search-kicker">全局索引</div>
          <h2>搜索所有目录</h2>
        </div>
        <button class="global-search-close" type="button" aria-label="关闭全局搜索">×</button>
      </header>
      <div class="global-search-box">
        <input class="global-search-input" type="search" placeholder="输入文件夹、照片或视频名称..." autocomplete="off" />
        <button class="global-search-refresh" type="button">刷新索引</button>
      </div>
      <div class="global-search-status">正在读取索引状态...</div>
      <div class="global-search-results"></div>
    </div>
  `;
  pluginDialogs.append(dialog);

  const input = dialog.querySelector(".global-search-input");
  const status = dialog.querySelector(".global-search-status");
  const results = dialog.querySelector(".global-search-results");
  const refreshButton = dialog.querySelector(".global-search-refresh");
  let searchTimer = 0;
  let statusTimer = 0;

  registerPluginAction("global_search.open", () => openGlobalSearch());

  dialog.querySelector(".global-search-close").addEventListener("click", () => dialog.close());
  input.addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(runSearch, 220);
  });
  refreshButton.addEventListener("click", async () => {
    status.textContent = "已请求刷新索引...";
    await fetchJson("/api/global-search/refresh", { method: "POST" });
    await refreshStatus();
  });
  dialog.addEventListener("close", () => {
    window.clearInterval(statusTimer);
    statusTimer = 0;
  });

  async function openGlobalSearch() {
    dialog.showModal();
    input.focus();
    await refreshStatus();
    await runSearch();
    if (!statusTimer) {
      statusTimer = window.setInterval(refreshStatus, 2500);
    }
  }

  async function refreshStatus() {
    try {
      const data = await fetchJson("/api/global-search/status", { cache: "no-store" });
      const indexedAt = data.indexedAt ? new Date(data.indexedAt * 1000).toLocaleTimeString() : "尚未完成";
      const suffix = data.error ? `，错误：${data.error}` : "";
      status.textContent = data.indexing
        ? `正在建立索引，当前 ${data.count || 0} 项${suffix}`
        : `已索引 ${data.count || 0} 项，上次更新 ${indexedAt}${suffix}`;
    } catch (error) {
      status.textContent = error.message;
    }
  }

  async function runSearch() {
    const query = input.value.trim();
    if (!query) {
      results.innerHTML = `<div class="global-search-empty">输入关键词后开始搜索。</div>`;
      return;
    }
    try {
      const data = await fetchJson(`/api/global-search/search?q=${encodeURIComponent(query)}&limit=80`, { cache: "no-store" });
      renderResults(data.results || []);
      await refreshStatus();
    } catch (error) {
      results.innerHTML = `<div class="global-search-empty">${escapeHtml(error.message)}</div>`;
    }
  }

  function renderResults(items) {
    results.innerHTML = "";
    if (!items.length) {
      results.innerHTML = `<div class="global-search-empty">没有找到匹配项。</div>`;
      return;
    }
    items.forEach((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "global-search-result";
      button.innerHTML = `
        ${renderResultPreview(item)}
        <span class="global-search-result-main">
          <strong>${escapeHtml(item.name)}</strong>
          <small>${escapeHtml(displayPath(item))}</small>
        </span>
      `;
      button.addEventListener("click", () => openSearchResult(item));
      results.append(button);
      loadSearchPreview(item, button.querySelector(".global-search-result-preview img"));
    });
  }

  function renderResultPreview(item) {
    if (!item.thumbUrl) {
      return `<span class="global-search-result-preview global-search-result-icon">DIR</span>`;
    }
    return `
      <span class="global-search-result-preview global-search-result-thumb">
        <span class="global-search-thumb-label">${item.type === "folder" ? "DIR" : "IMG"}</span>
        <img alt="" loading="lazy" />
      </span>
    `;
  }

  async function loadSearchPreview(item, img, attempt = 0) {
    if (!img?.isConnected || !item.thumbUrl) {
      return;
    }
    const previewPath = item.previewPath || item.path;
    try {
      const response = await fetch(`/api/thumb-status/${encodePath(previewPath)}?mode=small`, { cache: "no-store" });
      if (response.status === 200) {
        const data = await response.json();
        img.onload = () => img.classList.add("loaded");
        img.onerror = () => showPreviewFallback(item, img);
        img.src = withVersion(data.url || item.thumbUrl, item.mtime);
        if (img.complete && img.naturalWidth > 0) {
          img.classList.add("loaded");
        }
        return;
      }
      if (response.status !== 202) {
        showPreviewFallback(item, img);
        return;
      }
    } catch {
      showPreviewFallback(item, img);
      return;
    }
    if (attempt < 8) {
      window.setTimeout(() => loadSearchPreview(item, img, attempt + 1), Math.min(2600, 400 + attempt * 250));
    }
  }

  function showPreviewFallback(item, img) {
    if (!img?.isConnected) {
      return;
    }
    const previewPath = item.previewPath || item.path;
    img.onload = () => img.classList.add("loaded");
    img.onerror = () => img.removeAttribute("src");
    img.src = `/api/image/${encodePath(previewPath)}`;
  }

  function openSearchResult(item) {
    dialog.close();
    if (item.type === "folder") {
      openRootedFolder(item.path);
      return;
    }
    openRootedFolder(`${item.root}/${item.folder === "." ? "" : item.folder}`);
  }

  function openRootedFolder(path) {
    const [rootId, ...parts] = String(path || "").split("/");
    if (rootId && state.rootId !== rootId) {
      state.rootId = rootId;
    }
    navigateFolder(parts.join("/"));
  }

  function displayPath(item) {
    return `${item.root}/${item.rel}`;
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }
})();
