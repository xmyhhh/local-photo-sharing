const UPLOAD_CLIENT_TASK_ID = "core.upload";
const uploadTaskState = {
  running: false,
  backgrounded: false,
  completed: 0,
  total: 0,
  detail: "",
  state: "running",
  error: "",
};

function openUploadDialog() {
  if (uploadTaskState.running) {
    uploadTaskState.backgrounded = false;
    uploadDialog.showModal();
    updateUploadBackgroundButton();
    return;
  }
  const defaultFolder = state.folder || "";
  uploadFolderInput.value = defaultFolder;
  uploadFilesInput.value = "";
  if (!state.uploadPasswordRequired) {
    uploadPasswordInput.value = "";
  }
  setUploadStatus("", "");
  updateUploadRootLabel();
  uploadDialog.showModal();
}

function closeUploadDialog() {
  if (uploadTaskState.running) {
    backgroundUpload();
    return;
  }
  if (uploadDialog.open) {
    uploadDialog.close();
  }
}

function backgroundUpload() {
  if (!uploadTaskState.running) {
    return;
  }
  uploadTaskState.backgrounded = true;
  updateUploadBackgroundButton();
  if (uploadDialog.open) {
    uploadDialog.close();
  }
  updateClientTask(UPLOAD_CLIENT_TASK_ID);
}

function updateUploadRootLabel() {
  const root = state.roots[0];
  uploadRootLabel.textContent = root ? `保存到 ${root.path}` : "";
}

async function createUploadFolder() {
  const folder = normalizeUploadFolder(uploadFolderInput.value);
  if (!folder) {
    setUploadStatus("请输入文件夹名称。", "error");
    return;
  }
  setUploadBusy(true);
  setUploadStatus("正在新建文件夹...", "");
  try {
    const result = await fetchJson("/api/upload-folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folder, password: getUploadPassword() }),
    });
    uploadFolderInput.value = result.folder || folder;
    setUploadStatus("文件夹已创建。", "success");
    if (result.root && result.root !== state.rootId) {
      state.rootId = result.root;
    }
    await loadFolder(result.folder || "");
  } catch (error) {
    setUploadStatus(error.message, "error");
  } finally {
    setUploadBusy(false);
  }
}

async function submitUpload(event) {
  event.preventDefault();
  const files = Array.from(uploadFilesInput.files || []);
  if (!files.length) {
    setUploadStatus("请选择要上传的照片或视频。", "error");
    return;
  }

  const formData = new FormData();
  formData.set("folder", normalizeUploadFolder(uploadFolderInput.value));
  formData.set("password", getUploadPassword());
  files.forEach((file) => formData.append("files", file, file.name));

  setUploadBusy(true);
  startUploadClientTask(files.length, normalizeUploadFolder(uploadFolderInput.value));
  setUploadStatus(`正在上传 ${files.length} 个文件...`, "");
  try {
    const response = await fetch("/api/upload", {
      method: "POST",
      body: formData,
    });
    const data = await parseUploadResponse(response);
    if (!response.ok) {
      throw new Error(data.message || `HTTP ${response.status}`);
    }
    const rejected = data.rejected?.length || 0;
    const saved = data.saved?.length || 0;
    const unpaired = data.unpairedLiveCandidates?.length || 0;
    uploadTaskState.completed = saved + rejected;
    uploadTaskState.state = rejected ? "error" : "running";
    uploadTaskState.error = rejected ? `${rejected} 个文件未导入` : "";
    const suffixParts = [];
    if (rejected) {
      suffixParts.push(`${rejected} 个文件未导入`);
    }
    if (unpaired) {
      suffixParts.push(`${unpaired} 张照片没有收到对应实况视频`);
    }
    const suffix = suffixParts.length ? `，${suffixParts.join("，")}` : "";
    setUploadStatus(`已上传 ${saved} 个文件${suffix}。`, rejected ? "error" : "success");
    finishUploadClientTask(rejected ? "error" : "done");
    if (unpaired) {
      showMissingLiveVideoNotice(data.unpairedLiveCandidates);
    }
    uploadFilesInput.value = "";
    if (data.root && data.root !== state.rootId) {
      state.rootId = data.root;
    }
    await loadFolder(data.folder || "");
  } catch (error) {
    setUploadStatus(error.message, "error");
    uploadTaskState.state = "error";
    uploadTaskState.error = error.message;
    finishUploadClientTask("error");
  } finally {
    setUploadBusy(false);
  }
}

function startUploadClientTask(total, folder) {
  uploadTaskState.running = true;
  uploadTaskState.backgrounded = false;
  uploadTaskState.completed = 0;
  uploadTaskState.total = total;
  uploadTaskState.detail = folder ? `上传到 ${folder}` : "上传到默认保存位置";
  uploadTaskState.state = "running";
  uploadTaskState.error = "";
  registerClientTask(UPLOAD_CLIENT_TASK_ID, {
    snapshot: uploadClientTaskSnapshot,
    open: openUploadDialogFromTask,
    retainSnapshot: true,
  });
  updateUploadBackgroundButton();
}

function finishUploadClientTask(stateValue) {
  uploadTaskState.running = false;
  uploadTaskState.backgrounded = false;
  uploadTaskState.state = stateValue;
  uploadTaskState.completed = uploadTaskState.total;
  updateUploadBackgroundButton();
  updateClientTask(UPLOAD_CLIENT_TASK_ID);
  unregisterClientTask(UPLOAD_CLIENT_TASK_ID);
}

function uploadClientTaskSnapshot() {
  return {
    title: "上传照片",
    detail: uploadTaskState.detail,
    source: "上传",
    state: uploadTaskState.state,
    progress: uploadTaskState.total ? uploadTaskState.completed / uploadTaskState.total : null,
    completed: uploadTaskState.completed,
    total: uploadTaskState.total,
    error: uploadTaskState.error,
    actionLabel: "打开上传",
  };
}

function openUploadDialogFromTask() {
  if (!uploadDialog.open) {
    uploadDialog.showModal();
  }
  uploadTaskState.backgrounded = false;
  updateUploadBackgroundButton();
}

function showMissingLiveVideoNotice(items) {
  const names = items.slice(0, 5).map((item) => item.name).join("、");
  const more = items.length > 5 ? ` 等 ${items.length} 张` : "";
  window.alert(
    `${names}${more} 没有收到对应的 MOV/M4V，因此只能按普通照片保存。\n\n` +
      "这是 iPhone 照片选择器交给网页的文件决定的；如果要保留实况，请再上传同名 MOV/M4V 文件，系统会自动配对。",
  );
}

async function parseUploadResponse(response) {
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

function normalizeUploadFolder(folder) {
  return String(folder || "")
    .replace(/\\/g, "/")
    .split("/")
    .map((part) => part.trim())
    .filter(Boolean)
    .join("/");
}

function setUploadBusy(busy) {
  submitUploadBtn.disabled = busy;
  createUploadFolderBtn.disabled = busy;
  closeUploadBtn.disabled = busy && !uploadTaskState.running;
  uploadFilesInput.disabled = busy;
  uploadFolderInput.disabled = busy;
  uploadPasswordInput.disabled = busy;
  updateUploadBackgroundButton();
}

function setUploadStatus(message, kind) {
  uploadStatus.textContent = message;
  uploadStatus.className = "upload-status";
  if (kind) {
    uploadStatus.classList.add(kind);
  }
}

function updateUploadBackgroundButton() {
  if (!backgroundUploadBtn) {
    return;
  }
  backgroundUploadBtn.hidden = !uploadTaskState.running || uploadTaskState.backgrounded;
}

function getUploadPassword() {
  return state.uploadPasswordRequired ? uploadPasswordInput.value : "";
}

backgroundUploadBtn?.addEventListener("click", backgroundUpload);
