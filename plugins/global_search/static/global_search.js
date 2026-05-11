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
        <span class="global-search-result-icon">${item.type === "folder" ? "DIR" : "IMG"}</span>
        <span class="global-search-result-main">
          <strong>${escapeHtml(item.name)}</strong>
          <small>${escapeHtml(displayPath(item))}</small>
        </span>
      `;
      button.addEventListener("click", () => openSearchResult(item));
      results.append(button);
    });
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
