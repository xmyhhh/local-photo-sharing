let loginBackgroundTimer = 0;
let loginBackgroundIndex = 0;

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
  if (openSettingsBtn) {
    openSettingsBtn.hidden = state.authEnabled && state.authRole !== "admin";
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
  loginBackdrop.onpointermove = null;
}

async function renderLoginBackgrounds() {
  loginBackdrop.innerHTML = "";
  loginBackdrop.className = "login-backdrop";
  const gallery = await fetchJson("/api/auth/background-gallery", { cache: "no-store" }).catch(() => ({ mode: "none", photos: [] }));
  const items = buildLoginMosaicItems(gallery.photos || []);
  if (!items.length) {
    return;
  }
  loginBackdrop.classList.add("mosaic");
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
