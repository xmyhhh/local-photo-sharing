openSettingsBtn.addEventListener("click", openSettingsDialog);
closeSettingsBtn.addEventListener("click", () => settingsDialog.close());

async function openSettingsDialog() {
  settingsStatus.textContent = "正在读取组件列表...";
  pluginComponentList.innerHTML = "";
  settingsDialog.showModal();
  try {
    const settings = await fetchJson("/api/settings/components", { cache: "no-store" });
    applyComponentSettings(settings);
    renderSettings(settings);
    settingsStatus.textContent = "";
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
  row.className = "component-row";
  const text = document.createElement("div");
  const title = document.createElement("div");
  title.className = "component-title";
  title.textContent = item.title;
  const desc = document.createElement("div");
  desc.className = "component-description";
  desc.textContent = item.description || item.id;
  text.append(title, desc);

  const button = document.createElement("button");
  button.type = "button";
  button.className = item.enabled ? "ghost component-enabled" : "ghost";
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
