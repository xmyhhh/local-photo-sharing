const bracketUi = {};

initBracketPluginUi();

function initBracketPluginUi() {
  pluginDialogs?.append(createBracketDialog());
  registerPluginAction("brackets.detect_folder", detectBracketsInContextFolder);
  registerPluginAction("brackets.open_project", () => openBracketProject());
  bindBracketPluginEvents();
}

function createBracketDialog() {
  const template = document.createElement("template");
  template.innerHTML = `
    <dialog id="bracketDialog" class="bracket-dialog">
      <div class="bracket-panel">
        <div class="bracket-header">
          <div>
            <div class="bracket-title">包围曝光检测</div>
            <div id="bracketDialogPath" class="bracket-path"></div>
          </div>
          <button id="closeBracketDialogBtn" class="ghost" type="button">关闭</button>
        </div>
        <div id="bracketCacheActions" class="bracket-cache-actions" hidden>
          <span>已有这个文件夹的扫描结果。</span>
          <button id="useBracketCacheBtn" type="button">使用结果</button>
          <button id="rescanBracketsBtn" class="ghost" type="button">重新扫描</button>
        </div>
        <div id="bracketStatus" class="bracket-status"></div>
        <div id="bracketMergePanel" class="bracket-merge-panel" hidden>
          <label><input id="selectAllBracketGroups" type="checkbox" /> 全选</label>
          <label>算法
            <select id="mergeAlgorithm">
              <option value="fusion">Fusion</option>
              <option value="debevec">Debevec</option>
              <option value="robertson">Robertson</option>
            </select>
          </label>
          <label>对齐
            <select id="mergeAlignment">
              <option value="simple">简单</option>
              <option value="people">人物/轻微移动</option>
              <option value="off">关闭</option>
              <option value="advanced">复杂</option>
            </select>
          </label>
          <label>曝光 <input id="mergeExposure" type="number" step="0.1" min="-2" max="2" value="0" /></label>
          <label>阴影 <input id="mergeShadows" type="number" step="0.05" min="0" max="1" value="0.25" /></label>
          <label>高光 <input id="mergeHighlights" type="number" step="0.05" min="0" max="1" value="0.15" /></label>
          <label>对比度 <input id="mergeContrast" type="number" step="0.05" min="0.5" max="2" value="1" /></label>
          <label>饱和度 <input id="mergeSaturation" type="number" step="0.05" min="0" max="2" value="1" /></label>
          <label>锐化 <input id="mergeSharpen" type="number" step="0.1" min="0" max="2" value="0.2" /></label>
          <label>质量 <input id="mergeQuality" type="number" step="1" min="70" max="98" value="92" /></label>
          <button id="mergeBracketsBtn" type="button">合成选中组</button>
        </div>
        <div id="bracketMergeOutput" class="bracket-merge-output" hidden></div>
        <div id="bracketResults" class="bracket-results"></div>
      </div>
    </dialog>
  `;
  const dialog = template.content.firstElementChild;
  bracketUi.bracketDialog = dialog;
  bracketUi.bracketDialogPath = dialog.querySelector("#bracketDialogPath");
  bracketUi.bracketStatus = dialog.querySelector("#bracketStatus");
  bracketUi.bracketResults = dialog.querySelector("#bracketResults");
  bracketUi.closeBracketDialogBtn = dialog.querySelector("#closeBracketDialogBtn");
  bracketUi.bracketCacheActions = dialog.querySelector("#bracketCacheActions");
  bracketUi.useBracketCacheBtn = dialog.querySelector("#useBracketCacheBtn");
  bracketUi.rescanBracketsBtn = dialog.querySelector("#rescanBracketsBtn");
  bracketUi.bracketMergePanel = dialog.querySelector("#bracketMergePanel");
  bracketUi.selectAllBracketGroups = dialog.querySelector("#selectAllBracketGroups");
  bracketUi.mergeAlgorithm = dialog.querySelector("#mergeAlgorithm");
  bracketUi.mergeAlignment = dialog.querySelector("#mergeAlignment");
  bracketUi.mergeExposure = dialog.querySelector("#mergeExposure");
  bracketUi.mergeShadows = dialog.querySelector("#mergeShadows");
  bracketUi.mergeHighlights = dialog.querySelector("#mergeHighlights");
  bracketUi.mergeContrast = dialog.querySelector("#mergeContrast");
  bracketUi.mergeSaturation = dialog.querySelector("#mergeSaturation");
  bracketUi.mergeSharpen = dialog.querySelector("#mergeSharpen");
  bracketUi.mergeQuality = dialog.querySelector("#mergeQuality");
  bracketUi.mergeBracketsBtn = dialog.querySelector("#mergeBracketsBtn");
  bracketUi.bracketMergeOutput = dialog.querySelector("#bracketMergeOutput");
  return dialog;
}

function bindBracketPluginEvents() {
  bracketUi.closeBracketDialogBtn.addEventListener("click", () => bracketUi.bracketDialog.close());
  bracketUi.useBracketCacheBtn.addEventListener("click", () => {
    bracketUi.bracketCacheActions.hidden = true;
    renderBracketDetection(state.currentBracketResult);
    saveCurrentBracketProject();
  });
  bracketUi.rescanBracketsBtn.addEventListener("click", () => {
    resetBracketDialog();
    bracketUi.bracketStatus.textContent = "正在重新扫描...";
    startBracketDetection(true);
  });
  bracketUi.selectAllBracketGroups.addEventListener("change", () => setAllBracketGroups(bracketUi.selectAllBracketGroups.checked));
  bracketUi.mergeBracketsBtn.addEventListener("click", mergeSelectedBracketGroups);
  [
    bracketUi.mergeAlgorithm,
    bracketUi.mergeAlignment,
    bracketUi.mergeExposure,
    bracketUi.mergeShadows,
    bracketUi.mergeHighlights,
    bracketUi.mergeContrast,
    bracketUi.mergeSaturation,
    bracketUi.mergeSharpen,
    bracketUi.mergeQuality,
  ].forEach((input) => input.addEventListener("change", saveCurrentBracketProject));
  window.openBracketProject = openBracketProject;
}

async function detectBracketsInContextFolder() {
  const folder = state.contextFolder;
  closeFolderContextMenu();
  if (!folder) {
    return;
  }
  const { root, folderPath } = splitRootedFolder(folder.path);
  state.currentBracketRoot = root;
  state.currentBracketFolder = folderPath;
  bracketUi.bracketDialogPath.textContent = folder.path || "根目录";
  resetBracketDialog();
  bracketUi.bracketStatus.textContent = "正在检查缓存...";
  bracketUi.bracketDialog.showModal();
  startBracketDetection(false);
}

function resetBracketDialog() {
  state.currentBracketResult = null;
  state.currentBracketMergeResult = null;
  state.currentBracketProjectPath = null;
  bracketUi.bracketCacheActions.hidden = true;
  bracketUi.bracketMergePanel.hidden = true;
  bracketUi.bracketMergeOutput.hidden = true;
  bracketUi.bracketMergeOutput.innerHTML = "";
  bracketUi.bracketResults.innerHTML = "";
  bracketUi.selectAllBracketGroups.checked = false;
}

async function startBracketDetection(force) {
  try {
    const params = new URLSearchParams();
    params.set("root", state.currentBracketRoot);
    params.set("folder", state.currentBracketFolder);
    if (force) {
      params.set("force", "1");
    }
    const start = await fetchJson(`/api/bracket-detection?${params.toString()}`, { method: "GET" });
    if (start.state === "cached") {
      state.currentBracketResult = start;
      bracketUi.bracketStatus.textContent = `已有缓存结果：${start.groups.length} 组。`;
      bracketUi.bracketCacheActions.hidden = false;
      saveCurrentBracketProject();
      return;
    }
    bracketUi.bracketCacheActions.hidden = true;
    renderBracketProgress(start, Date.now(), 0);
    pollBracketDetection(state.currentBracketRoot, state.currentBracketFolder, start.taskId);
  } catch (error) {
    bracketUi.bracketStatus.textContent = error.message;
  }
}

async function pollBracketDetection(root, folderPath, taskId) {
  const startedAt = Date.now();
  let lastProgress = 0;

  while (true) {
    try {
      const params = new URLSearchParams();
      params.set("root", root);
      params.set("folder", folderPath);
      params.set("task_id", taskId);
      const result = await fetchJson(`/api/bracket-detection?${params.toString()}`);
      if (result.state === "error") {
        bracketUi.bracketStatus.textContent = result.message;
        return;
      }
      if (result.state === "done") {
        renderBracketDetection(result);
        saveCurrentBracketProject();
        return;
      }
      lastProgress = result.progress || lastProgress;
      renderBracketProgress(result, startedAt, lastProgress);
    } catch (error) {
      bracketUi.bracketStatus.textContent = error.message;
      return;
    }
    await sleep(500);
  }
}

function renderBracketProgress(result, startedAt, lastProgress) {
  const progress = Number.isFinite(result.progress) ? result.progress : lastProgress;
  const percent = Math.max(0, Math.min(100, progress * 100));
  const elapsedSeconds = Number.isFinite(result.elapsedSeconds) ? result.elapsedSeconds : (Date.now() - startedAt) / 1000;
  const etaSeconds = Number.isFinite(result.etaSeconds) ? result.etaSeconds : estimateEta(result, elapsedSeconds);
  const stageText = result.stage === "stage2" ? "阶段2：特征匹配" : "阶段1：读取 EXIF";
  const groupText = `已找到 ${result.count || 0} 组包围曝光`;
  const timeText = `已耗时 ${formatDuration(elapsedSeconds)}`;
  const etaText = etaSeconds === null ? "预计还需计算中" : `预计还需 ${formatDuration(etaSeconds)}`;
  bracketUi.bracketStatus.textContent = `${stageText} · 进度 ${percent.toFixed(0)}% · ${groupText} · ${timeText} · ${etaText}`;
}

function renderBracketDetection(result) {
  state.currentBracketResult = result;
  state.currentBracketMergeResult = null;
  bracketUi.bracketResults.innerHTML = "";
  bracketUi.bracketMergeOutput.hidden = true;
  bracketUi.bracketMergeOutput.innerHTML = "";
  if (!result.groups.length) {
    const truncatedText = result.truncated ? ` 已扫描前 ${result.scanned} 张，目录过大，结果可能不完整。` : "";
    bracketUi.bracketStatus.textContent = `没有发现符合规则的包围曝光组。${truncatedText}`;
    bracketUi.bracketMergePanel.hidden = true;
    return;
  }
  const truncatedText = result.truncated ? ` 已扫描前 ${result.scanned} 张，目录过大，结果可能不完整。` : "";
  bracketUi.bracketStatus.textContent = `发现 ${result.groups.length} 组疑似包围曝光。${truncatedText}`;
  bracketUi.bracketMergePanel.hidden = false;

  result.groups.forEach((group) => {
    const section = document.createElement("section");
    section.className = "bracket-group";

    const title = document.createElement("label");
    title.className = "bracket-group-title";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "bracket-group-check";
    checkbox.value = String(group.id);
    checkbox.addEventListener("change", saveCurrentBracketProject);
    const exposureText = group.exposureRangeEv === null ? "无 EXIF 曝光跨度" : `曝光跨度 ${group.exposureRangeEv} EV`;
    const timeText = group.timeSpanSeconds === null ? "时间未知" : `时间跨度 ${group.timeSpanSeconds}s`;
    const titleText = document.createElement("span");
    titleText.textContent = `第 ${group.id} 组 · ${group.size} 张 · ${timeText} · 相似度 ${group.averageSimilarity} · ${exposureText}`;
    title.append(checkbox, titleText);
    section.append(title);

    const compare = document.createElement("div");
    compare.className = "bracket-compare";

    const sourcePane = document.createElement("div");
    sourcePane.className = "bracket-source-pane";
    const sourceTitle = document.createElement("div");
    sourceTitle.className = "bracket-pane-title";
    sourceTitle.textContent = "原始序列";
    const strip = document.createElement("div");
    strip.className = "bracket-strip";
    group.photos.forEach((photo) => {
      strip.append(createBracketPhotoButton(photo));
    });
    sourcePane.append(sourceTitle, strip);

    const resultPane = document.createElement("div");
    resultPane.className = "bracket-result-pane";
    resultPane.dataset.groupId = String(group.id);
    const resultTitle = document.createElement("div");
    resultTitle.className = "bracket-pane-title";
    resultTitle.textContent = "合成结果";
    const resultBody = document.createElement("div");
    resultBody.className = "bracket-result-body";
    resultBody.textContent = "选择本组并点击合成后显示。";
    resultPane.append(resultTitle, resultBody);

    compare.append(sourcePane, resultPane);
    section.append(compare);
    bracketUi.bracketResults.append(section);
  });
}

async function openBracketProject(path) {
  try {
    const params = new URLSearchParams();
    if (path) {
      params.set("path", path);
    }
    const data = await fetchJson(`/api/bracket-project?${params.toString()}`);
    restoreBracketProject(data.project, data.path);
  } catch (error) {
    window.alert(path ? `无法打开项目：${error.message}` : "还没有默认包围曝光项目。请先扫描一个文件夹生成项目。");
  }
}

function restoreBracketProject(project, path) {
  if (!project || !project.detection) {
    throw new Error("项目文件无效。");
  }
  state.currentBracketProjectPath = path || null;
  state.currentBracketRoot = project.root || state.rootId || "root1";
  state.currentBracketFolder = project.folder || "";
  state.rootId = state.currentBracketRoot;
  resetBracketDialog();
  state.currentBracketProjectPath = path || null;
  state.currentBracketRoot = project.root || state.rootId || "root1";
  state.currentBracketFolder = project.folder || "";
  bracketUi.bracketDialogPath.textContent = `${state.currentBracketRoot}/${state.currentBracketFolder}`.replace(/\/$/, "");
  applyMergeParams(project.params || {});
  bracketUi.bracketDialog.showModal();
  renderBracketDetection({ root: state.currentBracketRoot, folder: state.currentBracketFolder, state: "done", ...project.detection });
  restoreSelectedBracketGroups(project.selectedGroupIds || []);
  if (project.mergeResult) {
    renderMergeOutput(project.mergeResult);
  }
  bracketUi.bracketStatus.textContent = `已打开项目：${path || "bracket_project.prj"} · ${project.detection.groups?.length || 0} 组`;
}

function restoreSelectedBracketGroups(groupIds) {
  const selected = new Set(groupIds.map((groupId) => String(groupId)));
  document.querySelectorAll(".bracket-group-check").forEach((input) => {
    input.checked = selected.has(input.value);
  });
  bracketUi.selectAllBracketGroups.checked = Boolean(groupIds.length) && Array.from(document.querySelectorAll(".bracket-group-check")).every((input) => input.checked);
}

function applyMergeParams(params) {
  if (params.algorithm) bracketUi.mergeAlgorithm.value = params.algorithm;
  if (params.alignment) bracketUi.mergeAlignment.value = params.alignment;
  if (params.exposure !== undefined) bracketUi.mergeExposure.value = params.exposure;
  if (params.shadows !== undefined) bracketUi.mergeShadows.value = params.shadows;
  if (params.highlights !== undefined) bracketUi.mergeHighlights.value = params.highlights;
  if (params.contrast !== undefined) bracketUi.mergeContrast.value = params.contrast;
  if (params.saturation !== undefined) bracketUi.mergeSaturation.value = params.saturation;
  if (params.sharpen !== undefined) bracketUi.mergeSharpen.value = params.sharpen;
  if (params.quality !== undefined) bracketUi.mergeQuality.value = params.quality;
}

async function saveCurrentBracketProject() {
  if (!state.currentBracketResult) {
    return;
  }
  const project = {
    type: "photo-share-bracket-project",
    root: state.currentBracketRoot || state.rootId || "root1",
    folder: state.currentBracketFolder || "",
    detection: state.currentBracketResult,
    selectedGroupIds: currentSelectedBracketGroupIds(),
    params: getMergeParams(),
    mergeResult: state.currentBracketMergeResult,
  };
  try {
    const data = await fetchJson("/api/bracket-project", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: state.currentBracketProjectPath, project }),
    });
    state.currentBracketProjectPath = data.path;
    updateBracketProjectUrl(data.path);
  } catch (error) {
    bracketUi.bracketStatus.textContent = `项目保存失败：${error.message}`;
  }
}

function updateBracketProjectUrl(path) {
  if (!path || !bracketUi.bracketDialog.open) {
    return;
  }
  const url = new URL(window.location.href);
  url.searchParams.set("bracketProject", path);
  window.history.replaceState(null, "", url.toString());
}

function currentSelectedBracketGroupIds() {
  return Array.from(document.querySelectorAll(".bracket-group-check:checked")).map((input) => Number(input.value));
}

function createBracketPhotoButton(photo) {
  const displayPhoto = normalizeBracketPhoto(photo);
  const item = document.createElement("button");
  item.type = "button";
  item.className = "bracket-photo";
  item.title = displayPhoto.path;
  const img = document.createElement("img");
  img.alt = displayPhoto.name;
  img.src = withVersion(displayPhoto.thumbUrl, displayPhoto.mtime);
  img.onerror = () => {
    img.src = `/api/image/${encodePath(displayPhoto.path)}`;
  };
  const name = document.createElement("span");
  name.className = "bracket-photo-name";
  name.textContent = displayPhoto.name;
  const info = document.createElement("span");
  info.className = "bracket-photo-info";
  info.textContent = formatBracketPhotoInfo(displayPhoto);
  item.append(img, name, info);
  item.addEventListener("click", () => {
    openViewer(photoToEntry(displayPhoto));
  });
  return item;
}

function normalizeBracketPhoto(photo) {
  const path = qualifyPath(photo.path);
  return {
    ...photo,
    path,
    thumbUrl: photo.thumbUrl && photo.thumbUrl.includes(`/${state.rootId}/`)
      ? photo.thumbUrl
      : `/api/thumb/${encodePath(path)}`,
  };
}

async function mergeSelectedBracketGroups() {
  const groupIds = currentSelectedBracketGroupIds();
  if (!groupIds.length) {
    bracketUi.bracketMergeOutput.hidden = false;
    bracketUi.bracketMergeOutput.textContent = "先选择要合成的包围曝光组。";
    return;
  }
  bracketUi.bracketMergeOutput.hidden = false;
  markBracketGroupsMerging(groupIds);
  renderMergeProgress({ stage: "正在提交合成任务", progress: 0, processed: 0, total: groupIds.length });
  try {
    const start = await fetchJson("/api/bracket-merge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        root: state.currentBracketRoot,
        folder: state.currentBracketFolder,
        groupIds,
        groups: state.currentBracketResult?.groups || [],
        params: getMergeParams(),
      }),
    });
    saveCurrentBracketProject();
    pollBracketMerge(start.taskId);
  } catch (error) {
    bracketUi.bracketMergeOutput.textContent = error.message;
  }
}

async function pollBracketMerge(taskId) {
  while (true) {
    try {
      const status = await fetchJson("/api/bracket-merge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ taskId }),
      });
      if (status.state === "done") {
        renderMergeOutput(status.result);
        saveCurrentBracketProject();
        return;
      }
      if (status.state === "error") {
        bracketUi.bracketMergeOutput.textContent = status.message || "合成失败";
        return;
      }
      renderMergeProgress(status);
    } catch (error) {
      bracketUi.bracketMergeOutput.textContent = error.message;
      return;
    }
    await sleep(500);
  }
}

function renderMergeProgress(status) {
  const progress = Math.max(0, Math.min(1, Number(status.progress) || 0));
  bracketUi.bracketMergeOutput.innerHTML = "";
  const text = document.createElement("div");
  text.textContent = `${status.stage || "正在合成"} · ${Math.round(progress * 100)}% · ${status.processed || 0}/${status.total || 0}`;
  const bar = document.createElement("progress");
  bar.max = 100;
  bar.value = Math.round(progress * 100);
  bracketUi.bracketMergeOutput.append(text, bar);
}

function renderMergeOutput(result) {
  state.currentBracketMergeResult = result;
  bracketUi.bracketMergeOutput.innerHTML = "";
  const dir = document.createElement("div");
  dir.textContent = `临时目录：${result.outputDir}`;
  bracketUi.bracketMergeOutput.append(dir);
  result.files.forEach((file) => {
    renderGroupMergeResult(file);
  });
}

function markBracketGroupsMerging(groupIds) {
  groupIds.forEach((groupId) => {
    const pane = document.querySelector(`.bracket-result-pane[data-group-id="${groupId}"]`);
    if (!pane) {
      return;
    }
    const body = pane.querySelector(".bracket-result-body");
    body.innerHTML = "";
    const spinner = document.createElement("div");
    spinner.className = "spinner";
    const text = document.createElement("div");
    text.className = "bracket-result-note";
    text.textContent = "正在合成...";
    body.append(spinner, text);
  });
}

function renderGroupMergeResult(file) {
  const pane = document.querySelector(`.bracket-result-pane[data-group-id="${file.groupId}"]`);
  if (!pane) {
    return;
  }
  const body = pane.querySelector(".bracket-result-body");
  body.innerHTML = "";
  body.classList.add("has-result");

  const button = document.createElement("button");
  button.type = "button";
  button.className = "bracket-merged-photo";
  const img = document.createElement("img");
  img.alt = `第 ${file.groupId} 组合成结果`;
  img.src = file.imageUrl || file.downloadUrl;
  const caption = document.createElement("span");
  caption.textContent = `${formatMergeAlgorithm(file.algorithm)} · ${formatAlignMethod(file.alignMethod)}`;
  button.append(img, caption);
  button.addEventListener("click", () => {
    openViewer({
      type: "photo",
      name: file.name,
      path: file.path,
      thumbUrl: file.imageUrl || file.downloadUrl,
      originalUrl: file.imageUrl || file.downloadUrl,
      originalReady: true,
    });
  });

  const actions = document.createElement("div");
  actions.className = "bracket-result-actions";
  const download = document.createElement("a");
  download.href = file.downloadUrl;
  download.download = file.name;
  download.textContent = "下载合成图";
  actions.append(download);
  body.append(button, actions);
}

function formatMergeAlgorithm(algorithm) {
  if (algorithm === "debevec") {
    return "Debevec HDR";
  }
  if (algorithm === "robertson") {
    return "Robertson HDR";
  }
  return "Fusion";
}

function formatAlignMethod(method) {
  if (method === "none") {
    return "未对齐";
  }
  if (method === "simple-homography") {
    return "简单特征单应性对齐";
  }
  if (method === "simple-affine") {
    return "简单特征仿射对齐";
  }
  if (method === "simple-translation") {
    return "简单平移对齐";
  }
  if (method === "people-simple-homography") {
    return "人物轻微移动：简单对齐 + 去重影";
  }
  if (method === "people-simple-affine") {
    return "人物轻微移动：简单仿射 + 去重影";
  }
  if (method === "people-simple-translation") {
    return "人物轻微移动：平移 + 去重影";
  }
  if (method === "advanced-homography") {
    return "复杂特征单应性对齐";
  }
  if (method === "advanced-affine") {
    return "复杂特征仿射对齐";
  }
  if (method === "advanced-flow") {
    return "复杂光流细化对齐";
  }
  if (method === "advanced-translation") {
    return "复杂平移降级对齐";
  }
  if (method === "feature-homography") {
    return "特征点单应性对齐";
  }
  if (method === "feature-affine") {
    return "特征点仿射对齐";
  }
  if (method === "translation-fallback") {
    return "平移降级对齐";
  }
  return method;
}

function getMergeParams() {
  return {
    algorithm: bracketUi.mergeAlgorithm.value,
    alignment: bracketUi.mergeAlignment.value,
    exposure: bracketUi.mergeExposure.value,
    shadows: bracketUi.mergeShadows.value,
    highlights: bracketUi.mergeHighlights.value,
    contrast: bracketUi.mergeContrast.value,
    saturation: bracketUi.mergeSaturation.value,
    sharpen: bracketUi.mergeSharpen.value,
    quality: bracketUi.mergeQuality.value,
  };
}

function setAllBracketGroups(checked) {
  document.querySelectorAll(".bracket-group-check").forEach((input) => {
    input.checked = checked;
  });
  saveCurrentBracketProject();
}

function splitRootedFolder(path) {
  const parts = (path || "").split("/");
  const rootIds = (state.roots || []).map((root) => root.id).filter(Boolean);
  if (parts[0] === state.rootId || rootIds.includes(parts[0])) {
    return { root: parts[0], folderPath: parts.slice(1).join("/") };
  }
  return { root: state.rootId || "root1", folderPath: path || "" };
}

function estimateEta(result, elapsedSeconds) {
  if (!result.processed || !result.total || result.processed <= 0 || result.total <= result.processed) {
    return null;
  }
  return (elapsedSeconds / result.processed) * (result.total - result.processed);
}

function formatBracketPhotoInfo(photo) {
  const captureTime = photo.captureTime ? `拍摄 ${photo.captureTime}` : "拍摄时间未知";
  const aperture = photo.aperture ? ` · f/${formatDecimal(photo.aperture)}` : "";
  const focalLength = photo.focalLength ? ` · ${formatDecimal(photo.focalLength)}mm` : "";
  const exposure = photo.exposureTime ? ` · ${formatExposureTime(photo.exposureTime)}` : "";
  const bias = Number.isFinite(photo.exposureBias) ? ` · EV ${formatSignedDecimal(photo.exposureBias)}` : "";
  return `${captureTime}${aperture}${focalLength}${exposure}${bias}`;
}

function formatExposureTime(seconds) {
  if (seconds <= 0) {
    return "";
  }
  if (seconds < 1) {
    return `1/${Math.round(1 / seconds)}s`;
  }
  return `${seconds.toFixed(seconds >= 10 ? 0 : 1)}s`;
}

function formatDecimal(value) {
  return Number(value).toFixed(1).replace(/\.0$/, "");
}

function formatSignedDecimal(value) {
  const text = formatDecimal(value);
  return value > 0 ? `+${text}` : text;
}

function formatDuration(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  if (value < 60) {
    return `${value.toFixed(1)}秒`;
  }
  const minutes = Math.floor(value / 60);
  const remaining = value - minutes * 60;
  return `${minutes}分${remaining.toFixed(1)}秒`;
}

function photoToEntry(photo) {
  return {
    type: "photo",
    name: photo.name,
    path: photo.path,
    mtime: photo.mtime,
    rating: photo.rating || 0,
  };
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
