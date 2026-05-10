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
  bracketDialogPath.textContent = folder.path || "根目录";
  bracketStatus.textContent = "正在启动扫描...";
  bracketResults.innerHTML = "";
  bracketDialog.showModal();

  try {
    const params = new URLSearchParams();
    params.set("folder", folder.path);
    const start = await fetchJson(`/api/bracket-detection?${params.toString()}`, { method: "GET" });
    pollBracketDetection(folder.path, start.taskId);
  } catch (error) {
    bracketStatus.textContent = error.message;
  }
}

async function pollBracketDetection(folderPath, taskId) {
  const startedAt = Date.now();
  let lastProgress = 0;

  while (true) {
    try {
      const params = new URLSearchParams();
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
  const groupText = `已找到 ${result.count || 0} 组包围曝光`;
  const timeText = `已耗时 ${formatDuration(elapsedSeconds)}`;
  const etaText = `预计还需 ${formatDuration(etaSeconds)}`;
  bracketStatus.textContent = `扫描进度 ${percent.toFixed(0)}% · ${groupText} · ${timeText} · ${etaText}`;
}

function estimateEta(result, elapsedSeconds) {
  if (!result.processed || !result.total || result.processed <= 0 || result.total <= result.processed) {
    return 0;
  }
  const perPhoto = elapsedSeconds / result.processed;
  return perPhoto * (result.total - result.processed);
}

function renderBracketDetection(result) {
  bracketResults.innerHTML = "";
  if (!result.groups.length) {
    const truncatedText = result.truncated ? ` 已扫描前 ${result.scanned} 张，目录过大，结果可能不完整。` : "";
    bracketStatus.textContent = `没有发现符合规则的包围曝光组。${truncatedText}`;
    return;
  }
  const truncatedText = result.truncated ? ` 已扫描前 ${result.scanned} 张，目录过大，结果可能不完整。` : "";
  bracketStatus.textContent = `发现 ${result.groups.length} 组疑似包围曝光。${truncatedText}`;

  result.groups.forEach((group) => {
    const section = document.createElement("section");
    section.className = "bracket-group";

    const title = document.createElement("div");
    title.className = "bracket-group-title";
    const exposureText = group.exposureRangeEv === null ? "无 EXIF 曝光跨度" : `曝光跨度 ${group.exposureRangeEv} EV`;
    const timeText = group.timeSpanSeconds === null ? "时间未知" : `时间跨度 ${group.timeSpanSeconds}s`;
    title.textContent = `第 ${group.id} 组 · ${group.size} 张 · ${timeText} · 相似度 ${group.averageSimilarity} · ${exposureText}`;
    section.append(title);

    const strip = document.createElement("div");
    strip.className = "bracket-strip";
    group.photos.forEach((photo) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "bracket-photo";
      item.title = photo.path;
      const img = document.createElement("img");
      img.alt = photo.name;
      img.src = withVersion(photo.thumbUrl, photo.mtime);
      img.onerror = () => {
        img.src = `/api/image/${encodePath(photo.path)}`;
      };
      const name = document.createElement("span");
      name.className = "bracket-photo-name";
      name.textContent = photo.name;
      const info = document.createElement("span");
      info.className = "bracket-photo-info";
      info.textContent = formatBracketPhotoInfo(photo);
      item.append(img, name, info);
      item.addEventListener("click", () => {
        bracketDialog.close();
        openViewer(photoToEntry(photo));
      });
      strip.append(item);
    });
    section.append(strip);
    bracketResults.append(section);
  });
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
    const denominator = Math.round(1 / seconds);
    return `1/${denominator}s`;
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

