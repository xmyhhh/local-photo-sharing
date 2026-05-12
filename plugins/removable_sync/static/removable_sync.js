const removableSyncUi = {};
const removableSyncState = {
  targetFolder: "",
  targetLabel: "",
  files: [],
  destinationHashes: new Set(),
  cancelled: false,
  running: false,
};

const REMOVABLE_SYNC_EXTENSIONS = new Set([
  ".jpg", ".jpeg", ".heic", ".heif", ".mp4", ".mov", ".m4v", ".webm",
]);

initRemovableSyncPlugin();

function initRemovableSyncPlugin() {
  pluginDialogs?.append(createRemovableSyncDialog());
  registerPluginAction("removable_sync.sync_to_folder", openRemovableSyncForContextFolder);
  bindRemovableSyncEvents();
}

function createRemovableSyncDialog() {
  const template = document.createElement("template");
  template.innerHTML = `
    <dialog id="removableSyncDialog" class="removable-sync-dialog">
      <div class="removable-sync-panel">
        <header class="removable-sync-header">
          <div>
            <div class="removable-sync-title">从存储设备同步</div>
            <div id="removableSyncTarget" class="removable-sync-target"></div>
          </div>
          <button id="closeRemovableSyncBtn" class="ghost" type="button">关闭</button>
        </header>
        <div class="removable-sync-body">
          <div class="removable-sync-source-actions">
            <button id="chooseRemovableFolderBtn" type="button">选择文件夹</button>
            <button id="chooseRemovableFilesBtn" class="ghost" type="button">选择文件</button>
            <input id="removableFileInput" type="file" multiple accept="image/*,video/*,.jpg,.jpeg,.heic,.heif,.mov,.m4v,.mp4,.webm" hidden />
            <input id="removableDirectoryInput" type="file" multiple webkitdirectory accept="image/*,video/*,.jpg,.jpeg,.heic,.heif,.mov,.m4v,.mp4,.webm" hidden />
          </div>
          <div id="removableSyncSource" class="removable-sync-source">尚未选择来源。</div>
          <div class="removable-sync-stats" aria-live="polite">
            <div><span id="removableSyncTotal">0</span><small>来源文件</small></div>
            <div><span id="removableSyncReady">0</span><small>可导入</small></div>
            <div><span id="removableSyncDuplicate">0</span><small>已存在</small></div>
            <div><span id="removableSyncSaved">0</span><small>已导入</small></div>
            <div><span id="removableSyncError">0</span><small>异常</small></div>
          </div>
          <div class="removable-sync-progress" aria-hidden="true">
            <div id="removableSyncProgressFill"></div>
          </div>
          <div id="removableSyncStatus" class="removable-sync-status"></div>
          <div id="removableSyncList" class="removable-sync-list"></div>
        </div>
        <footer class="removable-sync-actions">
          <button id="cancelRemovableSyncBtn" class="ghost" type="button" disabled>取消</button>
          <button id="startRemovableSyncBtn" type="button" disabled>开始同步</button>
        </footer>
      </div>
    </dialog>
  `;
  const dialog = template.content.firstElementChild;
  removableSyncUi.dialog = dialog;
  removableSyncUi.target = dialog.querySelector("#removableSyncTarget");
  removableSyncUi.source = dialog.querySelector("#removableSyncSource");
  removableSyncUi.chooseFolderButton = dialog.querySelector("#chooseRemovableFolderBtn");
  removableSyncUi.chooseFilesButton = dialog.querySelector("#chooseRemovableFilesBtn");
  removableSyncUi.fileInput = dialog.querySelector("#removableFileInput");
  removableSyncUi.directoryInput = dialog.querySelector("#removableDirectoryInput");
  removableSyncUi.status = dialog.querySelector("#removableSyncStatus");
  removableSyncUi.list = dialog.querySelector("#removableSyncList");
  removableSyncUi.closeButton = dialog.querySelector("#closeRemovableSyncBtn");
  removableSyncUi.cancelButton = dialog.querySelector("#cancelRemovableSyncBtn");
  removableSyncUi.startButton = dialog.querySelector("#startRemovableSyncBtn");
  removableSyncUi.progressFill = dialog.querySelector("#removableSyncProgressFill");
  removableSyncUi.total = dialog.querySelector("#removableSyncTotal");
  removableSyncUi.ready = dialog.querySelector("#removableSyncReady");
  removableSyncUi.duplicate = dialog.querySelector("#removableSyncDuplicate");
  removableSyncUi.saved = dialog.querySelector("#removableSyncSaved");
  removableSyncUi.error = dialog.querySelector("#removableSyncError");
  return dialog;
}

function bindRemovableSyncEvents() {
  removableSyncUi.closeButton.addEventListener("click", closeRemovableSyncDialog);
  removableSyncUi.cancelButton.addEventListener("click", () => {
    removableSyncState.cancelled = true;
    removableSyncUi.status.textContent = "正在取消...";
  });
  removableSyncUi.chooseFolderButton.addEventListener("click", chooseRemovableFolderSource);
  removableSyncUi.chooseFilesButton.addEventListener("click", () => removableSyncUi.fileInput.click());
  removableSyncUi.fileInput.addEventListener("change", () => prepareRemovableFiles(Array.from(removableSyncUi.fileInput.files || []), "已选择文件"));
  removableSyncUi.directoryInput.addEventListener("change", () => prepareRemovableFiles(Array.from(removableSyncUi.directoryInput.files || []), "已选择文件夹"));
  removableSyncUi.startButton.addEventListener("click", startRemovableSync);
}

function openRemovableSyncForContextFolder() {
  const folder = state.contextFolder;
  closeFolderContextMenu();
  if (!folder) {
    return;
  }
  resetRemovableSyncState();
  removableSyncState.targetFolder = qualifyPath(folder.path);
  removableSyncState.targetLabel = removableSyncDisplayFolder(folder.path);
  removableSyncUi.target.textContent = `目标文件夹：${removableSyncState.targetLabel}`;
  removableSyncUi.dialog.showModal();
}

function closeRemovableSyncDialog() {
  if (removableSyncState.running) {
    removableSyncState.cancelled = true;
    removableSyncUi.status.textContent = "正在取消...";
    return;
  }
  removableSyncUi.dialog.close();
}

function resetRemovableSyncState() {
  removableSyncState.files = [];
  removableSyncState.destinationHashes = new Set();
  removableSyncState.cancelled = false;
  removableSyncState.running = false;
  removableSyncUi.source.textContent = "尚未选择来源。";
  removableSyncUi.status.textContent = "";
  removableSyncUi.list.innerHTML = "";
  removableSyncUi.progressFill.style.width = "0%";
  removableSyncUi.fileInput.value = "";
  removableSyncUi.directoryInput.value = "";
  setRemovableSyncBusy(false);
  updateRemovableSyncStats();
}

async function chooseRemovableFolderSource() {
  if (window.showDirectoryPicker) {
    try {
      const handle = await window.showDirectoryPicker({ mode: "read" });
      await prepareRemovableDirectoryHandle(handle);
      return;
    } catch (error) {
      if (error?.name === "AbortError") {
        return;
      }
      removableSyncUi.status.textContent = error.message || "无法读取所选文件夹。";
      return;
    }
  }
  removableSyncUi.directoryInput.click();
}

async function prepareRemovableDirectoryHandle(handle) {
  setRemovableSyncBusy(true, { scanning: true });
  removableSyncUi.source.textContent = `正在扫描：${handle.name || "所选文件夹"}`;
  removableSyncUi.status.textContent = "正在递归读取来源文件...";
  try {
    const files = [];
    await collectFilesFromDirectoryHandle(handle, files);
    prepareRemovableFiles(files, handle.name || "所选文件夹");
  } catch (error) {
    removableSyncUi.status.textContent = error.message || "扫描来源文件夹失败。";
  } finally {
    setRemovableSyncBusy(false);
  }
}

async function collectFilesFromDirectoryHandle(directoryHandle, files) {
  for await (const entry of directoryHandle.values()) {
    if (entry.kind === "file") {
      const file = await entry.getFile();
      files.push(file);
    } else if (entry.kind === "directory") {
      await collectFilesFromDirectoryHandle(entry, files);
    }
  }
}

function prepareRemovableFiles(files, sourceLabel) {
  const items = files
    .filter((file) => isRemovableSyncMedia(file.name))
    .map((file, index) => ({
      id: `${Date.now()}-${index}`,
      file,
      name: file.name,
      size: file.size,
      status: "pending",
      hash: "",
      message: "",
    }));
  removableSyncState.files = items;
  removableSyncUi.source.textContent = `${sourceLabel}：${files.length} 个文件，${items.length} 个照片/视频可同步。`;
  removableSyncUi.status.textContent = items.length ? "准备就绪。同步时会先计算 SHA-256 并自动跳过已导入文件。" : "没有找到支持的照片或视频。";
  removableSyncUi.startButton.disabled = !items.length;
  renderRemovableSyncList();
  updateRemovableSyncStats();
}

async function startRemovableSync() {
  if (removableSyncState.running || !removableSyncState.files.length) {
    return;
  }
  removableSyncState.cancelled = false;
  removableSyncState.running = true;
  setRemovableSyncBusy(true);
  try {
    await loadRemovableDestinationIndex();
    await hashRemovableFiles();
    await uploadRemovableFiles();
    const saved = removableSyncState.files.filter((item) => item.status === "saved").length;
    const duplicate = removableSyncState.files.filter((item) => item.status === "duplicate").length;
    const failed = removableSyncState.files.filter((item) => item.status === "error" || item.status === "rejected").length;
    removableSyncUi.status.textContent = `同步完成：导入 ${saved} 个，跳过已存在 ${duplicate} 个${failed ? `，异常 ${failed} 个` : ""}。`;
    if (saved) {
      await loadFolder(state.folder, { silent: true });
    }
  } catch (error) {
    removableSyncUi.status.textContent = error.message || "同步失败。";
  } finally {
    removableSyncState.running = false;
    setRemovableSyncBusy(false);
    updateRemovableSyncStats();
  }
}

async function loadRemovableDestinationIndex() {
  removableSyncUi.status.textContent = "正在读取目标文件夹去重索引...";
  const params = new URLSearchParams({ folder: removableSyncState.targetFolder });
  const result = await fetchJson(`/api/removable-sync/index?${params.toString()}`);
  removableSyncState.destinationHashes = new Set(result.hashes || []);
}

async function hashRemovableFiles() {
  let completed = 0;
  for (const item of removableSyncState.files) {
    if (removableSyncState.cancelled) {
      throw new Error("同步已取消。");
    }
    item.status = "hashing";
    item.message = "计算指纹";
    updateRemovableSyncRow(item);
    removableSyncUi.status.textContent = `正在计算指纹：${completed + 1}/${removableSyncState.files.length}`;
    item.hash = await sha256BrowserFile(item.file);
    if (removableSyncState.destinationHashes.has(item.hash)) {
      item.status = "duplicate";
      item.message = "目标文件夹已存在";
    } else {
      item.status = "ready";
      item.message = "等待上传";
    }
    completed += 1;
    updateRemovableSyncProgress(completed, removableSyncState.files.length * 2);
    updateRemovableSyncRow(item);
    updateRemovableSyncStats();
  }
}

async function uploadRemovableFiles() {
  const candidates = removableSyncState.files.filter((item) => item.status === "ready");
  let completed = removableSyncState.files.length;
  for (const item of candidates) {
    if (removableSyncState.cancelled) {
      throw new Error("同步已取消。");
    }
    item.status = "uploading";
    item.message = "上传中";
    updateRemovableSyncRow(item);
    removableSyncUi.status.textContent = `正在上传：${item.name}`;
    try {
      const result = await uploadRemovableFile(item);
      item.status = result.status === "saved" ? "saved" : result.status === "duplicate" ? "duplicate" : "rejected";
      item.message = removableSyncMessageForResult(result);
      if (result.hash) {
        removableSyncState.destinationHashes.add(result.hash);
      }
    } catch (error) {
      item.status = "error";
      item.message = error.message || "上传失败";
    }
    completed += 1;
    updateRemovableSyncProgress(completed, removableSyncState.files.length * 2);
    updateRemovableSyncRow(item);
    updateRemovableSyncStats();
  }
}

async function uploadRemovableFile(item) {
  const formData = new FormData();
  formData.set("folder", removableSyncState.targetFolder);
  formData.set("sha256", item.hash);
  formData.append("file", item.file, item.name);
  const response = await fetch("/api/removable-sync/upload", {
    method: "POST",
    body: formData,
  });
  const data = await parseRemovableSyncResponse(response);
  if (!response.ok) {
    throw new Error(data.message || `HTTP ${response.status}`);
  }
  return data;
}

async function parseRemovableSyncResponse(response) {
  const text = await response.text();
  if (!text) {
    return {};
  }
  try {
    return JSON.parse(text);
  } catch {
    return { message: text };
  }
}

async function sha256BrowserFile(file) {
  const buffer = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function renderRemovableSyncList() {
  removableSyncUi.list.innerHTML = "";
  removableSyncState.files.slice(0, 300).forEach((item) => {
    const row = document.createElement("div");
    row.className = "removable-sync-row";
    row.dataset.id = item.id;
    row.innerHTML = `
      <div class="removable-sync-row-name"></div>
      <div class="removable-sync-row-meta"></div>
    `;
    row.querySelector(".removable-sync-row-name").textContent = item.name;
    removableSyncUi.list.append(row);
    updateRemovableSyncRow(item);
  });
  if (removableSyncState.files.length > 300) {
    const more = document.createElement("div");
    more.className = "removable-sync-more";
    more.textContent = `还有 ${removableSyncState.files.length - 300} 个文件将参与同步。`;
    removableSyncUi.list.append(more);
  }
}

function updateRemovableSyncRow(item) {
  const row = removableSyncUi.list.querySelector(`.removable-sync-row[data-id="${CSS.escape(item.id)}"]`);
  if (!row) {
    return;
  }
  row.dataset.status = item.status;
  const meta = row.querySelector(".removable-sync-row-meta");
  meta.textContent = `${removableSyncStatusLabel(item.status)} · ${formatRemovableSyncSize(item.size)}${item.message ? ` · ${item.message}` : ""}`;
}

function updateRemovableSyncStats() {
  const files = removableSyncState.files;
  removableSyncUi.total.textContent = String(files.length);
  removableSyncUi.ready.textContent = String(files.filter((item) => item.status === "ready" || item.status === "uploading").length);
  removableSyncUi.duplicate.textContent = String(files.filter((item) => item.status === "duplicate").length);
  removableSyncUi.saved.textContent = String(files.filter((item) => item.status === "saved").length);
  removableSyncUi.error.textContent = String(files.filter((item) => item.status === "error" || item.status === "rejected").length);
}

function updateRemovableSyncProgress(completed, total) {
  const percent = total ? Math.min(100, Math.round((completed / total) * 100)) : 0;
  removableSyncUi.progressFill.style.width = `${percent}%`;
}

function setRemovableSyncBusy(busy, options = {}) {
  removableSyncUi.chooseFolderButton.disabled = busy;
  removableSyncUi.chooseFilesButton.disabled = busy;
  removableSyncUi.closeButton.disabled = Boolean(options.scanning);
  removableSyncUi.cancelButton.disabled = !busy || Boolean(options.scanning);
  removableSyncUi.startButton.disabled = busy || !removableSyncState.files.length;
}

function isRemovableSyncMedia(name) {
  const lower = String(name || "").toLowerCase();
  const index = lower.lastIndexOf(".");
  return index >= 0 && REMOVABLE_SYNC_EXTENSIONS.has(lower.slice(index));
}

function removableSyncStatusLabel(status) {
  return {
    pending: "待处理",
    hashing: "计算中",
    ready: "待导入",
    uploading: "上传中",
    saved: "已导入",
    duplicate: "已跳过",
    rejected: "不支持",
    error: "失败",
  }[status] || status;
}

function removableSyncMessageForResult(result) {
  if (result.status === "saved") {
    return result.name ? `保存为 ${result.name}` : "导入完成";
  }
  if (result.status === "duplicate") {
    return "服务端确认已存在";
  }
  return result.reason || result.message || "未导入";
}

function removableSyncDisplayFolder(path) {
  if (typeof displayDuplicateFolderPath === "function" && typeof splitDuplicateRootedFolder === "function") {
    const { root, folderPath } = splitDuplicateRootedFolder(path);
    return displayDuplicateFolderPath(root, folderPath);
  }
  return path || "目标文件夹";
}

function formatRemovableSyncSize(size) {
  const value = Number(size) || 0;
  if (value >= 1024 * 1024 * 1024) {
    return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
  }
  if (value >= 1024 * 1024) {
    return `${(value / 1024 / 1024).toFixed(1)} MB`;
  }
  if (value >= 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${value} B`;
}
