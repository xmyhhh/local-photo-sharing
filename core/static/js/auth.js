let loginBackgroundTimer = 0;
let loginBackgroundIndex = 0;
let loginBackgroundSparkTimer = 0;

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
    if (attempt < 8) {
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
  const count = Math.max(18, Math.min(46, urls.length < 8 ? urls.length * 7 : urls.length));
  return Array.from({ length: count }, (_, index) => {
    const col = index % 9;
    const row = Math.floor(index / 9);
    const jitterX = pseudoRandom(index, 7) * 5.8;
    const jitterY = pseudoRandom(index, 13) * 6.6;
    return {
      url: urls[index % urls.length],
      x: -6 + col * 13.8 + jitterX,
      y: -8 + row * 22 + jitterY,
      w: 13 + pseudoRandom(index, 19) * 9,
      h: 18 + pseudoRandom(index, 23) * 13,
      rotate: -5 + pseudoRandom(index, 29) * 10,
      delay: Math.floor(pseudoRandom(index, 31) * 4200),
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
