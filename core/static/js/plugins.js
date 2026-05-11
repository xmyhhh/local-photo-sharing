async function loadPluginAssets() {
  const assets = Array.isArray(state.pluginAssets) ? state.pluginAssets : [];
  for (const plugin of assets) {
    for (const href of plugin.styles || []) {
      await loadPluginStyle(href);
    }
    for (const src of plugin.scripts || []) {
      await loadPluginScript(src);
    }
  }
  document.dispatchEvent(new CustomEvent("photo-share:plugins-ready", {
    detail: {
      plugins: state.enabledPlugins,
      components: state.pluginComponents,
    },
  }));
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
