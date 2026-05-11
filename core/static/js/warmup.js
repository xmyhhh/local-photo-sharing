function startWarmupPolling() {
  stopWarmupPolling();
  if (state.authRole !== "admin") {
    if (warmupBanner) {
      warmupBanner.hidden = true;
    }
    return;
  }
  pollWarmupStatus();
}

function stopWarmupPolling() {
  if (state.warmupPollTimer) {
    window.clearTimeout(state.warmupPollTimer);
    state.warmupPollTimer = null;
  }
}

async function pollWarmupStatus() {
  if (state.authRole !== "admin") {
    stopWarmupPolling();
    if (warmupBanner) {
      warmupBanner.hidden = true;
    }
    return;
  }
  try {
    const status = await fetchJson("/api/warmup", { cache: "no-store" });
    renderWarmupStatus(status);
    if (status.state === "scanning" || status.state === "running") {
      state.warmupPollTimer = window.setTimeout(pollWarmupStatus, 800);
    } else if (status.state === "complete") {
      warmupBanner.hidden = true;
      state.warmupPollTimer = null;
    } else if (status.state === "error") {
      state.warmupPollTimer = window.setTimeout(() => {
        warmupBanner.hidden = true;
        state.warmupPollTimer = null;
      }, 10000);
    }
  } catch {
    state.warmupPollTimer = window.setTimeout(pollWarmupStatus, 2000);
  }
}

function renderWarmupStatus(status) {
  if (!warmupBanner || !status || status.state === "idle") {
    if (warmupBanner) {
      warmupBanner.hidden = true;
    }
    return;
  }

  const scanning = status.state === "scanning";
  const running = status.state === "running";
  const complete = status.state === "complete";
  const error = status.state === "error";
  const progress = Math.max(0, Math.min(1, Number(status.progress) || 0));
  const percent = Math.round(progress * 100);

  warmupBanner.hidden = scanning || complete;
  if (scanning || complete) {
    return;
  }
  warmupBanner.classList.toggle("complete", complete);
  warmupBanner.classList.toggle("error", error);
  warmupTitle.textContent = error ? "缩略图压缩失败" : "正在压缩缩略图";

  warmupProgressFill.classList.remove("indeterminate");
  warmupProgressFill.style.width = `${percent}%`;
  warmupPercent.textContent = `${percent}%`;

  const total = Number(status.total) || 0;
  const completed = Number(status.completed) || 0;
  const generated = Number(status.generated) || 0;
  const failed = Number(status.failed) || 0;
  const speed = running && status.elapsedSeconds > 0 ? ` · ${Math.round(completed / status.elapsedSeconds)}/秒` : "";
  const failedText = failed ? ` · 失败 ${failed}` : "";
  warmupDetail.textContent = error
    ? status.error || "预热过程中出现错误。"
    : `${status.stage || "正在生成缩略图缓存"} · ${completed}/${total} · 新生成 ${generated}${failedText}${speed}`;
}
