(function () {
  const STORAGE_KEY = "dynamicScreensaver.settings.v1";
  const DEFAULTS = {
    enabled: false,
    idleMinutes: 5,
    folder: "",
    minRating: 1,
    slideSeconds: 8,
  };

  let settings = loadScreensaverSettings();
  let idleTimer = 0;
  let slideTimer = 0;
  let active = false;
  let photos = [];
  let index = -1;
  let overlay = null;
  let stage = null;
  let caption = null;
  let statusText = null;
  let lastLayer = null;
  let warmupTimer = 0;
  let warmupKey = "";
  let requestedFullscreen = false;

  registerPluginAction("dynamic_screensaver.open", openScreensaverSettings);
  registerPluginSettingsPage("dynamic_screensaver.settings", renderScreensaverSettingsPage);
  document.addEventListener("photo-share:plugins-ready", initializeScreensaver);

  if (document.readyState !== "loading") {
    initializeScreensaver();
  }

  function initializeScreensaver() {
    ensureScreensaverDom();
    bindActivityListeners();
    scheduleScreensaver();
    requestScreensaverWarmup({ startup: true });
  }

  function ensureScreensaverDom() {
    if (overlay) {
      return;
    }
    overlay = document.createElement("div");
    overlay.id = "dynamicScreensaverOverlay";
    overlay.className = "dynamic-screensaver";
    overlay.hidden = true;
    overlay.innerHTML = `
      <div class="dynamic-screensaver-stage"></div>
      <div class="dynamic-screensaver-vignette"></div>
      <div class="dynamic-screensaver-caption"></div>
    `;
    document.body.append(overlay);
    stage = overlay.querySelector(".dynamic-screensaver-stage");
    caption = overlay.querySelector(".dynamic-screensaver-caption");
    overlay.addEventListener("pointerdown", stopScreensaver);
    overlay.addEventListener("wheel", stopScreensaver, { passive: true });

  }

  function screensaverSettingsMarkup() {
    return `
      <section class="settings-card dynamic-screensaver-settings-card">
        <label class="dynamic-screensaver-switch">
          <span>启用本机屏保</span>
          <input id="dynamicScreensaverEnabled" type="checkbox" />
        </label>
        <div class="dynamic-screensaver-fields">
          <label>
            <span>无操作分钟</span>
            <input id="dynamicScreensaverIdle" type="number" min="1" max="240" step="1" />
          </label>
          <label>
            <span>每张秒数</span>
            <input id="dynamicScreensaverSlideSeconds" type="number" min="3" max="120" step="1" />
          </label>
          <label>
            <span>最低星级</span>
            <select id="dynamicScreensaverMinRating">
              <option value="1">1 星以上</option>
              <option value="2">2 星以上</option>
              <option value="3">3 星以上</option>
              <option value="4">4 星以上</option>
              <option value="5">5 星</option>
            </select>
          </label>
        </div>
        <label>
          <span>限定目录</span>
          <input id="dynamicScreensaverFolder" type="text" autocomplete="off" placeholder="例如 root1/DCIM/109_FUJ1，留空为全部图库" />
        </label>
        <div class="dynamic-screensaver-actions">
          <button id="dynamicScreensaverUseCurrent" class="ghost" type="button">使用当前目录</button>
          <button id="dynamicScreensaverClearFolder" class="ghost" type="button">全部图库</button>
          <button id="dynamicScreensaverPreview" class="ghost" type="button">立即预览</button>
          <button id="dynamicScreensaverSave" type="button">保存</button>
        </div>
        <div id="dynamicScreensaverStatus" class="dynamic-screensaver-status"></div>
      </section>
    `;
  }

  function renderScreensaverSettingsPage() {
    const panel = document.querySelector('[data-settings-page="plugin:dynamic_screensaver.settings"]');
    if (!panel) {
      return;
    }
    if (!panel.dataset.dynamicScreensaverReady) {
      panel.innerHTML = screensaverSettingsMarkup();
      panel.dataset.dynamicScreensaverReady = "1";
      statusText = panel.querySelector("#dynamicScreensaverStatus");
      panel.querySelector("#dynamicScreensaverUseCurrent").addEventListener("click", useCurrentFolder);
      panel.querySelector("#dynamicScreensaverClearFolder").addEventListener("click", () => {
        panel.querySelector("#dynamicScreensaverFolder").value = "";
      });
      panel.querySelector("#dynamicScreensaverPreview").addEventListener("click", () => {
        saveFromPanel(panel);
        requestScreensaverWarmup({ force: true });
        closeOpenDialogsForPreview();
        window.requestAnimationFrame(() => startScreensaver({ manual: true }));
      });
      panel.querySelector("#dynamicScreensaverSave").addEventListener("click", () => {
        saveFromPanel(panel);
        statusText.textContent = "已保存到本机。屏保会在启动前按需准备缓存。";
      });
      ["#dynamicScreensaverEnabled", "#dynamicScreensaverIdle", "#dynamicScreensaverSlideSeconds", "#dynamicScreensaverMinRating", "#dynamicScreensaverFolder"].forEach((selector) => {
        panel.querySelector(selector).addEventListener("change", () => saveFromPanel(panel));
      });
    }
    renderPanelValues(panel);
  }

  function openScreensaverSettings() {
    if (typeof setSettingsTab === "function") {
      openSettingsDialog().then(() => setSettingsTab("plugin:dynamic_screensaver.settings")).catch(() => null);
    }
  }

  function renderPanelValues(panel) {
    panel.querySelector("#dynamicScreensaverEnabled").checked = settings.enabled;
    panel.querySelector("#dynamicScreensaverIdle").value = String(settings.idleMinutes);
    panel.querySelector("#dynamicScreensaverSlideSeconds").value = String(settings.slideSeconds);
    panel.querySelector("#dynamicScreensaverMinRating").value = String(settings.minRating);
    panel.querySelector("#dynamicScreensaverFolder").value = settings.folder;
  }

  function saveFromPanel(panel) {
    settings = {
      enabled: panel.querySelector("#dynamicScreensaverEnabled").checked,
      idleMinutes: clampInt(panel.querySelector("#dynamicScreensaverIdle").value, 1, 240, DEFAULTS.idleMinutes),
      slideSeconds: clampInt(panel.querySelector("#dynamicScreensaverSlideSeconds").value, 3, 120, DEFAULTS.slideSeconds),
      minRating: clampInt(panel.querySelector("#dynamicScreensaverMinRating").value, 1, 5, DEFAULTS.minRating),
      folder: normalizeScreensaverFolder(panel.querySelector("#dynamicScreensaverFolder").value),
    };
    saveScreensaverSettings(settings);
    scheduleScreensaver();
    if (settings.enabled && statusText) {
      requestScreensaverWarmup({ startup: false });
    }
  }

  function useCurrentFolder() {
    const panel = document.querySelector('[data-settings-page="plugin:dynamic_screensaver.settings"]');
    if (!state.rootId) {
      if (statusText) {
        statusText.textContent = "当前在根目录，请先进入一个图库目录。";
      }
      return;
    }
    const folder = state.folder ? `${state.rootId}/${state.folder}` : state.rootId;
    const input = panel?.querySelector("#dynamicScreensaverFolder");
    if (input) {
      input.value = folder;
      saveFromPanel(panel);
    }
  }

  function bindActivityListeners() {
    if (window.__dynamicScreensaverActivityBound) {
      return;
    }
    window.__dynamicScreensaverActivityBound = true;
    ["pointerdown", "mousemove", "keydown", "wheel", "touchstart", "scroll"].forEach((eventName) => {
      window.addEventListener(eventName, handleActivity, { passive: true, capture: true });
    });
    document.addEventListener("fullscreenchange", () => {
      if (document.fullscreenElement !== overlay) {
        requestedFullscreen = false;
      }
    });
  }

  function handleActivity() {
    if (active) {
      stopScreensaver();
      return;
    }
    scheduleScreensaver();
  }

  function scheduleScreensaver() {
    window.clearTimeout(idleTimer);
    if (!settings.enabled || !state.enabledPlugins.has("dynamic_screensaver")) {
      return;
    }
    idleTimer = window.setTimeout(() => startScreensaver({ manual: false }), settings.idleMinutes * 60 * 1000);
  }

  async function requestScreensaverWarmup({ force = false, startup = false } = {}) {
    if (!settings.enabled || !state.enabledPlugins.has("dynamic_screensaver")) {
      return;
    }
    if (!startup && document.hidden && !force) {
      return;
    }
    const nextKey = `${settings.folder}|${settings.minRating}`;
    if (!force && warmupKey === nextKey) {
      return;
    }
    warmupKey = nextKey;
    try {
      const data = await fetchJson("/api/dynamic-screensaver/warmup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          folder: settings.folder,
          minRating: settings.minRating,
          limit: 360,
          force,
        }),
      });
      updateWarmupStatus(data);
      if (!startup || document.visibilityState === "visible") {
        pollWarmupStatus();
      }
    } catch (error) {
      if (statusText) {
        statusText.textContent = error.message || "屏保缓存准备失败。";
      }
    }
  }

  function pollWarmupStatus() {
    window.clearTimeout(warmupTimer);
    if (!settings.enabled || !state.enabledPlugins.has("dynamic_screensaver")) {
      return;
    }
    if (document.hidden && !active) {
      return;
    }
    warmupTimer = window.setTimeout(async () => {
      const params = new URLSearchParams();
      params.set("minRating", String(settings.minRating));
      params.set("limit", "360");
      if (settings.folder) {
        params.set("folder", settings.folder);
      }
      try {
        const data = await fetchJson(`/api/dynamic-screensaver/warmup?${params.toString()}`, { cache: "no-store" });
        updateWarmupStatus(data);
        if (data.state === "queued" || data.state === "running") {
          pollWarmupStatus();
        }
      } catch {
        pollWarmupStatus();
      }
    }, 1600);
  }

  function updateWarmupStatus(data) {
    if (!statusText || !data) {
      return;
    }
    if (data.state === "queued" || data.state === "running") {
      statusText.textContent = `正在准备屏保缓存：${data.prepared || 0}/${data.matched || 0}，已扫描 ${data.scanned || 0} 张。`;
    } else if (data.state === "ready") {
      statusText.textContent = `屏保缓存已准备：${data.prepared || 0} 张。`;
    } else if (data.state === "error") {
      statusText.textContent = data.error || "屏保缓存准备失败。";
    }
  }

  async function startScreensaver({ manual }) {
    const blockingDialog = document.querySelector("#pluginDialogs dialog[open]") || settingsDialog?.open;
    if (!state.enabledPlugins.has("dynamic_screensaver") || active || viewer?.open || uploadDialog?.open || blockingDialog) {
      scheduleScreensaver();
      return;
    }
    ensureScreensaverDom();
    active = true;
    overlay.hidden = false;
    overlay.classList.add("active");
    enterScreensaverFullscreen();
    caption.textContent = "正在载入评分照片...";
    try {
      photos = await fetchScreensaverPhotos({ waitForFirstBatch: true });
      if (!photos.length) {
        caption.textContent = "暂时还没有找到可播放的评分照片。";
        window.setTimeout(stopScreensaver, manual ? 3600 : 2600);
        return;
      }
      index = Math.floor(Math.random() * photos.length) - 1;
      showNextSlide();
    } catch (error) {
      caption.textContent = error.message || "屏保启动失败。";
      window.setTimeout(stopScreensaver, manual ? 3600 : 2600);
    }
  }

  async function fetchScreensaverPhotos(options = {}) {
    const params = new URLSearchParams();
    params.set("minRating", String(settings.minRating));
    params.set("limit", "360");
    if (settings.folder) {
      params.set("folder", settings.folder);
    }
    const attempts = options.waitForFirstBatch ? 10 : 1;
    let lastPhotos = [];
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      const data = await fetchJson(`/api/dynamic-screensaver/photos?${params.toString()}`, { cache: "no-store" });
      updateWarmupStatus(data.warmup);
      lastPhotos = data.photos || [];
      if (lastPhotos.length || !data.warmup || !["queued", "running"].includes(data.warmup.state)) {
        return lastPhotos;
      }
      caption.textContent = `正在准备评分照片... 已发现 ${data.warmup.matched || 0} 张`;
      await delay(650);
    }
    return lastPhotos;
  }

  async function showNextSlide() {
    if (!active || !photos.length) {
      return;
    }
    const slide = await findLoadableSlide();
    if (!active) {
      return;
    }
    if (!slide) {
      caption.textContent = "这些照片暂时无法预览。";
      window.clearTimeout(slideTimer);
      slideTimer = window.setTimeout(stopScreensaver, 3200);
      return;
    }
    const { photo, url } = slide;
    const layer = document.createElement("div");
    layer.className = "dynamic-screensaver-slide";
    layer.style.backgroundImage = `url("${cssUrl(url)}")`;
    layer.dataset.motion = String(index % 4);
    stage.append(layer);
    requestAnimationFrame(() => layer.classList.add("visible"));
    if (lastLayer) {
      const leaving = lastLayer;
      leaving.classList.add("leaving");
      window.setTimeout(() => leaving.remove(), 1400);
    }
    lastLayer = layer;
    caption.textContent = `${photo.path} · ${photo.rating} 星`;
    window.clearTimeout(slideTimer);
    slideTimer = window.setTimeout(showNextSlide, settings.slideSeconds * 1000);
    preloadUpcoming();
  }

  async function findLoadableSlide() {
    const attempts = Math.min(photos.length, 12);
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      index = (index + 1) % photos.length;
      const photo = photos[index];
      const candidates = uniqueUrls(await resolveSlideUrls(photo));
      for (const url of candidates) {
        if (await canLoadImage(url)) {
          return { photo, url };
        }
      }
    }
    return null;
  }

  async function resolveSlideUrl(photo) {
    const urls = await resolveSlideUrls(photo);
    return urls[0] || "";
  }

  async function resolveSlideUrls(photo) {
    if (photo.preparedUrl) {
      return [photo.preparedUrl, photo.thumbUrl, photo.imageUrl];
    }
    if (photo.browserRenderable) {
      return [photo.thumbUrl, photo.imageUrl];
    }
    for (let attempt = 0; attempt < 3; attempt += 1) {
      const response = await fetch(`/api/preview-status/${encodePath(photo.path)}`, { cache: "no-store" });
      const data = await response.json().catch(() => ({}));
      if (response.ok && data.url) {
        return [data.url, photo.thumbUrl, photo.imageUrl];
      }
      await delay(450);
    }
    return [photo.thumbUrl, photo.imageUrl];
  }

  function preloadUpcoming() {
    for (let offset = 1; offset <= 5 && offset < photos.length; offset += 1) {
      const photo = photos[(index + offset) % photos.length];
      const image = new Image();
      image.src = photo.preparedUrl || photo.thumbUrl || photo.imageUrl;
    }
  }

  function stopScreensaver() {
    if (!active) {
      return;
    }
    active = false;
    window.clearTimeout(slideTimer);
    exitScreensaverFullscreen();
    overlay.classList.remove("active");
    window.setTimeout(() => {
      if (!active) {
        overlay.hidden = true;
        stage.innerHTML = "";
        lastLayer = null;
      }
    }, 220);
    scheduleScreensaver();
  }

  function closeOpenDialogsForPreview() {
    document.querySelectorAll("#pluginDialogs dialog[open]").forEach((dialog) => {
      dialog.close();
    });
    if (settingsDialog?.open) {
      settingsDialog.close();
    }
  }

  async function enterScreensaverFullscreen() {
    if (!overlay || document.fullscreenElement || !overlay.requestFullscreen) {
      return;
    }
    try {
      await overlay.requestFullscreen({ navigationUI: "hide" });
      requestedFullscreen = true;
    } catch {
      requestedFullscreen = false;
    }
  }

  function exitScreensaverFullscreen() {
    if (!requestedFullscreen || document.fullscreenElement !== overlay || !document.exitFullscreen) {
      requestedFullscreen = false;
      return;
    }
    document.exitFullscreen().catch(() => {});
    requestedFullscreen = false;
  }

  function loadScreensaverSettings() {
    try {
      return { ...DEFAULTS, ...JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "{}") };
    } catch {
      return { ...DEFAULTS };
    }
  }

  function saveScreensaverSettings(value) {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  }

  function normalizeScreensaverFolder(value) {
    return String(value || "").replace(/\\/g, "/").replace(/^\/+|\/+$/g, "").split("/").map((part) => part.trim()).filter(Boolean).join("/");
  }

  function clampInt(value, min, max, fallback) {
    const parsed = Number.parseInt(value, 10);
    if (!Number.isFinite(parsed)) {
      return fallback;
    }
    return Math.max(min, Math.min(max, parsed));
  }

  function cssUrl(value) {
    return String(value || "").replace(/"/g, "%22");
  }

  function uniqueUrls(values) {
    return [...new Set(values.filter(Boolean))];
  }

  function canLoadImage(url) {
    return new Promise((resolve) => {
      if (!url) {
        resolve(false);
        return;
      }
      const image = new Image();
      image.onload = () => resolve(true);
      image.onerror = () => resolve(false);
      image.src = url;
    });
  }

  function delay(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }
})();
