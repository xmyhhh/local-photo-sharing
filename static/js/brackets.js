function openFolderContextMenu(event, entry) {
  event.preventDefault();
  state.contextFolder = entry;
  folderContextMenu.hidden = false;
  const menuRect = folderContextMenu.getBoundingClientRect();
  const left = Math.min(event.clientX, window.innerWidth - menuRect.width - 8);
  const top = Math.min(event.clientY, window.innerHeight - menuRect.height - 8);
  folderContextMenu.style.left = `${Math.max(8, left)}px`;
  folderContextMenu.style.top = `${Math.max(8, top)}px`;
}

function closeFolderContextMenu() {
  folderContextMenu.hidden = true;
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
  bracketDialogPath.textContent = folder.path || "根目录";
  resetBracketDialog();
  bracketStatus.textContent = "正在检查缓存...";
  bracketDialog.showModal();
  startBracketDetection(false);
}

function resetBracketDialog() {
  state.currentBracketResult = null;
  bracketCacheActions.hidden = true;
  bracketMergePanel.hidden = true;
  bracketMergeOutput.hidden = true;
  bracketMergeOutput.innerHTML = "";
  bracketResults.innerHTML = "";
  selectAllBracketGroups.checked = false;
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
      bracketStatus.textContent = `已有缓存结果：${start.groups.length} 组。`;
      bracketCacheActions.hidden = false;
      return;
    }
    bracketCacheActions.hidden = true;
    renderBracketProgress(start, Date.now(), 0);
    pollBracketDetection(state.currentBracketRoot, state.currentBracketFolder, start.taskId);
  } catch (error) {
    bracketStatus.textContent = error.message;
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
        bracketStatus.textContent = result.message;
        return;
      }
      if (result.state === "done") {
        renderBracketDetection(result);
        return;
      }
      lastProgress = result.progress || lastProgress;
      renderBracketProgress(result, startedAt, lastProgress);
    } catch (error) {
      bracketStatus.textContent = error.message;
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
  bracketStatus.textContent = `${stageText} · 进度 ${percent.toFixed(0)}% · ${groupText} · ${timeText} · ${etaText}`;
}

function renderBracketDetection(result) {
  state.currentBracketResult = result;
  bracketResults.innerHTML = "";
  bracketMergeOutput.hidden = true;
  bracketMergeOutput.innerHTML = "";
  if (!result.groups.length) {
    const truncatedText = result.truncated ? ` 已扫描前 ${result.scanned} 张，目录过大，结果可能不完整。` : "";
    bracketStatus.textContent = `没有发现符合规则的包围曝光组。${truncatedText}`;
    bracketMergePanel.hidden = true;
    return;
  }
  const truncatedText = result.truncated ? ` 已扫描前 ${result.scanned} 张，目录过大，结果可能不完整。` : "";
  bracketStatus.textContent = `发现 ${result.groups.length} 组疑似包围曝光。${truncatedText}`;
  bracketMergePanel.hidden = false;

  result.groups.forEach((group) => {
    const section = document.createElement("section");
    section.className = "bracket-group";

    const title = document.createElement("label");
    title.className = "bracket-group-title";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "bracket-group-check";
    checkbox.value = String(group.id);
    const exposureText = group.exposureRangeEv === null ? "无 EXIF 曝光跨度" : `曝光跨度 ${group.exposureRangeEv} EV`;
    const timeText = group.timeSpanSeconds === null ? "时间未知" : `时间跨度 ${group.timeSpanSeconds}s`;
    const titleText = document.createElement("span");
    titleText.textContent = `第 ${group.id} 组 · ${group.size} 张 · ${timeText} · 相似度 ${group.averageSimilarity} · ${exposureText}`;
    title.append(checkbox, titleText);
    section.append(title);

    const strip = document.createElement("div");
    strip.className = "bracket-strip";
    group.photos.forEach((photo) => {
      strip.append(createBracketPhotoButton(photo));
    });
    section.append(strip);
    bracketResults.append(section);
  });
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
    bracketDialog.close();
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
  const groupIds = Array.from(document.querySelectorAll(".bracket-group-check:checked")).map((input) => Number(input.value));
  if (!groupIds.length) {
    bracketMergeOutput.hidden = false;
    bracketMergeOutput.textContent = "先选择要合成的包围曝光组。";
    return;
  }
  bracketMergeOutput.hidden = false;
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
    pollBracketMerge(start.taskId);
  } catch (error) {
    bracketMergeOutput.textContent = error.message;
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
        return;
      }
      if (status.state === "error") {
        bracketMergeOutput.textContent = status.message || "合成失败";
        return;
      }
      renderMergeProgress(status);
    } catch (error) {
      bracketMergeOutput.textContent = error.message;
      return;
    }
    await sleep(500);
  }
}

function renderMergeProgress(status) {
  const progress = Math.max(0, Math.min(1, Number(status.progress) || 0));
  bracketMergeOutput.innerHTML = "";
  const text = document.createElement("div");
  text.textContent = `${status.stage || "正在合成"} · ${Math.round(progress * 100)}% · ${status.processed || 0}/${status.total || 0}`;
  const bar = document.createElement("progress");
  bar.max = 100;
  bar.value = Math.round(progress * 100);
  bracketMergeOutput.append(text, bar);
}

function renderMergeOutput(result) {
  bracketMergeOutput.innerHTML = "";
  const dir = document.createElement("div");
  dir.textContent = `临时目录：${result.outputDir}`;
  bracketMergeOutput.append(dir);
  result.files.forEach((file) => {
    const link = document.createElement("a");
    link.href = file.downloadUrl;
    link.textContent = `下载第 ${file.groupId} 组合成结果`;
    link.download = file.name;
    bracketMergeOutput.append(link);
    if (file.alignMethod) {
      const method = document.createElement("div");
      method.textContent = `第 ${file.groupId} 组：${formatMergeAlgorithm(file.algorithm)} · ${formatAlignMethod(file.alignMethod)}`;
      bracketMergeOutput.append(method);
    }
  });
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
    algorithm: mergeAlgorithm.value,
    exposure: mergeExposure.value,
    contrast: mergeContrast.value,
    saturation: mergeSaturation.value,
    sharpen: mergeSharpen.value,
    quality: mergeQuality.value,
  };
}

function setAllBracketGroups(checked) {
  document.querySelectorAll(".bracket-group-check").forEach((input) => {
    input.checked = checked;
  });
}

function splitRootedFolder(path) {
  const parts = (path || "").split("/");
  if (parts[0] === state.rootId) {
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
