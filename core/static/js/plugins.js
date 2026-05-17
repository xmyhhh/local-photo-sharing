const pluginActionHandlers = new Map();
const pluginSettingsPageHandlers = new Map();

function registerPluginAction(actionId, handler) {
  if (!actionId || typeof handler !== "function") {
    throw new Error("registerPluginAction requires an action id and a handler.");
  }
  pluginActionHandlers.set(actionId, handler);
}

function registerPluginSettingsPage(pageId, handler) {
  if (!pageId || typeof handler !== "function") {
    throw new Error("registerPluginSettingsPage requires a page id and renderer.");
  }
  pluginSettingsPageHandlers.set(pageId, handler);
}

async function loadPluginAssets() {
  const assets = enabledPluginAssets();
  for (const plugin of assets) {
    for (const href of plugin.styles || []) {
      await loadPluginStyle(href);
    }
    for (const src of plugin.scripts || []) {
      await loadPluginScript(src);
    }
  }
  renderPluginComponentTriggers();
  renderPluginSettingsTabs();
  document.dispatchEvent(new CustomEvent("photo-share:plugins-ready", {
    detail: {
      plugins: state.enabledPlugins,
      components: state.pluginComponents,
    },
  }));
}

function renderPluginComponentTriggers() {
  clearPluginManagedTriggers();
  enabledPluginComponents().forEach((component) => {
    (component.triggers || []).forEach((trigger) => {
      if (trigger.status === "planned") {
        return;
      }
      if (trigger.type === "topbar_button") {
        const button = createPluginTriggerButton(component, trigger);
        button.classList.add("ghost");
        topbarActions?.append(button);
      }
    });
  });
  renderSelectionPluginActions();
}

function enabledPluginAssets() {
  return (state.pluginAssets || []).filter((plugin) => state.enabledPlugins.has(plugin.name) || plugin.enabled === true);
}

function enabledPluginComponents() {
  return (state.pluginComponents || []).filter((component) => state.enabledPlugins.has(component.plugin) || component.enabled === true);
}

function clearPluginManagedTriggers() {
  document.querySelectorAll("[data-plugin-trigger='1']").forEach((item) => item.remove());
}

function createPluginTriggerButton(component, trigger) {
  const button = document.createElement("button");
  button.type = "button";
  button.classList.add("with-icon");
  const label = trigger.label || component.title || component.id;
  const icon = document.createElement("span");
  icon.className = "button-icon";
  icon.setAttribute("aria-hidden", "true");
  icon.innerHTML = trigger.iconSvg || topbarIconSvgForLabel(label);
  const text = document.createElement("span");
  text.textContent = label;
  button.append(icon, text);
  button.dataset.pluginTrigger = "1";
  button.dataset.componentId = component.id;
  button.dataset.triggerType = trigger.type;
  if (trigger.target) {
    button.dataset.triggerTarget = trigger.target;
  }
  button.addEventListener("click", () => dispatchPluginComponentAction(component, trigger));
  return button;
}

function collectPluginSettingsPages() {
  const pages = [];
  enabledPluginComponents().forEach((component) => {
    (component.surfaces || []).forEach((surface) => {
      if (surface.type !== "settings_page" || surface.status === "planned") {
        return;
      }
      const id = surface.id || component.id;
      pages.push({
        id,
        tabId: `plugin:${id}`,
        plugin: component.plugin,
        title: surface.title || component.title || component.pluginTitle || id,
        label: surface.label || surface.title || component.title || id,
        kicker: surface.kicker || component.pluginTitle || "插件",
        description: surface.description || component.description || "",
        render: pluginSettingsPageHandlers.get(id),
      });
    });
  });
  return pages;
}

function getPluginSettingsPage(tabName) {
  return collectPluginSettingsPages().find((page) => page.tabId === tabName || page.id === tabName) || null;
}

function renderPluginSettingsTabs() {
  if (!pluginSettingsTabs || !pluginSettingsPages) {
    return;
  }
  const previous = new Map(
    Array.from(pluginSettingsPages.querySelectorAll(".settings-page")).map((page) => [page.dataset.settingsPage, page]),
  );
  pluginSettingsTabs.innerHTML = "";
  const activeTab = document.querySelector(".settings-tab.active")?.dataset.settingsTab || "general";
  const nextTabs = new Set();
  collectPluginSettingsPages().forEach((page) => {
    nextTabs.add(page.tabId);
    const button = document.createElement("button");
    button.className = "settings-tab plugin-settings-tab";
    button.type = "button";
    button.dataset.settingsTab = page.tabId;
    button.dataset.pluginSettingsTab = "1";
    button.textContent = page.label;
    button.addEventListener("click", () => setSettingsTab(page.tabId));
    pluginSettingsTabs.append(button);

    let panel = previous.get(page.tabId);
    if (!panel) {
      panel = document.createElement("div");
      panel.className = "settings-page";
      panel.dataset.settingsPage = page.tabId;
      pluginSettingsPages.append(panel);
    }
    panel.hidden = activeTab !== page.tabId;
  });
  previous.forEach((panel, tabId) => {
    if (!nextTabs.has(tabId)) {
      panel.remove();
    }
  });
  const activePage = getPluginSettingsPage(activeTab);
  if (activePage) {
    setSettingsTab(activeTab);
  }
}

function topbarIconSvgForLabel(label) {
  if (label.includes("搜索")) {
    return `
      <svg viewBox="0 0 24 24">
        <circle cx="11" cy="11" r="6"></circle>
        <path d="m16 16 4 4"></path>
      </svg>
    `;
  }
  if (label.includes("包围") || label.includes("曝光")) {
    return `
      <svg viewBox="0 0 24 24">
        <path d="M12 3 21 12 12 21 3 12 12 3Z"></path>
        <path d="M12 8 16 12 12 16 8 12 12 8Z"></path>
      </svg>
    `;
  }
  return `
    <svg viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="4"></circle>
    </svg>
  `;
}

function dispatchPluginComponentAction(component, trigger) {
  const actionId = trigger.action || component.action || component.id;
  const handler = pluginActionHandlers.get(actionId);
  if (!handler) {
    window.alert(`组件动作尚未注册：${actionId}`);
    return;
  }
  handler({
    component,
    trigger,
    contextFolder: state.contextFolder,
    contextEntry: state.contextEntry,
    selectedPaths: Array.from(state.selectedPaths || []),
  });
}

function pluginContextMenuGroups(target) {
  const groups = new Map();
  enabledPluginComponents().forEach((component) => {
    (component.triggers || []).forEach((trigger) => {
      if (trigger.status === "planned" || trigger.type !== "context_menu" || trigger.target !== target) {
        return;
      }
      const pluginName = component.plugin || component.id || "plugin";
      if (!groups.has(pluginName)) {
        groups.set(pluginName, {
          title: component.pluginTitle || component.pluginName || pluginName,
          items: [],
        });
      }
      groups.get(pluginName).items.push({ component, trigger });
    });
  });
  return Array.from(groups.values()).filter((group) => group.items.length);
}

function renderSelectionPluginActions() {
  if (!selectionPluginActions) {
    return;
  }
  selectionPluginActions.innerHTML = "";
  pluginContextMenuGroups("file_selection").forEach((group) => {
    group.items.forEach(({ component, trigger }) => {
      const button = createSelectionPluginButton(component, trigger);
      selectionPluginActions.append(button);
    });
  });
  updateSelectionPluginActions();
}

function createSelectionPluginButton(component, trigger) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "ghost";
  button.dataset.pluginSelectionAction = "1";
  button.textContent = trigger.label || component.title || component.id;
  button.addEventListener("click", () => dispatchPluginComponentAction(component, trigger));
  return button;
}

function updateSelectionPluginActions() {
  if (!selectionPluginActions) {
    return;
  }
  const entries = typeof selectedEntries === "function" ? selectedEntries() : [];
  const allPhotos = entries.length > 0 && entries.length === state.selectedPaths.size && entries.every((entry) => entry.type === "photo");
  selectionPluginActions.hidden = !allPhotos || !selectionPluginActions.children.length;
  selectionPluginActions.querySelectorAll("button").forEach((button) => {
    button.disabled = !allPhotos;
  });
}

function loadPluginStyle(href) {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`link[data-plugin-asset="${CSS.escape(href)}"]`)) {
      resolve();
      return;
    }
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    link.dataset.pluginAsset = href;
    link.onload = () => resolve();
    link.onerror = () => reject(new Error(`Failed to load plugin style: ${href}`));
    document.head.append(link);
  });
}

function loadPluginScript(src) {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[data-plugin-asset="${CSS.escape(src)}"]`)) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.dataset.pluginAsset = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Failed to load plugin script: ${src}`));
    document.body.append(script);
  });
}
