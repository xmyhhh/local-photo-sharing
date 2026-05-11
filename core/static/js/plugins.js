const pluginActionHandlers = new Map();

function registerPluginAction(actionId, handler) {
  if (!actionId || typeof handler !== "function") {
    throw new Error("registerPluginAction requires an action id and a handler.");
  }
  pluginActionHandlers.set(actionId, handler);
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
      if (trigger.type === "context_menu" && trigger.target === "folder") {
        folderContextMenu?.append(createPluginTriggerButton(component, trigger));
      } else if (trigger.type === "topbar_button") {
        const button = createPluginTriggerButton(component, trigger);
        button.classList.add("ghost");
        topbarActions?.append(button);
      }
    });
  });
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
  button.textContent = trigger.label || component.title || component.id;
  button.dataset.pluginTrigger = "1";
  button.dataset.componentId = component.id;
  button.dataset.triggerType = trigger.type;
  if (trigger.target) {
    button.dataset.triggerTarget = trigger.target;
  }
  button.addEventListener("click", () => dispatchPluginComponentAction(component, trigger));
  return button;
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
