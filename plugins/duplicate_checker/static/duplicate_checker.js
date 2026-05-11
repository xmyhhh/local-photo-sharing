const duplicateCheckerUi = {};
let duplicateCheckerResult = null;

initDuplicateCheckerPlugin();

function initDuplicateCheckerPlugin() {
  pluginDialogs?.append(createDuplicateCheckerDialog());
  registerPluginAction("duplicate_checker.scan_folder", scanDuplicatesInContextFolder);
  bindDuplicateCheckerEvents();
}

function createDuplicateCheckerDialog() {
  const template = document.createElement("template");
  template.innerHTML = `
    <dialog id="duplicateCheckerDialog" class="duplicate-dialog">
      <div class="duplicate-panel">
        <div class="duplicate-header">
          <div>
            <div class="duplicate-title">检查重复照片</div>
            <div id="duplicateCheckerPath" class="bracket-path"></div>
          </div>
          <button id="closeDuplicateCheckerBtn" class="ghost" type="button">关闭</button>
        </div>
        <div class="duplicate-body">
          <div id="duplicateCheckerStatus" class="duplicate-status"></div>
          <section id="duplicateStrategyPanel" class="duplicate-strategy" hidden>
            <div>
              <div class="duplicate-strategy-title">批量保留策略</div>
              <div class="duplicate-strategy-help">每组重复照片只保留 1 张。下面会自动填入常见文件夹，你可以直接编辑、删除或调整顺序。</div>
            </div>
            <label>
              优先保留文件夹/路径关键字
              <textarea id="duplicateKeepPriorityInput" rows="3" placeholder="例如：\n精选\n相机原片\n2026"></textarea>
            </label>
            <div class="duplicate-strategy-grid">
              <label>
                未匹配时保留
                <select id="duplicateFallbackSelect">
                  <option value="shortest">路径最短的文件</option>
                  <option value="oldest">修改时间最早的文件</option>
                  <option value="newest">修改时间最新的文件</option>
                  <option value="first">当前排序第一张</option>
                </select>
              </label>
              <label>
                删除前筛选
                <select id="duplicateDeleteScopeSelect">
                  <option value="all">删除所有非保留副本</option>
                  <option value="matched-only">只删除命中优先级之外的副本</option>
                </select>
              </label>
            </div>
            <label class="duplicate-inline-option">
              <input id="duplicateDeleteEmptyFoldersInput" type="checkbox" />
              删除后清理变空的文件夹
            </label>
            <div class="duplicate-strategy-actions">
              <button id="generateDuplicateStrategyBtn" class="ghost" type="button">生成删除策略</button>
              <button id="clearDuplicateSelectionBtn" class="ghost" type="button">清空选择</button>
            </div>
            <div id="duplicateStrategySummary" class="duplicate-strategy-summary"></div>
          </section>
          <div id="duplicateCheckerResults" class="duplicate-results"></div>
        </div>
        <div class="duplicate-actions">
          <button id="selectDuplicateCopiesBtn" class="ghost" type="button">选择每组副本</button>
          <button id="deleteDuplicateCopiesBtn" class="danger" type="button" disabled>删除选中照片</button>
        </div>
      </div>
    </dialog>
  `;
  const dialog = template.content.firstElementChild;
  duplicateCheckerUi.dialog = dialog;
  duplicateCheckerUi.path = dialog.querySelector("#duplicateCheckerPath");
  duplicateCheckerUi.status = dialog.querySelector("#duplicateCheckerStatus");
  duplicateCheckerUi.strategyPanel = dialog.querySelector("#duplicateStrategyPanel");
  duplicateCheckerUi.keepPriorityInput = dialog.querySelector("#duplicateKeepPriorityInput");
  duplicateCheckerUi.fallbackSelect = dialog.querySelector("#duplicateFallbackSelect");
  duplicateCheckerUi.deleteScopeSelect = dialog.querySelector("#duplicateDeleteScopeSelect");
  duplicateCheckerUi.deleteEmptyFoldersInput = dialog.querySelector("#duplicateDeleteEmptyFoldersInput");
  duplicateCheckerUi.generateStrategyButton = dialog.querySelector("#generateDuplicateStrategyBtn");
  duplicateCheckerUi.clearSelectionButton = dialog.querySelector("#clearDuplicateSelectionBtn");
  duplicateCheckerUi.strategySummary = dialog.querySelector("#duplicateStrategySummary");
  duplicateCheckerUi.results = dialog.querySelector("#duplicateCheckerResults");
  duplicateCheckerUi.closeButton = dialog.querySelector("#closeDuplicateCheckerBtn");
  duplicateCheckerUi.selectCopiesButton = dialog.querySelector("#selectDuplicateCopiesBtn");
  duplicateCheckerUi.deleteButton = dialog.querySelector("#deleteDuplicateCopiesBtn");
  return dialog;
}

function bindDuplicateCheckerEvents() {
  duplicateCheckerUi.closeButton.addEventListener("click", () => duplicateCheckerUi.dialog.close());
  duplicateCheckerUi.selectCopiesButton.addEventListener("click", selectDuplicateCopies);
  duplicateCheckerUi.generateStrategyButton.addEventListener("click", generateDuplicateDeleteStrategy);
  duplicateCheckerUi.clearSelectionButton.addEventListener("click", clearDuplicateSelection);
  duplicateCheckerUi.deleteButton.addEventListener("click", deleteSelectedDuplicatePhotos);
}

async function scanDuplicatesInContextFolder() {
  const folder = state.contextFolder;
  closeFolderContextMenu();
  if (!folder) {
    return;
  }
  const { root, folderPath } = splitDuplicateRootedFolder(folder.path);
  duplicateCheckerUi.path.textContent = displayDuplicateFolderPath(root, folderPath);
  duplicateCheckerUi.status.textContent = "正在递归计算 MD5...";
  duplicateCheckerUi.results.innerHTML = "";
  duplicateCheckerUi.strategyPanel.hidden = true;
  duplicateCheckerUi.strategySummary.textContent = "";
  duplicateCheckerResult = null;
  duplicateCheckerUi.deleteButton.disabled = true;
  duplicateCheckerUi.dialog.showModal();
  try {
    const params = new URLSearchParams({ root, folder: folderPath });
    const result = await fetchJson(`/api/duplicate-checker/scan?${params.toString()}`);
    renderDuplicateScanResult(result);
  } catch (error) {
    duplicateCheckerUi.status.textContent = error.message;
  }
}

function renderDuplicateScanResult(result) {
  duplicateCheckerResult = result;
  duplicateCheckerUi.results.innerHTML = "";
  if (!result.groups.length) {
    duplicateCheckerUi.status.textContent = "没有发现 MD5 完全一致的重复照片。";
    duplicateCheckerUi.strategyPanel.hidden = true;
    return;
  }
  duplicateCheckerUi.status.textContent = `发现 ${result.groups.length} 组重复，最多可删除 ${result.duplicateCount} 张副本。`;
  duplicateCheckerUi.strategyPanel.hidden = false;
  seedDuplicatePriorityInput(result);
  result.groups.forEach((group, groupIndex) => {
    duplicateCheckerUi.results.append(createDuplicateGroup(group, groupIndex));
  });
  updateDuplicateDeleteState();
}

function createDuplicateGroup(group, groupIndex) {
  const section = document.createElement("section");
  section.className = "duplicate-group";
  section.dataset.groupIndex = String(groupIndex);

  const title = document.createElement("div");
  title.className = "duplicate-group-title";
  title.textContent = `${group.photos.length} 张相同照片 · MD5 ${group.md5} · ${formatDuplicateSize(group.size)}`;
  section.append(title);

  group.photos.forEach((photo, index) => {
    const row = document.createElement("label");
    row.className = "duplicate-photo";
    row.dataset.path = photo.path;
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = photo.path;
    checkbox.addEventListener("change", updateDuplicateDeleteState);
    const img = document.createElement("img");
    img.alt = photo.name;
    const spinner = document.createElement("span");
    spinner.className = "duplicate-thumb-spinner spinner";
    loadDuplicateThumbnail(photo, img, spinner);
    const text = document.createElement("div");
    const path = document.createElement("div");
    path.className = "duplicate-photo-path";
    path.textContent = photo.displayPath || photo.path;
    const meta = document.createElement("div");
    meta.className = "duplicate-photo-meta";
    meta.textContent = `${index === 0 ? "默认保留" : "副本"} · ${formatDuplicateSize(photo.size)}`;
    text.append(path, meta);
    const thumb = document.createElement("div");
    thumb.className = "duplicate-thumb";
    thumb.append(spinner, img);
    row.append(checkbox, thumb, text);
    section.append(row);
  });
  return section;
}

async function loadDuplicateThumbnail(photo, img, spinner, attempt = 0) {
  if (!img.isConnected && attempt > 0) {
    return;
  }
  try {
    const response = await fetch(`/api/thumb-status/${encodePath(photo.path)}?mode=small`, { cache: "no-store" });
    if (response.status === 200) {
      const data = await response.json();
      img.onload = () => {
        img.classList.add("loaded");
        spinner.hidden = true;
      };
      img.onerror = () => showDuplicateImageFallback(photo, img, spinner);
      img.src = withVersion(data.url, photo.mtime);
      if (img.complete && img.naturalWidth > 0) {
        img.classList.add("loaded");
        spinner.hidden = true;
      }
      return;
    }
    if (response.status !== 202) {
      showDuplicateImageFallback(photo, img, spinner);
      return;
    }
  } catch {
    showDuplicateImageFallback(photo, img, spinner);
    return;
  }
  if (attempt >= 8) {
    showDuplicateImageFallback(photo, img, spinner);
    return;
  }
  window.setTimeout(() => loadDuplicateThumbnail(photo, img, spinner, attempt + 1), Math.min(2600, 400 + attempt * 250));
}

function showDuplicateImageFallback(photo, img, spinner) {
  img.onload = () => {
    img.classList.add("loaded");
    spinner.hidden = true;
  };
  img.onerror = () => {
    spinner.classList.add("failed");
  };
  img.src = `/api/image/${encodePath(photo.path)}`;
}

function selectDuplicateCopies() {
  duplicateCheckerUi.results.querySelectorAll(".duplicate-group").forEach((group) => {
    const boxes = Array.from(group.querySelectorAll("input[type='checkbox']"));
    boxes.forEach((box, index) => {
      box.checked = index > 0;
    });
  });
  updateDuplicateDeleteState();
}

function seedDuplicatePriorityInput(result) {
  if (duplicateCheckerUi.keepPriorityInput.value.trim()) {
    return;
  }
  const folders = new Map();
  result.groups.flatMap((group) => group.photos).forEach((photo) => {
    const folder = displayFolderFromPhoto(photo);
    if (!folder) {
      return;
    }
    folders.set(folder, (folders.get(folder) || 0) + 1);
  });
  const suggestions = Array.from(folders.entries())
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, 6)
    .map(([folder]) => folder);
  duplicateCheckerUi.keepPriorityInput.value = suggestions.join("\n");
  duplicateCheckerUi.keepPriorityInput.placeholder = "每行一个，越靠上越优先。可以直接编辑、删除或调整顺序。";
}

function generateDuplicateDeleteStrategy() {
  if (!duplicateCheckerResult?.groups?.length) {
    return;
  }
  clearDuplicateSelection();
  const priorities = duplicateCheckerUi.keepPriorityInput.value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
  const fallback = duplicateCheckerUi.fallbackSelect.value;
  const scope = duplicateCheckerUi.deleteScopeSelect.value;
  const summary = {
    groups: 0,
    selected: 0,
    keptByPriority: 0,
    keptByFallback: 0,
    skipped: 0,
  };

  duplicateCheckerResult.groups.forEach((group, groupIndex) => {
    const decision = chooseDuplicateKeeper(group.photos, priorities, fallback);
    const groupElement = duplicateCheckerUi.results.querySelector(`.duplicate-group[data-group-index="${groupIndex}"]`);
    if (!decision.keep || !groupElement) {
      summary.skipped += 1;
      return;
    }
    summary.groups += 1;
    summary.keptByPriority += decision.reason === "priority" ? 1 : 0;
    summary.keptByFallback += decision.reason === "fallback" ? 1 : 0;
    groupElement.querySelectorAll(".duplicate-photo").forEach((row) => {
      const checkbox = row.querySelector("input[type='checkbox']");
      const photo = group.photos.find((item) => item.path === row.dataset.path);
      row.classList.toggle("duplicate-keep", row.dataset.path === decision.keep.path);
      if (!checkbox || !photo) {
        return;
      }
      const canDelete = row.dataset.path !== decision.keep.path && (scope === "all" || !matchesAnyPriority(photo, priorities));
      checkbox.checked = canDelete;
      if (canDelete) {
        summary.selected += 1;
      }
    });
  });

  duplicateCheckerUi.strategySummary.textContent = [
    `策略已生成：处理 ${summary.groups} 组，选中 ${summary.selected} 张待删除。`,
    `按优先级保留 ${summary.keptByPriority} 组，按兜底规则保留 ${summary.keptByFallback} 组。`,
    summary.skipped ? `跳过 ${summary.skipped} 组。` : "",
  ].filter(Boolean).join(" ");
  updateDuplicateDeleteState();
}

function chooseDuplicateKeeper(photos, priorities, fallback) {
  for (const priority of priorities) {
    const matched = photos.filter((photo) => photoSearchText(photo).includes(priority.toLowerCase()));
    if (matched.length) {
      return { keep: sortDuplicateCandidates(matched, fallback)[0], reason: "priority" };
    }
  }
  return { keep: sortDuplicateCandidates(photos, fallback)[0] || null, reason: "fallback" };
}

function sortDuplicateCandidates(photos, fallback) {
  return [...photos].sort((left, right) => {
    if (fallback === "oldest") {
      return left.mtime - right.mtime || compareDuplicatePath(left, right);
    }
    if (fallback === "newest") {
      return right.mtime - left.mtime || compareDuplicatePath(left, right);
    }
    if (fallback === "first") {
      return 0;
    }
    return displayPathForPhoto(left).length - displayPathForPhoto(right).length || compareDuplicatePath(left, right);
  });
}

function compareDuplicatePath(left, right) {
  return displayPathForPhoto(left).localeCompare(displayPathForPhoto(right));
}

function matchesAnyPriority(photo, priorities) {
  if (!priorities.length) {
    return false;
  }
  const text = photoSearchText(photo);
  return priorities.some((priority) => text.includes(priority.toLowerCase()));
}

function photoSearchText(photo) {
  return `${photo.path || ""}\n${photo.displayPath || ""}\n${photo.rel || ""}`.toLowerCase();
}

function clearDuplicateSelection() {
  duplicateCheckerUi.results.querySelectorAll(".duplicate-photo").forEach((row) => {
    row.classList.remove("duplicate-keep");
    const checkbox = row.querySelector("input[type='checkbox']");
    if (checkbox) {
      checkbox.checked = false;
    }
  });
  duplicateCheckerUi.strategySummary.textContent = "";
  updateDuplicateDeleteState();
}

async function deleteSelectedDuplicatePhotos() {
  const paths = selectedDuplicatePaths();
  if (!paths.length) {
    return;
  }
  const ok = window.confirm(`确认按当前选择删除 ${paths.length} 张重复照片？文件会移动到 .photo_share_trash。`);
  if (!ok) {
    return;
  }
  duplicateCheckerUi.deleteButton.disabled = true;
  duplicateCheckerUi.status.textContent = "正在删除选中照片...";
  try {
    const result = await fetchJson("/api/duplicate-checker/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        paths,
        deleteEmptyFolders: duplicateCheckerUi.deleteEmptyFoldersInput.checked,
      }),
    });
    removeDeletedDuplicateRows(new Set(result.deleted.map((item) => item.path)));
    const removedFolders = result.removedEmptyFolders?.length || 0;
    duplicateCheckerUi.status.textContent = `已删除 ${result.deleted.length} 张重复照片${removedFolders ? `，并清理 ${removedFolders} 个空文件夹` : ""}。`;
    duplicateCheckerUi.strategySummary.textContent = "删除完成。建议重新扫描一次，确认当前文件夹已经没有这些重复项。";
    updateDuplicateDeleteState();
    loadFolder(state.folder, { silent: true });
  } catch (error) {
    duplicateCheckerUi.status.textContent = error.message;
    updateDuplicateDeleteState();
  }
}

function selectedDuplicatePaths() {
  return Array.from(duplicateCheckerUi.results.querySelectorAll("input[type='checkbox']:checked")).map((input) => input.value);
}

function removeDeletedDuplicateRows(paths) {
  duplicateCheckerUi.results.querySelectorAll(".duplicate-photo").forEach((row) => {
    if (paths.has(row.dataset.path)) {
      row.remove();
    }
  });
  duplicateCheckerUi.results.querySelectorAll(".duplicate-group").forEach((group) => {
    if (group.querySelectorAll(".duplicate-photo").length < 2) {
      group.remove();
    }
  });
}

function updateDuplicateDeleteState() {
  duplicateCheckerUi.deleteButton.disabled = selectedDuplicatePaths().length === 0;
}

function splitDuplicateRootedFolder(path) {
  const value = path || "";
  const parts = value.split("/");
  const rootIds = (state.roots || []).map((root) => root.id).filter(Boolean);
  if (state.rootId && !rootIds.includes(state.rootId)) {
    rootIds.push(state.rootId);
  }
  if (rootIds.includes(parts[0])) {
    return { root: parts[0], folderPath: parts.slice(1).join("/") };
  }
  if (parts[0] === state.rootId) {
    return { root: parts[0], folderPath: parts.slice(1).join("/") };
  }
  return { root: state.rootId || rootIds[0] || "root1", folderPath: value };
}

function displayDuplicateFolderPath(rootId, folderPath) {
  const root = (state.roots || []).find((item) => item.id === rootId);
  const rootPath = root?.path || root?.name || rootId || "根目录";
  if (!folderPath) {
    return rootPath;
  }
  const separator = rootPath.includes("\\") ? "\\" : "/";
  return `${rootPath.replace(/[\\/]+$/, "")}${separator}${folderPath.replace(/\//g, separator)}`;
}

function displayPathForPhoto(photo) {
  return photo.displayPath || photo.path || "";
}

function displayFolderFromPhoto(photo) {
  const value = displayPathForPhoto(photo).replace(/[\\/]+$/, "");
  const index = Math.max(value.lastIndexOf("/"), value.lastIndexOf("\\"));
  return index > 0 ? value.slice(0, index) : "";
}

function formatDuplicateSize(size) {
  const value = Number(size) || 0;
  if (value >= 1024 * 1024) {
    return `${(value / 1024 / 1024).toFixed(1)} MB`;
  }
  if (value >= 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${value} B`;
}
