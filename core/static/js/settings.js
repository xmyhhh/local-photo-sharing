openSettingsBtn.addEventListener("click", openSettingsDialog);
closeSettingsBtn.addEventListener("click", () => settingsDialog.close());
settingsTabs().forEach((tab) => {
  tab.addEventListener("click", () => setSettingsTab(tab.dataset.settingsTab));
});
memoryPrefetchEnabledInput.addEventListener("change", saveGeneralSettings);
memoryPrefetchLimitInput.addEventListener("input", scheduleGeneralSettingsSave);
memoryPrefetchLimitInput.addEventListener("change", saveGeneralSettings);
memoryPrefetchLimitInput.addEventListener("blur", saveGeneralSettings);
clientPrefetchEnabledInput.addEventListener("change", saveClientPrefetchSettings);
[
  clientPrefetchThumbRadiusInput,
  clientPrefetchOriginalForwardInput,
  clientPrefetchOriginalBackwardInput,
  clientPrefetchOriginalConcurrencyInput,
  clientPrefetchOriginalQueueLimitInput,
].forEach((input) => {
  input.addEventListener("change", saveClientPrefetchSettings);
  input.addEventListener("blur", saveClientPrefetchSettings);
});
authEnabledInput.addEventListener("change", () => saveAuthSettings());
saveAuthPasswordBtn.addEventListener("click", saveAuthPassword);
loginBackgroundModeButtons().forEach((button) => {
  button.addEventListener("click", () => {
    loginBackgroundModeButtons().forEach((item) => item.classList.toggle("active", item === button));
    saveAuthSettings({ loginBackgroundMode: button.dataset.loginBackgroundMode });
  });
});
loginBackgroundLayoutButtons().forEach((button) => {
  button.addEventListener("click", () => {
    loginBackgroundLayoutButtons().forEach((item) => item.classList.toggle("active", item === button));
    saveAuthSettings({ loginBackgroundLayout: button.dataset.loginBackgroundLayout });
  });
});
loginBackgroundFolderInput.addEventListener("change", () => saveAuthSettings({ loginBackgroundFolder: loginBackgroundFolderInput.value.trim() }));
useCurrentLoginBackgroundFolderBtn.addEventListener("click", useCurrentLoginBackgroundFolder);
document.querySelectorAll(".settings-help").forEach((button) => {
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    const head = button.closest(".settings-card-head");
    const open = !head?.classList.contains("help-open");
    closeSettingsHelp();
    head?.classList.toggle("help-open", open);
  });
});
settingsDialog.addEventListener("click", (event) => {
  if (!event.target.closest(".settings-card-head")) {
    closeSettingsHelp();
  }
});

let generalSettingsSaveTimer = 0;
let generalSettingsLoaded = false;
let authSettingsLoaded = false;

async function openSettingsDialog() {
  setSettingsTab("general");
  settingsStatus.textContent = state.authEnabled && state.authRole !== "admin" ? "" : "正在读取设置...";
  pluginComponentList.innerHTML = "";
  settingsDialog.showModal();
  if (state.authEnabled && state.authRole !== "admin") {
    renderGuestSettings();
    return;
  }
  restoreAdminSettingsChrome();
  try {
    const [general, components] = await Promise.all([
      fetchJson("/api/settings/general", { cache: "no-store" }),
      fetchJson("/api/settings/components", { cache: "no-store" }),
    ]);
    renderGeneralSettings(general);
    applyComponentSettings(components);
    renderSettings(components);
    renderPluginSettingsTabs();
    settingsStatus.textContent = "";
  } catch (error) {
    settingsStatus.textContent = error.message;
  }
}

function setSettingsTab(tabName) {
  if (state.authEnabled && state.authRole !== "admin") {
    tabName = "general";
  }
  const pluginPage = getPluginSettingsPage(tabName);
  const name = pluginPage ? tabName : (["general", "auth", "plugins"].includes(tabName) ? tabName : "general");
  settingsTabs().forEach((tab) => {
    const active = tab.dataset.settingsTab === name;
    tab.classList.toggle("active", active);
    if (active) {
      tab.setAttribute("aria-current", "page");
    } else {
      tab.removeAttribute("aria-current");
    }
  });
  generalSettingsPanel.hidden = name !== "general";
  authSettingsPanel.hidden = name !== "auth";
  pluginsSettingsPanel.hidden = name !== "plugins";
  Array.from(pluginSettingsPages?.querySelectorAll(".settings-page") || []).forEach((page) => {
    page.hidden = page.dataset.settingsPage !== name;
  });
  const meta = pluginPage
    ? [pluginPage.kicker || "插件", pluginPage.title || "插件设置", pluginPage.description || ""]
    : {
    general: ["通用", "通用设置", "调整核心服务的运行策略。"],
    auth: ["安全", "访问控制", "管理登录页、游客入口和公开相册。"],
    plugins: ["扩展", "插件", "启用或禁用当前项目插件目录中的能力。"],
  }[name];
  settingsKicker.textContent = meta[0];
  settingsPageTitle.textContent = meta[1];
  settingsPageDescription.textContent = meta[2];
  if (pluginPage) {
    pluginPage.render?.();
  }
}

function renderGuestSettings() {
  generalSettingsLoaded = false;
  authSettingsLoaded = false;
  settingsTabs().forEach((tab) => {
    const isGeneral = tab.dataset.settingsTab === "general";
    tab.hidden = !isGeneral;
    tab.disabled = !isGeneral;
  });
  pluginSettingsTabs.innerHTML = "";
  themeModeSelect.value = state.themeMode;
  renderClientPrefetchSettings();
  memoryPrefetchEnabledInput.closest(".settings-card").hidden = true;
  authSettingsPanel.hidden = true;
  pluginsSettingsPanel.hidden = true;
  pluginSettingsPages.innerHTML = "";
  setSettingsTab("general");
  generalSettingsLoaded = true;
}

function restoreAdminSettingsChrome() {
  settingsTabs().forEach((tab) => {
    tab.hidden = false;
    tab.disabled = false;
  });
  memoryPrefetchEnabledInput.closest(".settings-card").hidden = false;
}

function renderGeneralSettings(settings) {
  const prefetch = settings.memoryPrefetch || {};
  generalSettingsLoaded = false;
  themeModeSelect.value = ["system", "light", "dark"].includes(settings.theme) ? settings.theme : "system";
  applyThemeMode(themeModeSelect.value);
  memoryPrefetchEnabledInput.checked = Boolean(prefetch.enabled);
  memoryPrefetchLimitInput.value = String(prefetch.memoryLimitMb || 1024);
  memoryPrefetchLimitInput.min = String(prefetch.minMb || 256);
  memoryPrefetchLimitInput.max = String(prefetch.maxMb || 1024);
  state.memoryPrefetchWindowBefore = Number.parseInt(prefetch.windowBefore, 10) || 5;
  state.memoryPrefetchWindowAfter = Number.parseInt(prefetch.windowAfter, 10) || 35;
  renderClientPrefetchSettings();
  generalSettingsLoaded = true;
  renderAuthSettings({
    enabled: state.authEnabled,
    hasPassword: state.authHasPassword,
    loginBackgroundMode: state.loginBackgroundMode,
    loginBackgroundFolder: state.loginBackgroundFolder,
    loginBackgroundLayout: state.loginBackgroundLayout,
  });
}

function renderAuthSettings(settings) {
  authSettingsLoaded = false;
  authEnabledInput.checked = Boolean(settings.enabled);
  authPasswordInput.value = "";
  authPasswordInput.placeholder = settings.hasPassword ? "已设置，留空则不修改" : "启用登录页前必须设置";
  const mode = ["none", "rated", "folder"].includes(settings.loginBackgroundMode) ? settings.loginBackgroundMode : "none";
  const layout = ["grid", "stack", "solo"].includes(settings.loginBackgroundLayout) ? settings.loginBackgroundLayout : "grid";
  loginBackgroundModeButtons().forEach((button) => {
    button.classList.toggle("active", button.dataset.loginBackgroundMode === mode);
  });
  loginBackgroundLayoutButtons().forEach((button) => {
    button.classList.toggle("active", button.dataset.loginBackgroundLayout === layout);
    button.disabled = mode === "none";
  });
  loginBackgroundFolderInput.value = settings.loginBackgroundFolder || "";
  loginBackgroundFolderInput.disabled = mode !== "folder";
  useCurrentLoginBackgroundFolderBtn.disabled = mode !== "folder";
  authSettingsLoaded = true;
}

function renderEditableList(container, values, onRemove) {
  container.innerHTML = "";
  if (!values.length) {
    const empty = document.createElement("div");
    empty.className = "settings-list-empty";
    empty.textContent = "还没有配置。";
    container.append(empty);
    return;
  }
  values.forEach((value) => {
    const item = document.createElement("div");
    item.className = "settings-chip";
    const text = document.createElement("span");
    text.textContent = value;
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("aria-label", `删除 ${value}`);
    button.textContent = "×";
    button.addEventListener("click", () => onRemove(value));
    item.append(text, button);
    container.append(item);
  });
}

async function saveAuthPassword() {
  if (!authSettingsLoaded) {
    return;
  }
  const password = authPasswordInput.value.trim();
  if (!password) {
    settingsStatus.textContent = "请输入管理员密码后再保存。";
    authPasswordInput.focus();
    return;
  }
  await saveAuthSettings({ password });
}

async function saveAuthSettings(overrides = null) {
  if (!authSettingsLoaded) {
    return;
  }
  if (!overrides && authEnabledInput.checked && !state.authHasPassword && !authPasswordInput.value.trim()) {
    authEnabledInput.checked = false;
    settingsStatus.textContent = "启用登录页前必须先设置管理员密码。";
    authPasswordInput.focus();
    return;
  }
  const payload = overrides || {
    enabled: authEnabledInput.checked,
    loginBackgroundMode: selectedLoginBackgroundMode(),
    loginBackgroundFolder: loginBackgroundFolderInput.value.trim(),
    loginBackgroundLayout: selectedLoginBackgroundLayout(),
  };
  if (authPasswordInput.value.trim() && (!overrides || Object.prototype.hasOwnProperty.call(overrides, "enabled"))) {
    payload.password = authPasswordInput.value.trim();
  }
  settingsStatus.textContent = "正在保存访问控制...";
  try {
    const settings = await fetchJson("/api/auth/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    applyAuthStatus(settings);
    renderAuthSettings(settings);
    renderGrid();
    if (payloadTouchesLoginBackground(payload) && typeof notifyBackendTaskStarted === "function") {
      notifyBackendTaskStarted();
    }
    settingsStatus.textContent = "访问控制已保存。";
  } catch (error) {
    settingsStatus.textContent = error.message;
    renderAuthSettings({
      enabled: state.authEnabled,
      hasPassword: state.authHasPassword,
      loginBackgroundMode: state.loginBackgroundMode,
      loginBackgroundFolder: state.loginBackgroundFolder,
      loginBackgroundLayout: state.loginBackgroundLayout,
    });
  }
}

function selectedLoginBackgroundMode() {
  return loginBackgroundModeButtons().find((button) => button.classList.contains("active"))?.dataset.loginBackgroundMode || "none";
}

function selectedLoginBackgroundLayout() {
  return loginBackgroundLayoutButtons().find((button) => button.classList.contains("active"))?.dataset.loginBackgroundLayout || "grid";
}

function payloadTouchesLoginBackground(payload) {
  return Boolean(payload && (
    Object.prototype.hasOwnProperty.call(payload, "publicAlbums")
    || Object.prototype.hasOwnProperty.call(payload, "loginBackgrounds")
    || Object.prototype.hasOwnProperty.call(payload, "loginBackgroundMode")
    || Object.prototype.hasOwnProperty.call(payload, "loginBackgroundFolder")
  ));
}

function useCurrentLoginBackgroundFolder() {
  if (!state.rootId) {
    settingsStatus.textContent = "请先进入一个具体根目录或文件夹。";
    return;
  }
  const folder = state.folder ? `${state.rootId}/${state.folder}` : state.rootId;
  loginBackgroundFolderInput.value = folder;
  saveAuthSettings({ loginBackgroundFolder: folder, loginBackgroundMode: "folder" });
}

function scheduleGeneralSettingsSave() {
  if (!generalSettingsLoaded) {
    return;
  }
  window.clearTimeout(generalSettingsSaveTimer);
  generalSettingsSaveTimer = window.setTimeout(saveGeneralSettings, 520);
}

function closeSettingsHelp() {
  document.querySelectorAll(".settings-card-head.help-open").forEach((item) => {
    item.classList.remove("help-open");
  });
}

function renderClientPrefetchSettings() {
  const settings = state.clientPrefetch;
  clientPrefetchEnabledInput.checked = settings.enabled;
  clientPrefetchThumbRadiusInput.value = String(settings.thumbNeighborRadius);
  clientPrefetchOriginalForwardInput.value = String(settings.originalForward);
  clientPrefetchOriginalBackwardInput.value = String(settings.originalBackward);
  clientPrefetchOriginalConcurrencyInput.value = String(settings.originalConcurrency);
  clientPrefetchOriginalQueueLimitInput.value = String(settings.originalQueueLimit);
  [
    clientPrefetchThumbRadiusInput,
    clientPrefetchOriginalForwardInput,
    clientPrefetchOriginalBackwardInput,
    clientPrefetchOriginalConcurrencyInput,
    clientPrefetchOriginalQueueLimitInput,
  ].forEach((input) => {
    input.disabled = !settings.enabled;
  });
}

function saveClientPrefetchSettings() {
  const wasEnabled = state.clientPrefetch.enabled;
  state.clientPrefetch = normalizeClientPrefetchSettings({
    enabled: clientPrefetchEnabledInput.checked,
    thumbNeighborRadius: clientPrefetchThumbRadiusInput.value,
    originalForward: clientPrefetchOriginalForwardInput.value,
    originalBackward: clientPrefetchOriginalBackwardInput.value,
    originalConcurrency: clientPrefetchOriginalConcurrencyInput.value,
    originalQueueLimit: clientPrefetchOriginalQueueLimitInput.value,
  });
  window.localStorage.setItem(CLIENT_PREFETCH_STORAGE_KEY, JSON.stringify(state.clientPrefetch));
  renderClientPrefetchSettings();
  if (wasEnabled && !state.clientPrefetch.enabled) {
    disableClientPrefetchWork();
  }
  if (generalSettingsLoaded) {
    settingsStatus.textContent = "本机预下载设置已保存。";
  }
}

function disableClientPrefetchWork() {
  dropQueuedNeighborThumbnails();
  state.thumbNeighborPrefetchKey = "";
  cancelClientOriginalPrefetches();
}

async function saveGeneralSettings() {
  if (!generalSettingsLoaded) {
    return;
  }
  window.clearTimeout(generalSettingsSaveTimer);
  if (state.authEnabled && state.authRole !== "admin") {
    settingsStatus.textContent = "";
    return;
  }
  const memoryLimitMb = Number.parseInt(memoryPrefetchLimitInput.value, 10);
  const minMb = Number.parseInt(memoryPrefetchLimitInput.min, 10) || 256;
  const maxMb = Number.parseInt(memoryPrefetchLimitInput.max, 10) || 1024;
  if (!Number.isFinite(memoryLimitMb) || memoryLimitMb < minMb || memoryLimitMb > maxMb) {
    settingsStatus.textContent = `内存上限必须是 ${minMb} 到 ${maxMb} 之间的整数 MB。`;
    return;
  }
  settingsStatus.textContent = "正在保存通用设置...";
  try {
    const settings = await fetchJson("/api/settings/general", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        memoryPrefetch: {
          enabled: memoryPrefetchEnabledInput.checked,
          memoryLimitMb,
        },
        theme: themeModeSelect.value,
      }),
    });
    renderGeneralSettings(settings);
    settingsStatus.textContent = "已自动保存。";
  } catch (error) {
    settingsStatus.textContent = error.message;
  }
}

themeModeSelect.addEventListener("change", () => {
  applyThemeMode(themeModeSelect.value);
  saveGeneralSettings();
});

function renderSettings(settings) {
  pluginComponentList.innerHTML = "";
  (settings.plugins || []).forEach((plugin) => {
    pluginComponentList.append(createComponentRow({
      id: plugin.name,
      title: plugin.title || plugin.name,
      description: plugin.description || "",
      path: plugin.path || plugin.module || "",
      enabled: state.enabledPlugins.has(plugin.name),
      kind: "plugin",
    }));
  });
}

function createComponentRow(item) {
  const row = document.createElement("div");
  row.className = "plugin-row";
  row.classList.toggle("enabled", item.enabled);
  const icon = document.createElement("div");
  icon.className = "plugin-row-icon";
  icon.textContent = pluginInitials(item.title || item.id);
  const text = document.createElement("div");
  text.className = "plugin-row-main";
  const titleLine = document.createElement("div");
  titleLine.className = "plugin-title-line";
  const title = document.createElement("div");
  title.className = "plugin-title";
  title.textContent = item.title;
  const status = document.createElement("span");
  status.className = item.enabled ? "plugin-status enabled" : "plugin-status";
  status.textContent = item.enabled ? "运行中" : "未启用";
  titleLine.append(title, status);
  const desc = document.createElement("div");
  desc.className = "plugin-description";
  desc.textContent = item.description || "这个插件还没有填写简介。";
  const meta = document.createElement("div");
  meta.className = "plugin-meta";
  meta.textContent = item.path || item.id;
  text.append(titleLine, desc, meta);

  const button = document.createElement("button");
  button.type = "button";
  button.className = item.enabled ? "plugin-toggle enabled" : "plugin-toggle";
  button.textContent = item.enabled ? "禁用" : "启用";
  button.addEventListener("click", () => toggleComponent(item));
  row.append(icon, text, button);
  return row;
}

function pluginInitials(value) {
  return String(value || "?").trim().slice(0, 2).toUpperCase();
}

async function toggleComponent(item) {
  const plugins = {};
  state.pluginComponents.forEach((component) => {
    if (component.plugin && component.plugin !== "core") {
      plugins[component.plugin] = state.enabledPlugins.has(component.plugin);
    }
  });
  state.pluginAssets.forEach((asset) => {
    plugins[asset.name] = state.enabledPlugins.has(asset.name);
  });

  plugins[item.id] = !state.enabledPlugins.has(item.id);

  settingsStatus.textContent = "正在保存设置...";
  try {
    const settings = await fetchJson("/api/settings/components", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plugins }),
    });
    applyComponentSettings(settings);
    await loadPluginAssets();
    renderSettings(settings);
    renderPluginSettingsTabs();
    renderGrid();
    settingsStatus.textContent = "设置已保存。";
  } catch (error) {
    settingsStatus.textContent = error.message;
  }
}

function applyComponentSettings(settings) {
  state.enabledPlugins = new Set(settings.enabledPlugins || []);
  state.pluginAssets = settings.pluginAssets || state.pluginAssets;
  state.pluginComponents = settings.pluginComponents || state.pluginComponents;
}
