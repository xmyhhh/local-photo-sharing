const state = {
  folder: "",
  parent: "",
  entries: [],
  currentPhoto: null,
  zoom: 1,
};

const grid = document.querySelector("#grid");
const emptyState = document.querySelector("#emptyState");
const breadcrumb = document.querySelector("#breadcrumb");
const rootPath = document.querySelector("#rootPath");
const backBtn = document.querySelector("#backBtn");
const refreshBtn = document.querySelector("#refreshBtn");
const viewer = document.querySelector("#viewer");
const viewerTitle = document.querySelector("#viewerTitle");
const viewerImage = document.querySelector("#viewerImage");
const viewerRating = document.querySelector("#viewerRating");
const imageStage = document.querySelector("#imageStage");
const zoomOutBtn = document.querySelector("#zoomOutBtn");
const zoomResetBtn = document.querySelector("#zoomResetBtn");
const zoomInBtn = document.querySelector("#zoomInBtn");
const deleteBtn = document.querySelector("#deleteBtn");
const closeBtn = document.querySelector("#closeBtn");

async function loadConfig() {
  const config = await fetchJson("/api/config");
  rootPath.textContent = config.root;
}

async function loadFolder(folder = state.folder) {
  const data = await fetchJson(`/api/photos?folder=${encodeURIComponent(folder)}`);
  state.folder = data.folder;
  state.parent = data.parent;
  state.entries = data.entries;
  renderBreadcrumb();
  renderGrid();
}

function renderBreadcrumb() {
  breadcrumb.innerHTML = "";
  const root = document.createElement("button");
  root.type = "button";
  root.textContent = "根目录";
  root.addEventListener("click", () => loadFolder(""));
  breadcrumb.append(root);

  const parts = state.folder ? state.folder.split("/") : [];
  let current = "";
  parts.forEach((part) => {
    const sep = document.createElement("span");
    sep.textContent = "/";
    breadcrumb.append(sep);

    current = current ? `${current}/${part}` : part;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = part;
    btn.addEventListener("click", () => loadFolder(current));
    breadcrumb.append(btn);
  });

  backBtn.disabled = !state.folder;
}

function renderGrid() {
  grid.innerHTML = "";
  emptyState.hidden = state.entries.length > 0;

  state.entries.forEach((entry) => {
    const tile = document.createElement("article");
    tile.className = "tile";

    const button = document.createElement("button");
    button.className = "tile-button";
    button.type = "button";
    button.title = entry.name;

    if (entry.type === "folder") {
      const icon = document.createElement("div");
      icon.className = "folder-icon";
      icon.textContent = "DIR";
      button.append(icon);
      button.addEventListener("click", () => loadFolder(entry.path));
    } else {
      const img = document.createElement("img");
      img.className = "thumb";
      img.loading = "lazy";
      img.alt = entry.name;
      img.src = `/api/thumb/${encodePath(entry.path)}`;
      button.append(img);
      button.addEventListener("click", () => openViewer(entry));
    }

    const meta = document.createElement("div");
    meta.className = "meta";
    const name = document.createElement("div");
    name.className = "name";
    name.textContent = entry.name;
    meta.append(name);

    if (entry.type === "photo") {
      meta.append(createRating(entry, false));
    }

    tile.append(button, meta);
    grid.append(tile);
  });
}

function createRating(entry, large) {
  const wrap = document.createElement("div");
  wrap.className = "rating";
  for (let i = 1; i <= 5; i += 1) {
    const star = document.createElement("button");
    star.type = "button";
    star.className = `star ${i <= entry.rating ? "active" : ""}`;
    star.textContent = "★";
    star.title = `${i} 分`;
    if (large) {
      star.style.fontSize = "28px";
    }
    star.addEventListener("click", async (event) => {
      event.stopPropagation();
      const nextRating = entry.rating === i ? 0 : i;
      await setRating(entry, nextRating);
    });
    wrap.append(star);
  }
  return wrap;
}

function openViewer(entry) {
  state.currentPhoto = entry;
  state.zoom = 1;
  viewerTitle.textContent = entry.path;
  viewerImage.alt = entry.name;
  viewerImage.src = `/api/image/${encodePath(entry.path)}`;
  renderViewerRating();
  updateZoom();
  viewer.showModal();
}

function renderViewerRating() {
  viewerRating.innerHTML = "";
  if (state.currentPhoto) {
    viewerRating.append(createRating(state.currentPhoto, true));
  }
}

async function setRating(entry, rating) {
  const updated = await fetchJson(`/api/rating/${encodePath(entry.path)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rating }),
  });
  entry.rating = updated.rating;
  renderGrid();
  if (state.currentPhoto?.path === entry.path) {
    state.currentPhoto.rating = updated.rating;
    renderViewerRating();
  }
}

function updateZoom() {
  viewerImage.style.width = `${Math.round(state.zoom * 100)}%`;
  zoomResetBtn.textContent = `${Math.round(state.zoom * 100)}%`;
}

async function deleteCurrentPhoto() {
  if (!state.currentPhoto) {
    return;
  }
  const ok = window.confirm(`确认删除这张图片？\n${state.currentPhoto.path}`);
  if (!ok) {
    return;
  }
  await fetchJson(`/api/photo/${encodePath(state.currentPhoto.path)}`, { method: "DELETE" });
  viewer.close();
  state.currentPhoto = null;
  await loadFolder(state.folder);
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json();
}

function encodePath(path) {
  return path.split("/").map(encodeURIComponent).join("/");
}

backBtn.addEventListener("click", () => {
  if (state.folder) {
    loadFolder(state.parent);
  }
});
refreshBtn.addEventListener("click", () => loadFolder(state.folder));
closeBtn.addEventListener("click", () => viewer.close());
deleteBtn.addEventListener("click", deleteCurrentPhoto);
zoomInBtn.addEventListener("click", () => {
  state.zoom = Math.min(5, state.zoom + 0.25);
  updateZoom();
});
zoomOutBtn.addEventListener("click", () => {
  state.zoom = Math.max(0.25, state.zoom - 0.25);
  updateZoom();
});
zoomResetBtn.addEventListener("click", () => {
  state.zoom = 1;
  updateZoom();
});
imageStage.addEventListener("wheel", (event) => {
  if (!event.ctrlKey) {
    return;
  }
  event.preventDefault();
  state.zoom = event.deltaY < 0 ? Math.min(5, state.zoom + 0.1) : Math.max(0.25, state.zoom - 0.1);
  updateZoom();
});

loadConfig()
  .then(() => loadFolder(""))
  .catch((error) => {
    emptyState.hidden = false;
    emptyState.textContent = error.message;
  });
