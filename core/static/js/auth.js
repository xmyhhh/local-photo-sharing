let loginBackgroundTimer = 0;
let loginBackgroundIndex = 0;
let loginBackgroundSparkTimer = 0;
let loginBackgroundPointerTimer = 0;

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
  if (loginBackgroundSparkTimer) {
    window.clearInterval(loginBackgroundSparkTimer);
    loginBackgroundSparkTimer = 0;
  }
  if (loginBackgroundPointerTimer) {
    window.clearTimeout(loginBackgroundPointerTimer);
    loginBackgroundPointerTimer = 0;
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
    tile.className = "login-bg-tile";
    tile.style.setProperty("--x", `${item.x}%`);
    tile.style.setProperty("--y", `${item.y}%`);
    tile.style.setProperty("--w", `${item.w}%`);
    tile.style.setProperty("--h", `${item.h}%`);
    tile.style.setProperty("--r", `${item.rotate}deg`);
    tile.style.setProperty("--delay", `${item.delay}ms`);
    tile.dataset.url = item.url;
    setLoginTileImage(tile, item.url);
    tile.classList.toggle("awake", index % 11 === 0);
    loginBackdrop.append(tile);
  });
  loginBackdrop.onpointermove = awakenLoginTilesNearPointer;
  loginBackgroundSparkTimer = window.setInterval(() => {
    const nodes = Array.from(loginBackdrop.querySelectorAll(".login-bg-tile"));
    if (!nodes.length) {
      return;
    }
    const node = nodes[Math.floor(Math.random() * nodes.length)];
    node.classList.add("awake");
    window.setTimeout(() => node.classList.remove("awake"), 2600 + Math.random() * 1800);
  }, 700);
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
  const cols = 9;
  const rows = 6;
  const count = cols * rows;
  return Array.from({ length: count }, (_, index) => {
    const col = index % cols;
    const row = Math.floor(index / cols);
    const jitterX = (pseudoRandom(index, 7) - 0.5) * 7.5;
    const jitterY = (pseudoRandom(index, 13) - 0.5) * 8.5;
    const rowShift = row % 2 ? 5 : 0;
    return {
      url: urls[index % urls.length],
      x: -7 + col * 13.9 + rowShift + jitterX,
      y: -10 + row * 23.2 + jitterY,
      w: 15 + pseudoRandom(index, 19) * 8,
      h: 20 + pseudoRandom(index, 23) * 12,
      rotate: -4.5 + pseudoRandom(index, 29) * 9,
      delay: Math.floor(pseudoRandom(index, 31) * 4200),
    };
  });
}

function awakenLoginTilesNearPointer(event) {
  if (loginBackgroundPointerTimer) {
    return;
  }
  loginBackgroundPointerTimer = window.setTimeout(() => {
    loginBackgroundPointerTimer = 0;
  }, 90);
  const nodes = Array.from(loginBackdrop.querySelectorAll(".login-bg-tile.ready"));
  if (!nodes.length) {
    return;
  }
  const ranked = nodes
    .map((node) => {
      const rect = node.getBoundingClientRect();
      const x = rect.left + rect.width / 2;
      const y = rect.top + rect.height / 2;
      return { node, distance: Math.hypot(event.clientX - x, event.clientY - y) };
    })
    .sort((a, b) => a.distance - b.distance)
    .slice(0, 4);
  ranked.forEach(({ node }, index) => {
    node.classList.add("awake");
    window.setTimeout(() => node.classList.remove("awake"), 900 + index * 180);
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
