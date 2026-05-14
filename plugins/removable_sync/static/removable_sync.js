const removableSyncUi = {};
const REMOVABLE_SYNC_CLIENT_TASK_ID = "plugin.removable_sync";
const removableSyncState = {
  targetFolder: "",
  targetLabel: "",
  files: [],
  destinationHashes: new Set(),
  cancelled: false,
  running: false,
  backgrounded: false,
  completed: 0,
  total: 0,
  statusDetail: "",
  error: "",
  prepareToken: null,
};

const REMOVABLE_SYNC_EXTENSIONS = new Set([
  ".jpg", ".jpeg", ".png", ".hdr", ".heic", ".heif", ".mp4", ".mov", ".m4v", ".webm",
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
            <input id="removableFileInput" type="file" multiple accept="image/*,video/*,.jpg,.jpeg,.png,.hdr,.heic,.heif,.mov,.m4v,.mp4,.webm" hidden />
            <input id="removableDirectoryInput" type="file" multiple webkitdirectory hidden />
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
          <button id="backgroundRemovableSyncBtn" class="ghost" type="button" hidden>后台执行</button>
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
  removableSyncUi.backgroundButton = dialog.querySelector("#backgroundRemovableSyncBtn");
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
  removableSyncUi.backgroundButton.addEventListener("click", backgroundRemovableSync);
  removableSyncUi.cancelButton.addEventListener("click", () => {
    removableSyncState.cancelled = true;
    removableSyncUi.status.textContent = "正在取消...";
  });
  removableSyncUi.chooseFolderButton.addEventListener("click", chooseRemovableFolderSource);
  removableSyncUi.chooseFilesButton.addEventListener("click", () => removableSyncUi.fileInput.click());
  removableSyncUi.fileInput.addEventListener("change", () => {
    const files = Array.from(removableSyncUi.fileInput.files || []);
    removableSyncUi.fileInput.value = "";
    prepareRemovableFiles(files, "已选择文件");
  });
  removableSyncUi.directoryInput.addEventListener("change", () => {
    const files = Array.from(removableSyncUi.directoryInput.files || []);
    removableSyncUi.directoryInput.value = "";
    prepareRemovableFiles(files, "已选择文件夹");
  });
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
    backgroundRemovableSync();
    return;
  }
  removableSyncUi.dialog.close();
}

function backgroundRemovableSync() {
  if (!removableSyncState.running) {
    return;
  }
  removableSyncState.backgrounded = true;
  updateRemovableSyncBackgroundButton();
  if (removableSyncUi.dialog.open) {
    removableSyncUi.dialog.close();
  }
  updateClientTask(REMOVABLE_SYNC_CLIENT_TASK_ID);
}

function openRemovableSyncFromTask() {
  if (!removableSyncUi.dialog.open) {
    removableSyncUi.dialog.showModal();
  }
  removableSyncState.backgrounded = false;
  updateRemovableSyncBackgroundButton();
}

function resetRemovableSyncState() {
  releaseRemovableSyncItems(removableSyncState.files);
  removableSyncState.files = [];
  removableSyncState.destinationHashes = new Set();
  removableSyncState.cancelled = false;
  removableSyncState.running = false;
  removableSyncState.backgrounded = false;
  removableSyncState.completed = 0;
  removableSyncState.total = 0;
  removableSyncState.statusDetail = "";
  removableSyncState.error = "";
  removableSyncState.prepareToken = null;
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
    await prepareRemovableFiles(files, handle.name || "所选文件夹");
  } catch (error) {
    removableSyncUi.status.textContent = error.message || "扫描来源文件夹失败。";
    setRemovableSyncBusy(false);
    updateRemovableSyncStats();
  } finally {
    if (!removableSyncState.files.length) {
      setRemovableSyncBusy(false);
    }
  }
}

async function collectFilesFromDirectoryHandle(directoryHandle, files) {
  for await (const entry of directoryHandle.values()) {
    if (entry.kind === "file") {
      files.push({
        handle: entry,
        name: entry.name,
        size: 0,
      });
      if (files.length % 100 === 0) {
        removableSyncUi.status.textContent = `已读取 ${files.length} 个来源文件...`;
        await waitRemovableSyncFrame();
      }
    } else if (entry.kind === "directory") {
      await collectFilesFromDirectoryHandle(entry, files);
    }
  }
}

async function prepareRemovableFiles(files, sourceLabel) {
  if (removableSyncState.running) {
    return;
  }
  const token = Symbol("removable-sync-prepare");
  removableSyncState.prepareToken = token;
  releaseRemovableSyncItems(removableSyncState.files);
  removableSyncState.files = [];
  removableSyncState.destinationHashes = new Set();
  removableSyncUi.list.innerHTML = "";
  removableSyncUi.progressFill.style.width = "0%";
  removableSyncUi.source.textContent = `${sourceLabel}：正在读取文件列表...`;
  removableSyncUi.status.textContent = "正在整理来源文件...";
  setRemovableSyncBusy(true);
  updateRemovableSyncStats();
  await waitRemovableSyncFrame();

  const totalFiles = Number(files?.length) || 0;
  const batchSize = 100;
  const items = [];
  const runId = Date.now();
  try {
    for (let index = 0; index < totalFiles; index += 1) {
      const source = files[index];
      const name = removableSyncSourceName(source);
      if (name && isRemovableSyncMedia(name)) {
        items.push({
          id: `${runId}-${index}`,
          file: source instanceof File ? source : null,
          handle: source instanceof File ? null : source.handle || null,
          name,
          size: Number(source?.size) || 0,
          status: "pending",
          hash: "",
          message: "",
          finalized: false,
          uploadFile: null,
        });
      }
      const processed = index + 1;
      if (processed % batchSize === 0 || processed === totalFiles) {
        if (removableSyncState.prepareToken !== token) {
          return;
        }
        removableSyncUi.total.textContent = String(items.length);
        removableSyncUi.source.textContent = `${sourceLabel}：正在整理 ${processed}/${totalFiles} 个文件...`;
        removableSyncUi.status.textContent = `已找到 ${items.length} 个照片/视频。`;
        updateRemovableSyncProgress(processed, totalFiles);
        await waitRemovableSyncFrame();
      }
    }

    if (removableSyncState.prepareToken !== token) {
      return;
    }
    removableSyncState.files = items;
    removableSyncUi.source.textContent = `${sourceLabel}：${totalFiles} 个文件，${items.length} 个照片/视频可同步。`;
    removableSyncUi.status.textContent = items.length ? "准备就绪。同步时会边计算 SHA-256 边导入新文件。" : "没有找到支持的照片或视频。";
    renderRemovableSyncList();
    updateRemovableSyncStats();
    updateRemovableSyncProgress(0, items.length || 1);
  } catch (error) {
    removableSyncUi.status.textContent = error.message || "整理来源文件失败。";
    releaseRemovableSyncItems(items);
  } finally {
    if (removableSyncState.prepareToken === token) {
      removableSyncState.prepareToken = null;
      setRemovableSyncBusy(false);
    }
  }
}

async function startRemovableSync() {
  if (removableSyncState.running || !removableSyncState.files.length) {
    return;
  }
  removableSyncState.cancelled = false;
  removableSyncState.running = true;
  removableSyncState.backgrounded = false;
  removableSyncState.completed = 0;
  removableSyncState.total = removableSyncState.files.length;
  removableSyncState.statusDetail = removableSyncState.targetLabel;
  removableSyncState.error = "";
  setRemovableSyncBusy(true);
  registerClientTask(REMOVABLE_SYNC_CLIENT_TASK_ID, {
    snapshot: removableSyncClientTaskSnapshot,
    open: openRemovableSyncFromTask,
    retainSnapshot: true,
  });
  try {
    await loadRemovableDestinationIndex();
    await syncRemovableFiles();
    const saved = removableSyncState.files.filter((item) => item.status === "saved").length;
    const duplicate = removableSyncState.files.filter((item) => item.status === "duplicate").length;
    const failed = removableSyncState.files.filter((item) => item.status === "error" || item.status === "rejected").length;
    removableSyncUi.status.textContent = `同步完成：导入 ${saved} 个，跳过已存在 ${duplicate} 个${failed ? `，异常 ${failed} 个` : ""}。`;
    removableSyncState.completed = removableSyncState.total;
    removableSyncState.error = failed ? `${failed} 个文件异常` : "";
    if (saved) {
      await loadFolder(state.folder, { silent: true });
    }
  } catch (error) {
    removableSyncUi.status.textContent = error.message || "同步失败。";
    removableSyncState.error = error.message || "同步失败。";
  } finally {
    removableSyncState.running = false;
    removableSyncState.backgrounded = false;
    setRemovableSyncBusy(false);
    updateRemovableSyncStats();
    updateClientTask(REMOVABLE_SYNC_CLIENT_TASK_ID);
    window.setTimeout(() => unregisterClientTask(REMOVABLE_SYNC_CLIENT_TASK_ID), 2500);
    releaseRemovableSyncItems(removableSyncState.files);
  }
}

function removableSyncClientTaskSnapshot() {
  const errorCount = removableSyncState.files.filter((item) => item.status === "error" || item.status === "rejected").length;
  return {
    title: "同步存储设备",
    detail: removableSyncState.statusDetail || removableSyncState.targetLabel,
    source: "同步插件",
    state: removableSyncState.running ? "running" : errorCount || removableSyncState.error ? "error" : "done",
    progress: removableSyncState.total ? removableSyncState.completed / removableSyncState.total : null,
    completed: removableSyncState.completed,
    total: removableSyncState.total,
    error: removableSyncState.error,
    actionLabel: "打开同步",
  };
}

async function loadRemovableDestinationIndex() {
  removableSyncUi.status.textContent = "正在读取目标文件夹去重索引...";
  const params = new URLSearchParams({ folder: removableSyncState.targetFolder });
  const result = await fetchJson(`/api/removable-sync/index?${params.toString()}`);
  removableSyncState.destinationHashes = new Set(result.hashes || []);
}

async function syncRemovableFiles() {
  const nativeHash = hasNativeSha256();
  const progress = {
    hashed: 0,
    finalized: 0,
    total: removableSyncState.files.length,
  };
  for (const item of removableSyncState.files) {
    if (removableSyncState.cancelled) {
      throw new Error("同步已取消。");
    }
    item.status = "hashing";
    item.message = nativeHash ? "计算指纹" : "计算指纹（兼容模式）";
    updateRemovableSyncRow(item);
    removableSyncUi.status.textContent = `正在计算指纹：${progress.hashed + 1}/${progress.total}`;
    try {
      item.hash = await sha256RemovableItem(item);
    } catch (error) {
      if (removableSyncState.cancelled) {
        item.status = "pending";
        item.message = "已取消";
        updateRemovableSyncRow(item);
        throw new Error("同步已取消。");
      }
      item.status = "error";
      item.message = removableSyncFailureMessage(error, "指纹计算失败");
      if (isRemovableSyncSourceGoneError(error)) {
        removableSyncState.cancelled = true;
        progress.hashed += 1;
        finalizeRemovableSyncItem(item, progress);
        releaseRemovableSyncItemSource(item);
        updateRemovableSyncRow(item);
        updateRemovableSyncStats();
        throw new Error("来源设备已断开连接，请重新插入后再选择文件。");
      }
      progress.hashed += 1;
      finalizeRemovableSyncItem(item, progress);
      releaseRemovableSyncItemSource(item);
      updateRemovableSyncRow(item);
      updateRemovableSyncStats();
      continue;
    }
    progress.hashed += 1;
    if (removableSyncState.cancelled) {
      item.status = "pending";
      item.message = "已取消";
      updateRemovableSyncWorkProgress(progress);
      updateRemovableSyncRow(item);
      throw new Error("同步已取消。");
    }
    if (removableSyncState.destinationHashes.has(item.hash)) {
      item.status = "duplicate";
      item.message = "目标文件夹已存在";
      finalizeRemovableSyncItem(item, progress);
      releaseRemovableSyncItemSource(item);
      updateRemovableSyncWorkProgress(progress);
      updateRemovableSyncRow(item);
      updateRemovableSyncStats();
      continue;
    }
    item.status = "ready";
    item.message = "等待导入";
    updateRemovableSyncWorkProgress(progress);
    updateRemovableSyncRow(item);
    updateRemovableSyncStats();
    await uploadReadyRemovableFile(item, progress);
  }
  if (removableSyncState.cancelled) {
    throw new Error("同步已取消。");
  }
}

async function uploadReadyRemovableFile(item, progress) {
  if (removableSyncState.cancelled) {
    throw new Error("同步已取消。");
  }
  if (item.hash && removableSyncState.destinationHashes.has(item.hash)) {
    item.status = "duplicate";
    item.message = "本次同步已导入同内容文件";
    finalizeRemovableSyncItem(item, progress);
    releaseRemovableSyncItemSource(item);
    updateRemovableSyncRow(item);
    updateRemovableSyncStats();
    return;
  }
  item.status = "uploading";
  item.message = "导入中";
  updateRemovableSyncRow(item);
  removableSyncUi.status.textContent = `正在导入：${item.name}`;
  try {
    const result = await uploadRemovableFile(item);
    item.status = result.status === "saved" ? "saved" : result.status === "duplicate" ? "duplicate" : "rejected";
    item.message = removableSyncMessageForResult(result);
    if (result.hash) {
      removableSyncState.destinationHashes.add(result.hash);
    }
  } catch (error) {
    if (removableSyncState.cancelled) {
      throw new Error("同步已取消。");
    }
    if (isRemovableSyncSourceGoneError(error)) {
      item.status = "error";
      item.message = "来源设备已断开连接";
      finalizeRemovableSyncItem(item, progress);
      releaseRemovableSyncItemSource(item);
      updateRemovableSyncRow(item);
      updateRemovableSyncStats();
      removableSyncState.cancelled = true;
      throw new Error("来源设备已断开连接，请重新插入后再选择文件。");
    }
    item.status = "error";
    item.message = removableSyncFailureMessage(error, "导入失败");
  }
  finalizeRemovableSyncItem(item, progress);
  releaseRemovableSyncItemSource(item);
  updateRemovableSyncRow(item);
  updateRemovableSyncStats();
}

async function uploadRemovableFile(item) {
  const file = item.uploadFile || await resolveRemovableSyncFile(item);
  const formData = new FormData();
  formData.set("folder", removableSyncState.targetFolder);
  formData.set("sha256", item.hash);
  formData.append("file", file, item.name);
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

async function sha256RemovableItem(item) {
  const file = await resolveRemovableSyncFile(item);
  const buffer = await file.arrayBuffer();
  item.uploadFile = new Blob([buffer], { type: file.type || "application/octet-stream" });
  return sha256ArrayBufferHex(buffer);
}

async function resolveRemovableSyncFile(item) {
  if (item.file instanceof File) {
    return item.file;
  }
  if (!item.handle || typeof item.handle.getFile !== "function") {
    throw new Error("来源文件不可用");
  }
  const file = await item.handle.getFile();
  item.file = file;
  if (!item.size && Number(file.size) >= 0) {
    item.size = file.size;
    updateRemovableSyncRow(item);
  }
  if (!item.name) {
    item.name = file.name || item.name;
  }
  return file;
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
  return sha256ArrayBufferHex(buffer);
}

function hasNativeSha256() {
  return Boolean(window.crypto?.subtle?.digest);
}

async function sha256ArrayBufferHex(buffer) {
  const digest = hasNativeSha256()
    ? await window.crypto.subtle.digest("SHA-256", buffer)
    : sha256ArrayBuffer(buffer);
  return Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function sha256ArrayBuffer(buffer) {
  const bytes = new Uint8Array(buffer);
  const bitLength = bytes.length * 8;
  const paddedLength = (((bytes.length + 9 + 63) >> 6) << 6);
  const padded = new Uint8Array(paddedLength);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const view = new DataView(padded.buffer);
  view.setUint32(paddedLength - 4, bitLength >>> 0);
  view.setUint32(paddedLength - 8, Math.floor(bitLength / 0x100000000));

  const constants = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ];
  const words = new Uint32Array(64);
  let h0 = 0x6a09e667;
  let h1 = 0xbb67ae85;
  let h2 = 0x3c6ef372;
  let h3 = 0xa54ff53a;
  let h4 = 0x510e527f;
  let h5 = 0x9b05688c;
  let h6 = 0x1f83d9ab;
  let h7 = 0x5be0cd19;

  for (let offset = 0; offset < paddedLength; offset += 64) {
    for (let i = 0; i < 16; i += 1) {
      words[i] = view.getUint32(offset + i * 4);
    }
    for (let i = 16; i < 64; i += 1) {
      const s0 = rightRotate(words[i - 15], 7) ^ rightRotate(words[i - 15], 18) ^ (words[i - 15] >>> 3);
      const s1 = rightRotate(words[i - 2], 17) ^ rightRotate(words[i - 2], 19) ^ (words[i - 2] >>> 10);
      words[i] = (words[i - 16] + s0 + words[i - 7] + s1) >>> 0;
    }
    let a = h0;
    let b = h1;
    let c = h2;
    let d = h3;
    let e = h4;
    let f = h5;
    let g = h6;
    let h = h7;
    for (let i = 0; i < 64; i += 1) {
      const s1 = rightRotate(e, 6) ^ rightRotate(e, 11) ^ rightRotate(e, 25);
      const ch = (e & f) ^ (~e & g);
      const temp1 = (h + s1 + ch + constants[i] + words[i]) >>> 0;
      const s0 = rightRotate(a, 2) ^ rightRotate(a, 13) ^ rightRotate(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (s0 + maj) >>> 0;
      h = g;
      g = f;
      f = e;
      e = (d + temp1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (temp1 + temp2) >>> 0;
    }
    h0 = (h0 + a) >>> 0;
    h1 = (h1 + b) >>> 0;
    h2 = (h2 + c) >>> 0;
    h3 = (h3 + d) >>> 0;
    h4 = (h4 + e) >>> 0;
    h5 = (h5 + f) >>> 0;
    h6 = (h6 + g) >>> 0;
    h7 = (h7 + h) >>> 0;
  }

  const output = new ArrayBuffer(32);
  const outputView = new DataView(output);
  [h0, h1, h2, h3, h4, h5, h6, h7].forEach((value, index) => outputView.setUint32(index * 4, value));
  return output;
}

function rightRotate(value, bits) {
  return (value >>> bits) | (value << (32 - bits));
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

function finalizeRemovableSyncItem(item, progress) {
  if (item.finalized) {
    return;
  }
  item.finalized = true;
  progress.finalized += 1;
  updateRemovableSyncWorkProgress(progress);
}

function updateRemovableSyncWorkProgress(progress) {
  removableSyncState.completed = Math.min(progress.total, progress.finalized);
  removableSyncState.total = progress.total;
  updateRemovableSyncProgress(progress.hashed + progress.finalized, progress.total * 2);
  updateClientTask(REMOVABLE_SYNC_CLIENT_TASK_ID);
}

function updateRemovableSyncProgress(completed, total) {
  const percent = total ? Math.min(100, Math.round((completed / total) * 100)) : 0;
  removableSyncUi.progressFill.style.width = `${percent}%`;
}

function waitRemovableSyncFrame() {
  return new Promise((resolve) => window.requestAnimationFrame(() => resolve()));
}

function removableSyncSourceName(source) {
  return source instanceof File ? source.name : String(source?.name || "");
}

function releaseRemovableSyncItems(items) {
  items.forEach((item) => releaseRemovableSyncItemSource(item));
}

function releaseRemovableSyncItemSource(item) {
  if (!item) {
    return;
  }
  item.file = null;
  item.handle = null;
  item.uploadFile = null;
}

function setRemovableSyncBusy(busy, options = {}) {
  removableSyncUi.chooseFolderButton.disabled = busy;
  removableSyncUi.chooseFilesButton.disabled = busy;
  removableSyncUi.closeButton.disabled = Boolean(options.scanning);
  removableSyncUi.cancelButton.disabled = !busy || Boolean(options.scanning);
  removableSyncUi.startButton.disabled = busy || !removableSyncState.files.length;
  updateRemovableSyncBackgroundButton();
}

function updateRemovableSyncBackgroundButton() {
  if (!removableSyncUi.backgroundButton) {
    return;
  }
  removableSyncUi.backgroundButton.hidden = !removableSyncState.running || removableSyncState.backgrounded;
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

function removableSyncFailureMessage(error, fallback) {
  if (isRemovableSyncSourceGoneError(error)) {
    return "来源设备已断开连接";
  }
  return error?.message || fallback;
}

function isRemovableSyncSourceGoneError(error) {
  const name = String(error?.name || "");
  const message = String(error?.message || "").toLowerCase();
  return name === "NotFoundError"
    || name === "NotReadableError"
    || name === "AbortError"
    || message.includes("notfound")
    || message.includes("not found")
    || message.includes("notreadable")
    || message.includes("not readable")
    || message.includes("device")
    || message.includes("networkerror")
    || message.includes("network error");
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
