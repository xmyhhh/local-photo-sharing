openSettingsBtn.addEventListener("click", openSettingsDialog);
closeSettingsBtn.addEventListener("click", () => settingsDialog.close());
settingsTabs.forEach((tab) => {
  tab.addEventListener("click", () => setSettingsTab(tab.dataset.settingsTab));
});
saveGeneralSettingsBtn.addEventListener("click", saveGeneralSettings);

async function openSettingsDialog() {
  setSettingsTab("general");
  settingsStatus.textContent = "正在读取设置...";
  pluginComponentList.innerHTML = "";
  settingsDialog.showModal();
  try {
    const [general, components] = await Promise.all([
      fetchJson("/api/settings/general", { cache: "no-store" }),
      fetchJson("/api/settings/components", { cache: "no-store" }),
    ]);
    renderGeneralSettings(general);
    applyComponentSettings(components);
    renderSettings(components);
    settingsStatus.textContent = "";
  } catch (error) {
    settingsStatus.textContent = error.message;
  }
}

function setSettingsTab(tabName) {
  const name = tabName === "plugins" ? "plugins" : "general";
  settingsTabs.forEach((tab) => {
    const active = tab.dataset.settingsTab === name;
    tab.classList.toggle("active", active);
    if (active) {
      tab.setAttribute("aria-current", "page");
    } else {
      tab.removeAttribute("aria-current");
    }
  });
  generalSettingsPanel.hidden = name !== "general";
  pluginsSettingsPanel.hidden = name !== "plugins";
  settingsKicker.textContent = name === "general" ? "通用" : "扩展";
  settingsPageTitle.textContent = name === "general" ? "通用设置" : "插件";
  settingsPageDescription.textContent = name === "general"
    ? "调整核心服务的运行策略。"
    : "启用或禁用当前项目插件目录中的能力。";
}

function renderGeneralSettings(settings) {
  const prefetch = settings.memoryPrefetch || {};
  memoryPrefetchEnabledInput.checked = Boolean(prefetch.enabled);
  memoryPrefetchLimitInput.value = String(prefetch.memoryLimitGb || 2);
  memoryPrefetchLimitInput.min = String(prefetch.minGb || 1);
  memoryPrefetchLimitInput.max = String(prefetch.maxGb || 16);
}

async function saveGeneralSettings() {
  const memoryLimitGb = Number.parseInt(memoryPrefetchLimitInput.value, 10);
  if (!Number.isFinite(memoryLimitGb) || memoryLimitGb < 1 || memoryLimitGb > 16) {
    settingsStatus.textContent = "内存上限必须是 1 到 16 之间的整数 GB。";
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
          memoryLimitGb,
        },
      }),
    });
    renderGeneralSettings(settings);
    settingsStatus.textContent = "通用设置已保存。";
  } catch (error) {
    settingsStatus.textContent = error.message;
  }
}

function renderSettings(settings) {
  pluginComponentList.innerHTML = "";
  (settings.plugins || []).forEach((plugin) => {
    pluginComponentList.append(createComponentRow({
      id: plugin.name,
      title: plugin.title || plugin.name,
      description: plugin.description || plugin.path || "",
      enabled: state.enabledPlugins.has(plugin.name),
      kind: "plugin",
    }));
  });
}

function createComponentRow(item) {
  const row = document.createElement("div");
  row.className = "plugin-row";
  const text = document.createElement("div");
  text.className = "plugin-row-main";
  const title = document.createElement("div");
  title.className = "plugin-title";
  title.textContent = item.title;
  const desc = document.createElement("div");
  desc.className = "plugin-description";
  desc.textContent = item.description || item.id;
  const meta = document.createElement("div");
  meta.className = "plugin-meta";
  meta.textContent = item.id;
  text.append(title, desc, meta);

  const button = document.createElement("button");
  button.type = "button";
  button.className = item.enabled ? "plugin-toggle enabled" : "plugin-toggle";
  button.textContent = item.enabled ? "已启用" : "启用";
  button.addEventListener("click", () => toggleComponent(item));
  row.append(text, button);
  return row;
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
