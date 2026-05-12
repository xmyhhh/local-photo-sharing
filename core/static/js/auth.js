let loginBackgroundTimer = 0;
let loginBackgroundIndex = 0;
let loginBackgroundPointerResetTimer = 0;

async function initializeAuth() {
  const status = await fetchJson("/api/auth/status", { cache: "no-store" });
  applyAuthStatus(status);
  if (status.enabled && status.role === "none") {
    showLoginScreen(status);
    throw new Error("AUTH_REQUIRED");
  }
  hideLoginScreen();
}

function applyAuthStatus(status) {
  state.authEnabled = Boolean(status.enabled);
  state.authRole = status.role || "none";
  state.authHasPassword = Boolean(status.hasPassword);
  state.publicAlbums = status.publicAlbums || [];
  state.publicAlbumSet = new Set(state.publicAlbums.map(normalizeRootedSettingsPath).filter(Boolean));
  state.loginBackgrounds = status.loginBackgrounds || [];
  state.loginBackgroundUrls = status.loginBackgroundUrls || status.loginBackgrounds || [];
  state.loginBackgroundMode = status.loginBackgroundMode || "none";
  state.loginBackgroundFolder = status.loginBackgroundFolder || "";
  state.loginBackgroundLayout = ["grid", "stack", "solo"].includes(status.loginBackgroundLayout) ? status.loginBackgroundLayout : "grid";
  if (openSettingsBtn) {
    openSettingsBtn.hidden = state.authEnabled && state.authRole === "none";
  }
  if (openUploadBtn) {
    openUploadBtn.hidden = state.authEnabled && state.authRole !== "admin";
  }
}

function showLoginScreen(status = {}) {
  applyAuthStatus(status);
  loginScreen.hidden = false;
  document.body.classList.add("login-active");
  renderLoginBackgrounds();
  window.setTimeout(() => loginPasswordInput?.focus(), 80);
}

function hideLoginScreen() {
  loginScreen.hidden = true;
  document.body.classList.remove("login-active");
  if (loginBackgroundTimer) {
    window.clearInterval(loginBackgroundTimer);
    loginBackgroundTimer = 0;
  }
  if (loginBackgroundPointerResetTimer) {
    window.clearTimeout(loginBackgroundPointerResetTimer);
    loginBackgroundPointerResetTimer = 0;
  }
  loginBackdrop.onpointermove = null;
  loginBackdrop.onpointerleave = null;
}

async function renderLoginBackgrounds() {
  loginBackdrop.innerHTML = "";
  loginBackdrop.className = "login-backdrop";
  const gallery = await fetchJson("/api/auth/background-gallery", { cache: "no-store" }).catch(() => ({ mode: "none", photos: [] }));
  if (state.loginBackgroundLayout === "solo") {
    renderLoginSoloBackground(gallery.photos || []);
    return;
  }
  const items = buildLoginMosaicItems(gallery.photos || []);
  if (!items.length) {
    return;
  }
  const layout = state.loginBackgroundLayout === "stack" ? "stack" : "grid";
  loginBackdrop.classList.add("mosaic", `mosaic-${layout}`);
  items.forEach((item, index) => {
    const tile = document.createElement("div");
    tile.className = `login-bg-tile depth-${item.depth}`;
    tile.style.setProperty("--x", `${item.x}%`);
    tile.style.setProperty("--y", `${item.y}%`);
    tile.style.setProperty("--w", `${item.w}%`);
    tile.style.setProperty("--h", `${item.h}%`);
    tile.style.setProperty("--r", `${item.rotate}deg`);
    tile.style.setProperty("--delay", `${item.delay}ms`);
    tile.style.setProperty("--float-x", `${item.floatX}px`);
    tile.style.setProperty("--float-y", `${item.floatY}px`);
    tile.dataset.url = item.url;
    setLoginTileImage(tile, item.url);
    loginBackdrop.append(tile);
  });
}

function renderLoginSoloBackground(photos) {
  const urls = photos.map((item) => item.thumbUrl).filter(Boolean);
  if (!urls.length) {
    return;
  }
  loginBackdrop.classList.add("solo-carousel");
  loginBackdrop.style.setProperty("--spot-x", "50%");
  loginBackdrop.style.setProperty("--spot-y", "50%");
  const layers = [0, 1].map((index) => {
    const layer = document.createElement("div");
    layer.className = `login-solo-layer ${index === 0 ? "active" : ""}`;
    loginBackdrop.append(layer);
    return layer;
  });
  loginBackgroundIndex = 0;
  setLoginSoloLayerImage(layers[0], urls[0]);
  if (urls.length > 1) {
    setLoginSoloLayerImage(layers[1], urls[1]);
    loginBackgroundTimer = window.setInterval(() => {
      loginBackgroundIndex = (loginBackgroundIndex + 1) % urls.length;
      const activeIndex = loginBackgroundIndex % 2;
      const nextIndex = (activeIndex + 1) % 2;
      setLoginSoloLayerImage(layers[activeIndex], urls[loginBackgroundIndex]);
      layers[activeIndex].classList.add("active");
      layers[nextIndex].classList.remove("active");
      setLoginSoloLayerImage(layers[nextIndex], urls[(loginBackgroundIndex + 1) % urls.length]);
    }, 6200);
  }
  loginBackdrop.onpointermove = (event) => {
    const rect = loginBackdrop.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / Math.max(1, rect.width)) * 100;
    const y = ((event.clientY - rect.top) / Math.max(1, rect.height)) * 100;
    loginBackdrop.style.setProperty("--spot-x", `${x}%`);
    loginBackdrop.style.setProperty("--spot-y", `${y}%`);
    loginBackdrop.classList.add("pointer-active");
    if (loginBackgroundPointerResetTimer) {
      window.clearTimeout(loginBackgroundPointerResetTimer);
    }
    loginBackgroundPointerResetTimer = window.setTimeout(() => {
      loginBackdrop.classList.remove("pointer-active");
      loginBackgroundPointerResetTimer = 0;
    }, 1100);
  };
  loginBackdrop.onpointerleave = () => {
    loginBackdrop.classList.remove("pointer-active");
  };
}

function setLoginSoloLayerImage(layer, url) {
  layer.style.backgroundImage = `url("${url.replace(/"/g, "%22")}")`;
}

function setLoginTileImage(tile, url, attempt = 0) {
  const image = new Image();
  image.onload = () => {
    tile.style.backgroundImage = `url("${url.replace(/"/g, "%22")}")`;
    tile.classList.add("ready");
  };
  image.onerror = () => {
    if (attempt < 2) {
      window.setTimeout(() => setLoginTileImage(tile, url, attempt + 1), 700 + attempt * 300);
    }
  };
  image.src = `${url}${url.includes("?") ? "&" : "?"}bg=${attempt}`;
}

function buildLoginMosaicItems(photos) {
  const urls = photos.map((item) => item.thumbUrl).filter(Boolean);
  if (!urls.length) {
    return [];
  }
  return state.loginBackgroundLayout === "stack" ? buildLoginStackItems(urls) : buildLoginGridItems(urls);
}

function buildLoginGridItems(urls) {
  const count = Math.min(30, Math.max(14, urls.length));
  const columns = 6;
  const rows = Math.ceil(count / columns);
  return Array.from({ length: count }, (_, index) => {
    const col = index % columns;
    const row = Math.floor(index / columns);
    const rowOffset = row % 2 ? 2 : -2;
    return {
      url: urls[index % urls.length],
      depth: "grid",
      x: -3 + col * 18.5 + rowOffset + (pseudoRandom(index, 11) - 0.5) * 1.8,
      y: -6 + row * (104 / Math.max(rows, 1)) + (pseudoRandom(index, 17) - 0.5) * 2.4,
      w: 15.4 + pseudoRandom(index, 19) * 1.2,
      h: 19.2 + pseudoRandom(index, 23) * 1.6,
      rotate: 0,
      delay: Math.floor(pseudoRandom(index, 31) * 3800),
      floatX: Math.round((pseudoRandom(index, 37) - 0.5) * 8),
      floatY: Math.round((pseudoRandom(index, 41) - 0.5) * 8),
    };
  });
}

function buildLoginStackItems(urls) {
  const count = Math.min(14, Math.max(7, urls.length));
  return Array.from({ length: count }, (_, index) => {
    const depth = index % 5 === 0 ? "far" : index % 3 === 0 ? "near" : "mid";
    const lane = index / Math.max(1, count - 1);
    const x = -8 + lane * 108 + (pseudoRandom(index, 7) - 0.5) * 16;
    const y = 4 + pseudoRandom(index, 13) * 78;
    const size = depth === "near" ? 28 : depth === "far" ? 20 : 24;
    return {
      url: urls[index % urls.length],
      depth,
      x,
      y,
      w: size + pseudoRandom(index, 19) * 7,
      h: size * 1.22 + pseudoRandom(index, 23) * 9,
      rotate: -2.2 + pseudoRandom(index, 29) * 4.4,
      delay: Math.floor(pseudoRandom(index, 31) * 5200),
      floatX: Math.round((pseudoRandom(index, 37) - 0.5) * 26),
      floatY: Math.round((pseudoRandom(index, 41) - 0.5) * 20),
    };
  });
}

function pseudoRandom(index, salt) {
  const value = Math.sin(index * 91.73 + salt * 37.19) * 10000;
  return value - Math.floor(value);
}

async function submitLogin(password) {
  loginStatus.textContent = "正在登录...";
  const status = await fetchJson("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  applyAuthStatus(status);
  hideLoginScreen();
  await startGallery();
}

async function submitGuestLogin() {
  loginStatus.textContent = "正在进入游客模式...";
  const status = await fetchJson("/api/auth/guest", { method: "POST" });
  applyAuthStatus(status);
  hideLoginScreen();
  await startGallery();
}

loginForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await submitLogin(loginPasswordInput.value || "");
  } catch (error) {
    loginStatus.textContent = error.message;
  }
});

guestLoginBtn?.addEventListener("click", async () => {
  try {
    await submitGuestLogin();
  } catch (error) {
    loginStatus.textContent = error.message;
  }
});
