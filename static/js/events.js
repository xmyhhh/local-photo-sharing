backBtn.addEventListener("click", () => {
  if (state.folder) {
    navigateFolder(state.parent);
  }
});
refreshBtn.addEventListener("click", () => loadFolder(state.folder));
openBracketProjectBtn.addEventListener("click", () => openBracketProject());
window.addEventListener("scroll", scheduleVisibleWorkScan, { passive: true });
window.addEventListener("scroll", scheduleLoadMoreIfNeeded, { passive: true });
window.addEventListener("scroll", updateScrollTopButton, { passive: true });
scrollTopBtn.addEventListener("click", () => {
  window.scrollTo({ top: 0, behavior: "smooth" });
});
ratingFilterBtn.addEventListener("click", (event) => {
  event.stopPropagation();
  setRatingMenuOpen(ratingFilterMenu.hidden);
});
ratingFilterMenu.addEventListener("click", (event) => event.stopPropagation());
ratingFilterInputs.forEach((input) => {
  input.addEventListener("change", applyFilters);
});
dateFromFilter.addEventListener("change", applyFilters);
dateToFilter.addEventListener("change", applyFilters);
thumbModeSelect.value = state.thumbMode;
thumbModeSelect.addEventListener("change", () => setThumbMode(thumbModeSelect.value));
detectBracketsBtn.addEventListener("click", detectBracketsInContextFolder);
closeBracketDialogBtn.addEventListener("click", () => bracketDialog.close());
useBracketCacheBtn.addEventListener("click", () => {
  bracketCacheActions.hidden = true;
  renderBracketDetection(state.currentBracketResult);
  saveCurrentBracketProject();
});
rescanBracketsBtn.addEventListener("click", () => {
  resetBracketDialog();
  bracketStatus.textContent = "正在重新扫描...";
  startBracketDetection(true);
});
selectAllBracketGroups.addEventListener("change", () => setAllBracketGroups(selectAllBracketGroups.checked));
mergeBracketsBtn.addEventListener("click", mergeSelectedBracketGroups);
[mergeAlgorithm, mergeAlignment, mergeExposure, mergeShadows, mergeHighlights, mergeContrast, mergeSaturation, mergeSharpen, mergeQuality].forEach((input) => {
  input.addEventListener("change", saveCurrentBracketProject);
});
document.addEventListener("click", (event) => {
  if (!ratingFilterMenu.hidden && !ratingFilterMenu.contains(event.target) && event.target !== ratingFilterBtn) {
    setRatingMenuOpen(false);
  }
  if (!folderContextMenu.hidden && !folderContextMenu.contains(event.target)) {
    closeFolderContextMenu();
  }
});
document.addEventListener("contextmenu", (event) => {
  if (!event.target.closest(".tile-button")) {
    closeFolderContextMenu();
  }
});
clearFiltersBtn.addEventListener("click", () => {
  ratingFilterInputs.forEach((input) => {
    input.checked = false;
  });
  dateFromFilter.value = "";
  dateToFilter.value = "";
  applyFilters();
});
closeBtn.addEventListener("click", () => viewer.close());
prevBtn.addEventListener("click", () => showAdjacentPhoto(-1));
nextBtn.addEventListener("click", () => showAdjacentPhoto(1));
downloadBtn.addEventListener("click", downloadCurrentPhoto);
deleteBtn.addEventListener("click", requestDeleteCurrentPhoto);
cancelDeleteBtn.addEventListener("click", () => deleteDialog.close());
confirmDeleteBtn.addEventListener("click", async () => {
  deleteDialog.close();
  await deleteCurrentPhoto();
});
zoomInBtn.addEventListener("click", () => {
  setZoom(state.zoom + 0.25);
});
zoomOutBtn.addEventListener("click", () => {
  setZoom(state.zoom - 0.25);
});
zoomResetBtn.addEventListener("click", () => {
  setZoom(1);
});
function handleViewerWheel(event) {
  if (!viewer.open) {
    return;
  }
  event.preventDefault();
  event.stopImmediatePropagation();
  event.stopPropagation();
  const deltaY = "deltaY" in event ? event.deltaY : -event.wheelDelta || event.detail * 16 || 0;
  state.wheelZoomDelta += deltaY;
  state.wheelZoomCenter = { x: event.clientX, y: event.clientY };
  if (state.wheelZoomFrame) {
    return;
  }
  state.wheelZoomFrame = requestAnimationFrame(() => {
    const delta = Math.max(-240, Math.min(240, state.wheelZoomDelta));
    const center = state.wheelZoomCenter || { x: imageStage.clientWidth / 2, y: imageStage.clientHeight / 2 };
    state.wheelZoomDelta = 0;
    state.wheelZoomCenter = null;
    state.wheelZoomFrame = 0;
    setZoom(state.zoom * Math.exp(-delta * 0.0016), center.x, center.y);
  });
}
document.addEventListener("wheel", handleViewerWheel, { capture: true, passive: false });
document.addEventListener("mousewheel", handleViewerWheel, { capture: true, passive: false });
document.addEventListener("DOMMouseScroll", handleViewerWheel, { capture: true, passive: false });
imageStage.addEventListener("pointerdown", (event) => {
  if (event.pointerType !== "mouse" || state.zoom <= 1) {
    return;
  }
  event.preventDefault();
  imageStage.setPointerCapture(event.pointerId);
  state.isDragging = true;
  state.dragStart = { x: event.clientX, y: event.clientY, panX: state.panX, panY: state.panY };
});
imageStage.addEventListener("pointermove", (event) => {
  if (!state.isDragging || !state.dragStart) {
    return;
  }
  event.preventDefault();
  state.panX = state.dragStart.panX + event.clientX - state.dragStart.x;
  state.panY = state.dragStart.panY + event.clientY - state.dragStart.y;
  clampPan();
  updateZoom();
});
imageStage.addEventListener("pointerup", () => {
  state.isDragging = false;
  state.dragStart = null;
});
imageStage.addEventListener("pointercancel", () => {
  state.isDragging = false;
  state.dragStart = null;
});
imageStage.addEventListener("dblclick", (event) => {
  event.preventDefault();
  setZoom(state.zoom > 1 ? 1 : 2, event.clientX, event.clientY);
});
imageStage.addEventListener("touchstart", (event) => {
  event.preventDefault();
  for (const touch of event.changedTouches) {
    state.activeTouches.set(touch.identifier, { x: touch.clientX, y: touch.clientY });
  }
  if (state.activeTouches.size >= 2) {
    state.pinchDistance = distanceBetweenTouches();
    state.pinchZoom = state.zoom;
    const middle = midpointBetweenTouches();
    state.dragStart = { x: middle.x, y: middle.y, panX: state.panX, panY: state.panY };
  } else if (event.changedTouches.length === 1) {
    const touch = event.changedTouches[0];
    state.swipeStart = { x: touch.clientX, y: touch.clientY, time: Date.now() };
    state.dragStart = { x: touch.clientX, y: touch.clientY, panX: state.panX, panY: state.panY };
    state.swipeMoved = false;
  }
}, { passive: false });
imageStage.addEventListener(
  "touchmove",
  (event) => {
    event.preventDefault();
    for (const touch of event.changedTouches) {
      state.activeTouches.set(touch.identifier, { x: touch.clientX, y: touch.clientY });
    }
    if (state.activeTouches.size >= 2 && state.pinchDistance > 0) {
      const nextDistance = distanceBetweenTouches();
      const middle = midpointBetweenTouches();
      state.zoom = Math.max(1, Math.min(6, state.pinchZoom * (nextDistance / state.pinchDistance)));
      if (state.dragStart) {
        state.panX = state.dragStart.panX + middle.x - state.dragStart.x;
        state.panY = state.dragStart.panY + middle.y - state.dragStart.y;
        clampPan();
      }
      updateZoom();
    } else if (state.zoom > 1 && state.dragStart && event.changedTouches.length === 1) {
      const touch = event.changedTouches[0];
      state.panX = state.dragStart.panX + touch.clientX - state.dragStart.x;
      state.panY = state.dragStart.panY + touch.clientY - state.dragStart.y;
      clampPan();
      updateZoom();
    } else if (state.swipeStart && state.zoom === 1 && event.changedTouches.length === 1) {
      const touch = event.changedTouches[0];
      const dx = touch.clientX - state.swipeStart.x;
      const dy = touch.clientY - state.swipeStart.y;
      if (Math.abs(dx) > 12 && Math.abs(dx) > Math.abs(dy) * 1.4) {
        state.swipeMoved = true;
      }
    }
  },
  { passive: false },
);
imageStage.addEventListener("touchend", (event) => {
  const wasSingleTouch = state.activeTouches.size === 1 && event.changedTouches.length === 1;
  if (state.swipeStart && state.zoom === 1 && event.changedTouches.length === 1) {
    const touch = event.changedTouches[0];
    const dx = touch.clientX - state.swipeStart.x;
    const dy = touch.clientY - state.swipeStart.y;
    const elapsed = Date.now() - state.swipeStart.time;
    if (Math.abs(dx) > 70 && Math.abs(dx) > Math.abs(dy) * 1.4 && elapsed < 900) {
      showAdjacentPhoto(dx < 0 ? 1 : -1);
    }
  }
  if (wasSingleTouch && state.swipeStart && !state.swipeMoved) {
    const now = Date.now();
    const touch = event.changedTouches[0];
    if (now - state.lastTapTime < 300) {
      setZoom(state.zoom > 1 ? 1 : 2, touch.clientX, touch.clientY);
      state.lastTapTime = 0;
    } else {
      state.lastTapTime = now;
    }
  }
  clearEndedTouches(event);
  state.swipeStart = null;
  state.dragStart = null;
});
imageStage.addEventListener("touchcancel", clearEndedTouches);
document.addEventListener("keydown", (event) => {
  if (!viewer.open) {
    return;
  }
  if (event.key === "ArrowLeft") {
    event.preventDefault();
    showAdjacentPhoto(-1);
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    showAdjacentPhoto(1);
  } else if (event.key === "Escape") {
    event.preventDefault();
    viewer.close();
  }
});

function clearEndedTouches(event) {
  for (const touch of event.changedTouches) {
    state.activeTouches.delete(touch.identifier);
  }
  if (state.activeTouches.size < 2) {
    state.pinchDistance = 0;
  }
}

function updateScrollTopButton() {
  scrollTopBtn.hidden = window.scrollY < 700 || viewer.open || bracketDialog.open;
}

loadConfig()
  .then(() => loadFolder(""))
  .then(openInitialBracketProject)
  .then(updateScrollTopButton)
  .catch((error) => {
    emptyState.hidden = false;
    emptyState.textContent = error.message;
  });

function openInitialBracketProject() {
  const params = new URLSearchParams(window.location.search);
  const path = params.get("bracketProject");
  if (path !== null) {
    return openBracketProject(path || undefined);
  }
  return null;
}

