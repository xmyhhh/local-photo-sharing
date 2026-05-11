function applyThemeMode(mode = state.themeMode) {
  const safeMode = ["system", "light", "dark"].includes(mode) ? mode : "system";
  state.themeMode = safeMode;
  window.localStorage.setItem("themeMode", safeMode);
  document.documentElement.dataset.theme = safeMode;
  const dark = safeMode === "dark" || (safeMode === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", dark ? "#0e161a" : "#176b87");
}

function initializeThemeMode() {
  applyThemeMode(state.themeMode);
  const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");
  const handleSystemThemeChange = () => {
    if (state.themeMode === "system") {
      applyThemeMode("system");
    }
  };
  if (systemTheme.addEventListener) {
    systemTheme.addEventListener("change", handleSystemThemeChange);
  } else if (systemTheme.addListener) {
    systemTheme.addListener(handleSystemThemeChange);
  }
}

initializeThemeMode();
