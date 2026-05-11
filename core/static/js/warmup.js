function startWarmupPolling() {
  stopWarmupPolling();
  pollWarmupStatus();
}

function stopWarmupPolling() {
  if (state.warmupPollTimer) {
    window.clearTimeout(state.warmupPollTimer);
    state.warmupPollTimer = null;
  }
}

async function pollWarmupStatus() {
  try {
    const status = await fetchJson("/api/warmup", { cache: "no-store" });
    renderWarmupStatus(status);
    if (status.state === "scanning" || status.state === "running") {
      state.warmupPollTimer = window.setTimeout(pollWarmupStatus, 800);
    } else if (status.state === "complete" || status.state === "error") {
      state.warmupPollTimer = window.setTimeout(() => {
        warmupBanner.hidden = true;
        state.warmupPollTimer = null;
      }, status.state === "complete" ? 3500 : 10000);
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

  const running = status.state === "scanning" || status.state === "running";
  const complete = status.state === "complete";
  const error = status.state === "error";
  const progress = Math.max(0, Math.min(1, Number(status.progress) || 0));
  const percent = Math.round(progress * 100);

  warmupBanner.hidden = false;
  warmupBanner.classList.toggle("complete", complete);
  warmupBanner.classList.toggle("error", error);
  warmupTitle.textContent = error ? "缩略图预热失败" : complete ? "缩略图预热完成" : "正在预热缩略图";

  if (status.state === "scanning") {
    warmupDetail.textContent = status.stage || "正在统计需要预热的缩略图...";
    warmupPercent.textContent = "...";
    warmupProgressFill.style.width = "18%";
    warmupProgressFill.classList.add("indeterminate");
    return;
  }

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
