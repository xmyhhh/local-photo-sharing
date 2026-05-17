(function () {
  const STORAGE_KEY = "photoShare.collage.pendingPaths";

  registerPluginAction("collage.open", () => {
    window.location.href = "/collage";
  });

  registerPluginAction("collage.add_file", ({ contextEntry }) => {
    const path = contextEntry?.path || state.contextEntry?.path || "";
    addToCollagePool(path ? [path] : []);
  });

  registerPluginAction("collage.add_selection", () => {
    addToCollagePool(Array.from(state.selectedPaths || []));
  });

  async function addToCollagePool(paths) {
    const photos = paths.filter((path) => {
      const entry = state.entryByPath?.get(path);
      return !entry || entry.type === "photo";
    });
    if (!photos.length) {
      window.location.href = "/collage";
      return;
    }
    try {
      await fetchJson("/api/collage/pool", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paths: photos }),
      });
    } catch {
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(photos));
    }
    window.location.href = "/collage";
  }
})();
