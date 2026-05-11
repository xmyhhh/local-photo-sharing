function startBackendTasksPolling() {
  stopBackendTasksPolling();
  if (state.authRole !== "admin") {
    hideBackendTasksUi();
    return;
  }
  pollBackendTasks();
}

function stopBackendTasksPolling() {
  if (state.backendTasksPollTimer) {
    window.clearTimeout(state.backendTasksPollTimer);
    state.backendTasksPollTimer = null;
  }
}

async function pollBackendTasks() {
  if (state.authRole !== "admin") {
    stopBackendTasksPolling();
    hideBackendTasksUi();
    return;
  }
  try {
    const payload = await fetchJson("/api/tasks", { cache: "no-store" });
    renderBackendTasks(payload);
    const hasTasks = (payload.tasks || []).length > 0;
    if (hasTasks || backendTasksDialog?.open) {
      state.backendTasksPollTimer = window.setTimeout(pollBackendTasks, hasTasks ? 1000 : 3000);
    } else {
      state.backendTasksPollTimer = null;
    }
  } catch {
    if (backendTasksBtn) {
      backendTasksBtn.hidden = true;
    }
    if (backendTasksDialog?.open) {
      state.backendTasksPollTimer = window.setTimeout(pollBackendTasks, 5000);
    } else {
      state.backendTasksPollTimer = null;
    }
  }
}

function notifyBackendTaskStarted() {
  document.dispatchEvent(new CustomEvent("photoShare:backend-task-started"));
  startBackendTasksPolling();
}

function hideBackendTasksUi() {
  state.backendTasks = [];
  state.backendTasksVisibleUntil = 0;
  if (backendTasksBtn) {
    backendTasksBtn.hidden = true;
  }
  if (backendTasksDialog?.open) {
    backendTasksDialog.close();
  }
}

function renderBackendTasks(payload) {
  const tasks = Array.isArray(payload?.tasks) ? payload.tasks : [];
  state.backendTasks = tasks;
  if (!backendTasksBtn) {
    return;
  }
  const now = Date.now();
  if (tasks.length > 0) {
    state.backendTasksVisibleUntil = now + 2500;
  }
  const keepVisible = Boolean(state.backendTasksVisibleUntil && now < state.backendTasksVisibleUntil);
  backendTasksBtn.hidden = tasks.length === 0 && !keepVisible;
  if (tasks.length === 0) {
    backendTasksBtn.classList.remove("has-error");
    if (backendTasksBadge) {
      backendTasksBadge.hidden = true;
      backendTasksBadge.textContent = "0";
    }
    if (backendTasksDialog?.open) {
      renderBackendTasksDialog(payload);
    }
    return;
  }
  const active = Number(payload.active) || tasks.filter((task) => isTaskActive(task)).length;
  const errors = Number(payload.errors) || tasks.filter((task) => task.state === "error").length;
  backendTasksBtn.classList.toggle("has-error", errors > 0);
  if (backendTasksBadge) {
    backendTasksBadge.hidden = active + errors <= 0;
    backendTasksBadge.textContent = String(active + errors);
  }
  if (backendTasksDialog?.open) {
    renderBackendTasksDialog(payload);
  }
}

function renderBackendTasksDialog(payload = { tasks: state.backendTasks }) {
  const tasks = Array.isArray(payload?.tasks) ? payload.tasks : state.backendTasks;
  const active = Number(payload?.active) || tasks.filter((task) => isTaskActive(task)).length;
  const errors = Number(payload?.errors) || tasks.filter((task) => task.state === "error").length;
  if (!tasks.length) {
    backendTasksSummary.textContent = "当前没有正在运行的后台任务";
    backendTasksList.innerHTML = `<div class="backend-tasks-empty">后台空闲。</div>`;
    return;
  }
  backendTasksSummary.textContent = errors
    ? `${active} 个任务运行中，${errors} 个任务异常`
    : `${active} 个任务运行中`;
  backendTasksList.innerHTML = "";
  const fragment = document.createDocumentFragment();
  tasks.forEach((task) => fragment.append(createBackendTaskRow(task)));
  backendTasksList.append(fragment);
}

function createBackendTaskRow(task) {
  const row = document.createElement("section");
  row.className = `backend-task-row state-${escapeCssToken(task.state || "running")}`;
  const progressPresent = task.progress !== null && task.progress !== undefined && task.progress !== "";
  const progress = progressPresent ? Number(task.progress) : NaN;
  const hasProgress = Number.isFinite(progress);
  const percent = hasProgress ? Math.round(Math.max(0, Math.min(1, progress)) * 100) : 0;
  const counts = formatTaskCounts(task);
  const progressLabel = hasProgress ? `${percent}%` : (task.progressMode === "activity" ? "活动中" : "处理中");
  row.innerHTML = `
    <div class="backend-task-main">
      <div>
        <div class="backend-task-title">${escapeHtml(task.title || "后台任务")}</div>
        <div class="backend-task-detail">${escapeHtml(task.detail || task.source || "")}</div>
      </div>
      <div class="backend-task-state">${escapeHtml(taskStateLabel(task.state))}</div>
    </div>
    <div class="backend-task-progress ${hasProgress ? "" : "indeterminate"}">
      <span style="width: ${hasProgress ? Math.max(2, percent) : 38}%"></span>
    </div>
    <div class="backend-task-meta">
      <span>${progressLabel}</span>
      ${counts ? `<span>${escapeHtml(counts)}</span>` : ""}
      ${task.error ? `<span class="backend-task-error">${escapeHtml(task.error)}</span>` : ""}
    </div>
  `;
  return row;
}

function isTaskActive(task) {
  return ["queued", "running", "scanning", "indexing"].includes(task?.state);
}

function taskStateLabel(state) {
  if (state === "queued") return "排队";
  if (state === "scanning") return "扫描";
  if (state === "indexing") return "索引";
  if (state === "error") return "异常";
  return "运行";
}

function formatTaskCounts(task) {
  const completed = task.completed;
  const total = task.total;
  if (completed === null || completed === undefined || completed === "") {
    return "";
  }
  if (total === null || total === undefined || total === "") {
    return `${completed}`;
  }
  return `${completed}/${total}`;
}

function escapeCssToken(value) {
  return String(value).replace(/[^a-z0-9_-]/gi, "");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

backendTasksBtn?.addEventListener("click", () => {
  renderBackendTasksDialog();
  backendTasksDialog.showModal();
  startBackendTasksPolling();
});

closeBackendTasksBtn?.addEventListener("click", () => backendTasksDialog.close());
