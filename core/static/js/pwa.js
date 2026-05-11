function registerServiceWorker() {
  if (!("serviceWorker" in navigator) || !window.isSecureContext) {
    return;
  }
  navigator.serviceWorker.register("/static/sw.js", { scope: "/" }).catch(() => {});
}

function handleSharedLaunch() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("shared") !== "1") {
    return;
  }
  const folder = normalizeFolderPath(params.get("folder") || "");
  window.history.replaceState({ gallery: true, folder }, "", window.location.pathname);
  window.setTimeout(() => {
    if (folder) {
      navigateFolder(folder);
    } else {
      loadFolder("");
    }
  }, 0);
}

registerServiceWorker();
