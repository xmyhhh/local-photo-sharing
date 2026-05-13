(function () {
  let panelReady = false;
  let statusTimer = 0;

  registerPluginSettingsPage("cloud_backup.settings", renderCloudBackupSettingsPage);
  document.addEventListener("photo-share:backend-task-started", () => pollCloudBackupStatus({ quiet: true }));

  function markup() {
    return `
      <section class="settings-card cloud-backup-card">
        <div class="cloud-backup-head">
          <label class="switch-row cloud-backup-switch">
            <span>启用冷备份</span>
            <input id="cloudBackupEnabled" type="checkbox" />
          </label>
          <div id="cloudBackupSummary" class="cloud-backup-summary">正在读取状态...</div>
        </div>
        <div class="cloud-backup-grid">
          <label class="cloud-backup-field">
            <span>备份目标</span>
            <select id="cloudBackupProvider"></select>
          </label>
          <label class="cloud-backup-field">
            <span>间隔小时</span>
            <input id="cloudBackupInterval" type="number" min="1" max="720" step="1" />
          </label>
          <label class="cloud-backup-field">
            <span>单次最多文件</span>
            <input id="cloudBackupMaxFiles" type="number" min="0" max="1000000" step="1" />
          </label>
        </div>
        <label class="cloud-backup-field">
          <span>本地备份目录</span>
          <input id="cloudBackupTargetDir" type="text" autocomplete="off" placeholder="例如 F:\\photo-cold-backup" />
        </label>
        <div id="cloudBackupAliyunFields" class="cloud-backup-provider-fields" hidden>
          <div class="cloud-backup-grid">
            <label class="cloud-backup-field">
              <span>Client ID</span>
              <input id="cloudBackupAliyunClientId" type="text" autocomplete="off" />
            </label>
            <label class="cloud-backup-field">
              <span>Client Secret</span>
              <input id="cloudBackupAliyunClientSecret" type="password" autocomplete="new-password" />
            </label>
            <label class="cloud-backup-field">
              <span>Refresh Token</span>
              <input id="cloudBackupAliyunRefreshToken" type="password" autocomplete="new-password" />
            </label>
          </div>
          <div class="cloud-backup-grid">
            <label class="cloud-backup-field">
              <span>Drive ID</span>
              <input id="cloudBackupAliyunDriveId" type="text" autocomplete="off" placeholder="留空自动读取" />
            </label>
            <label class="cloud-backup-field">
              <span>Drive 类型</span>
              <select id="cloudBackupAliyunDriveType">
                <option value="default">默认盘</option>
                <option value="resource">资源库</option>
                <option value="backup">备份盘</option>
              </select>
            </label>
            <label class="cloud-backup-field">
              <span>根目录 File ID</span>
              <input id="cloudBackupAliyunRootFileId" type="text" autocomplete="off" placeholder="root" />
            </label>
          </div>
        </div>
        <div id="cloudBackupPan123Fields" class="cloud-backup-provider-fields" hidden>
          <div class="cloud-backup-grid">
            <label class="cloud-backup-field">
              <span>Client ID</span>
              <input id="cloudBackupPan123ClientId" type="text" autocomplete="off" />
            </label>
            <label class="cloud-backup-field">
              <span>Client Secret</span>
              <input id="cloudBackupPan123ClientSecret" type="password" autocomplete="new-password" />
            </label>
            <label class="cloud-backup-field">
              <span>根目录 File ID</span>
              <input id="cloudBackupPan123RootFileId" type="number" min="0" step="1" placeholder="0" />
            </label>
          </div>
        </div>
        <label class="cloud-backup-field">
          <span>远端目录前缀</span>
          <input id="cloudBackupRemotePrefix" type="text" autocomplete="off" placeholder="photo-share-backup" />
        </label>
        <div class="cloud-backup-actions">
          <button id="cloudBackupSave" type="button">保存设置</button>
          <button id="cloudBackupRun" class="ghost" type="button">立即备份</button>
          <button id="cloudBackupRefresh" class="ghost" type="button">刷新状态</button>
        </div>
        <div id="cloudBackupStatus" class="cloud-backup-status"></div>
      </section>
      <section class="settings-card cloud-backup-card">
        <div class="settings-card-head">
          <h3>最近记录</h3>
        </div>
        <div id="cloudBackupHistory" class="cloud-backup-history"></div>
      </section>
    `;
  }

  async function renderCloudBackupSettingsPage() {
    const panel = document.querySelector('[data-settings-page="plugin:cloud_backup.settings"]');
    if (!panel) {
      return;
    }
    if (!panelReady) {
      panel.innerHTML = markup();
      panelReady = true;
      panel.querySelector("#cloudBackupSave").addEventListener("click", saveCloudBackupSettings);
      panel.querySelector("#cloudBackupRun").addEventListener("click", runCloudBackupNow);
      panel.querySelector("#cloudBackupRefresh").addEventListener("click", () => pollCloudBackupStatus({ quiet: false }));
      panel.querySelector("#cloudBackupProvider").addEventListener("change", updateProviderHint);
    }
    await loadCloudBackupSettings();
  }

  async function loadCloudBackupSettings() {
    const status = getStatusElement();
    if (status) {
      status.textContent = "正在读取冷备份设置...";
    }
    try {
      const payload = await fetchJson("/api/cloud-backup/settings", { cache: "no-store" });
      renderPayload(payload);
      if (status) {
        status.textContent = "";
      }
    } catch (error) {
      if (status) {
        status.textContent = error.message || "冷备份设置读取失败。";
      }
    }
  }

  async function saveCloudBackupSettings() {
    const status = getStatusElement();
    const payload = readSettingsFromPanel();
    if (payload.enabled && payload.provider === "local_folder" && !payload.targetDir) {
      status.textContent = "请先填写本地备份目录。";
      return false;
    }
    const validationMessage = validateCloudProviderPayload(payload, { requireProvider: payload.enabled });
    if (validationMessage) {
      status.textContent = validationMessage;
      return false;
    }
    status.textContent = "正在保存冷备份设置...";
    try {
      const data = await fetchJson("/api/cloud-backup/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      renderPayload(data);
      status.textContent = "冷备份设置已保存。";
      if (payload.enabled && typeof notifyBackendTaskStarted === "function") {
        notifyBackendTaskStarted();
      }
      return true;
    } catch (error) {
      status.textContent = error.message || "保存失败。";
      return false;
    }
  }

  async function runCloudBackupNow() {
    const payload = readSettingsFromPanel();
    const status = getStatusElement();
    if (payload.provider === "local_folder" && !payload.targetDir) {
      status.textContent = "请先填写本地备份目录。";
      return;
    }
    const validationMessage = validateCloudProviderPayload(payload, { requireProvider: true });
    if (validationMessage) {
      status.textContent = validationMessage;
      return;
    }
    const saved = await saveCloudBackupSettings();
    if (!saved) {
      return;
    }
    status.textContent = "正在启动冷备份...";
    try {
      const data = await fetchJson("/api/cloud-backup/run", { method: "POST" });
      renderStatus(data);
      status.textContent = "冷备份已加入后台任务。";
      if (typeof notifyBackendTaskStarted === "function") {
        notifyBackendTaskStarted();
      }
      scheduleStatusPoll();
    } catch (error) {
      status.textContent = error.message || "启动失败。";
    }
  }

  async function pollCloudBackupStatus({ quiet }) {
    window.clearTimeout(statusTimer);
    try {
      const status = await fetchJson("/api/cloud-backup/status", { cache: "no-store" });
      renderStatus(status);
      if (status.running) {
        scheduleStatusPoll();
      }
    } catch (error) {
      if (!quiet && getStatusElement()) {
        getStatusElement().textContent = error.message || "状态刷新失败。";
      }
    }
  }

  function scheduleStatusPoll() {
    window.clearTimeout(statusTimer);
    statusTimer = window.setTimeout(() => pollCloudBackupStatus({ quiet: true }), 1500);
  }

  function renderPayload(payload) {
    renderProviderOptions(payload.providers || []);
    renderSettings(payload.settings || {});
    renderStatus(payload.status || {});
    updateProviderHint();
    if (payload.status?.running) {
      scheduleStatusPoll();
    }
  }

  function renderProviderOptions(providers) {
    const select = document.querySelector("#cloudBackupProvider");
    if (!select) {
      return;
    }
    const current = select.value || "local_folder";
    select.innerHTML = "";
    providers.forEach((provider) => {
      const option = document.createElement("option");
      option.value = provider.key;
      option.disabled = !provider.available;
      option.textContent = provider.available ? provider.title : `${provider.title}（后续接入）`;
      select.append(option);
    });
    select.value = Array.from(select.options).some((option) => option.value === current && !option.disabled)
      ? current
      : "local_folder";
  }

  function renderSettings(settings) {
    setValue("#cloudBackupEnabled", Boolean(settings.enabled), "checked");
    setValue("#cloudBackupProvider", settings.provider || "local_folder");
    setValue("#cloudBackupTargetDir", settings.targetDir || "");
    setValue("#cloudBackupRemotePrefix", settings.remotePrefix || "photo-share-backup");
    setValue("#cloudBackupInterval", String(settings.intervalHours || 24));
    setValue("#cloudBackupMaxFiles", String(settings.maxFilesPerRun || 0));
    setValue("#cloudBackupAliyunClientId", settings.aliyunClientId || "");
    setValue("#cloudBackupAliyunClientSecret", "");
    setValue("#cloudBackupAliyunRefreshToken", "");
    setValue("#cloudBackupAliyunDriveId", settings.aliyunDriveId || "");
    setValue("#cloudBackupAliyunDriveType", settings.aliyunDriveType || "default");
    setValue("#cloudBackupAliyunRootFileId", settings.aliyunRootFileId || "root");
    setValue("#cloudBackupPan123ClientId", settings.pan123ClientId || "");
    setValue("#cloudBackupPan123ClientSecret", "");
    setValue("#cloudBackupPan123RootFileId", String(settings.pan123RootFileId || 0));
    setSecretPlaceholder("#cloudBackupAliyunClientSecret", settings.hasAliyunClientSecret);
    setSecretPlaceholder("#cloudBackupAliyunRefreshToken", settings.hasAliyunRefreshToken);
    setSecretPlaceholder("#cloudBackupPan123ClientSecret", settings.hasPan123ClientSecret);
  }

  function renderStatus(status) {
    const summary = document.querySelector("#cloudBackupSummary");
    if (summary) {
      summary.textContent = status.running
        ? formatRunSummary(status.currentRun)
        : formatIdleSummary(status);
    }
    const history = document.querySelector("#cloudBackupHistory");
    if (history) {
      renderHistory(history, status.history || []);
    }
    if (status.running) {
      scheduleStatusPoll();
    }
  }

  function renderHistory(container, runs) {
    container.innerHTML = "";
    if (!runs.length) {
      const empty = document.createElement("div");
      empty.className = "cloud-backup-empty";
      empty.textContent = "还没有备份记录。";
      container.append(empty);
      return;
    }
    runs.slice(0, 8).forEach((run) => {
      const row = document.createElement("div");
      row.className = `cloud-backup-history-row state-${escapeToken(run.state || "ready")}`;
      row.innerHTML = `
        <div>
          <strong>${escapeHtml(runStateLabel(run.state))}</strong>
          <span>${escapeHtml(formatTimestamp(run.finishedAt || run.startedAt))}</span>
        </div>
        <div>${escapeHtml(formatRunCounts(run))}</div>
      `;
      container.append(row);
    });
  }

  function readSettingsFromPanel() {
    return {
      enabled: document.querySelector("#cloudBackupEnabled")?.checked || false,
      provider: document.querySelector("#cloudBackupProvider")?.value || "local_folder",
      targetDir: document.querySelector("#cloudBackupTargetDir")?.value.trim() || "",
      remotePrefix: document.querySelector("#cloudBackupRemotePrefix")?.value.trim() || "photo-share-backup",
      intervalHours: clampInt(document.querySelector("#cloudBackupInterval")?.value, 1, 720, 24),
      maxFilesPerRun: clampInt(document.querySelector("#cloudBackupMaxFiles")?.value, 0, 1000000, 0),
      aliyunClientId: document.querySelector("#cloudBackupAliyunClientId")?.value.trim() || "",
      aliyunClientSecret: document.querySelector("#cloudBackupAliyunClientSecret")?.value.trim() || "",
      aliyunRefreshToken: document.querySelector("#cloudBackupAliyunRefreshToken")?.value.trim() || "",
      aliyunDriveId: document.querySelector("#cloudBackupAliyunDriveId")?.value.trim() || "",
      aliyunDriveType: document.querySelector("#cloudBackupAliyunDriveType")?.value || "default",
      aliyunRootFileId: document.querySelector("#cloudBackupAliyunRootFileId")?.value.trim() || "root",
      pan123ClientId: document.querySelector("#cloudBackupPan123ClientId")?.value.trim() || "",
      pan123ClientSecret: document.querySelector("#cloudBackupPan123ClientSecret")?.value.trim() || "",
      pan123RootFileId: clampInt(document.querySelector("#cloudBackupPan123RootFileId")?.value, 0, 9000000000000, 0),
    };
  }

  function updateProviderHint() {
    const provider = document.querySelector("#cloudBackupProvider")?.value || "local_folder";
    const target = document.querySelector("#cloudBackupTargetDir");
    if (target) {
      target.disabled = provider !== "local_folder";
    }
    setHidden("#cloudBackupAliyunFields", provider !== "aliyundrive");
    setHidden("#cloudBackupPan123Fields", provider !== "pan123");
  }

  function validateCloudProviderPayload(payload, { requireProvider }) {
    if (!requireProvider) {
      return "";
    }
    if (payload.provider === "aliyundrive") {
      if (!payload.aliyunClientId) {
        return "请先填写阿里云盘 Client ID。";
      }
      const hasSecret = hasExistingSecret("#cloudBackupAliyunClientSecret");
      const hasRefreshToken = hasExistingSecret("#cloudBackupAliyunRefreshToken");
      if (!payload.aliyunClientSecret && !hasSecret) {
        return "请先填写阿里云盘 Client Secret。";
      }
      if (!payload.aliyunRefreshToken && !hasRefreshToken) {
        return "请先填写阿里云盘 Refresh Token。";
      }
    }
    if (payload.provider === "pan123") {
      if (!payload.pan123ClientId) {
        return "请先填写 123 云盘 Client ID。";
      }
      if (!payload.pan123ClientSecret && !hasExistingSecret("#cloudBackupPan123ClientSecret")) {
        return "请先填写 123 云盘 Client Secret。";
      }
    }
    return "";
  }

  function formatIdleSummary(status) {
    const count = Number(status.fileCount) || 0;
    if (status.lastRun?.state === "error") {
      return `上次备份异常：${status.lastRun.error || "未知错误"}`;
    }
    if (status.lastRun) {
      return `已记录 ${count} 个文件，下次 ${formatTimestamp(status.nextRunAt)}`;
    }
    return status.enabled ? `等待首次备份，下次 ${formatTimestamp(status.nextRunAt)}` : "未启用";
  }

  function formatRunSummary(run) {
    if (!run) {
      return "冷备份正在准备...";
    }
    return `正在备份 ${run.completed || 0}/${run.total || 0}，新增 ${run.uploaded || 0}，跳过 ${run.skipped || 0}`;
  }

  function formatRunCounts(run) {
    const failed = Number(run.failed) || 0;
    const base = `新增 ${run.uploaded || 0}，跳过 ${run.skipped || 0}，总数 ${run.total || 0}`;
    return failed ? `${base}，失败 ${failed}` : base;
  }

  function runStateLabel(state) {
    if (state === "error") return "异常";
    if (state === "queued") return "排队";
    if (state === "running") return "运行中";
    return "完成";
  }

  function formatTimestamp(value) {
    const timestamp = Number(value) || 0;
    if (!timestamp) {
      return "未安排";
    }
    return new Date(timestamp * 1000).toLocaleString();
  }

  function setValue(selector, value, property = "value") {
    const element = document.querySelector(selector);
    if (element) {
      element[property] = value;
    }
  }

  function setHidden(selector, hidden) {
    const element = document.querySelector(selector);
    if (element) {
      element.hidden = hidden;
    }
  }

  function setSecretPlaceholder(selector, hasValue) {
    const element = document.querySelector(selector);
    if (!element) {
      return;
    }
    element.dataset.hasSecret = hasValue ? "1" : "0";
    element.placeholder = hasValue ? "已保存，留空不修改" : "";
  }

  function hasExistingSecret(selector) {
    return document.querySelector(selector)?.dataset.hasSecret === "1";
  }

  function getStatusElement() {
    return document.querySelector("#cloudBackupStatus");
  }

  function clampInt(value, min, max, fallback) {
    const parsed = Number.parseInt(value, 10);
    if (!Number.isFinite(parsed)) {
      return fallback;
    }
    return Math.max(min, Math.min(max, parsed));
  }

  function escapeToken(value) {
    return String(value).replace(/[^a-z0-9_-]/gi, "");
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }
})();
