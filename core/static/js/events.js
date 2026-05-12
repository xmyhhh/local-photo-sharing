backBtn?.addEventListener("click", () => {
  if (state.folder) {
    navigateFolder(state.parent);
  } else if (state.rootId) {
    navigateVirtualRoot();
  }
});
refreshBtn?.addEventListener("click", () => loadFolder(state.folder));
openUploadBtn.addEventListener("click", openUploadDialog);
filterPanelToggleBtn.addEventListener("click", () => {
  setFilterPanelOpen(filterPanel.hidden);
});
window.addEventListener("scroll", scheduleVisibleWorkScan, { passive: true });
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
compactToggleBtn.textContent = state.compactMode ? "展开" : "精简";
updateFilterPanelLabel();
compactToggleBtn.addEventListener("click", () => {
  state.compactMode = !state.compactMode;
  window.localStorage.setItem("compactMode", state.compactMode ? "1" : "0");
  renderGrid();
});
document.addEventListener("click", (event) => {
  if (!ratingFilterMenu.hidden && !ratingFilterMenu.contains(event.target) && event.target !== ratingFilterBtn) {
    setRatingMenuOpen(false);
  }
  if (!viewerRatingMenu.hidden && !viewerRatingMenu.contains(event.target) && event.target !== viewerRatingBtn) {
    setViewerRatingMenuOpen(false);
  }
  if (!folderContextMenu.hidden && !folderContextMenu.contains(event.target)) {
    closeFolderContextMenu();
  }
  if (!blankContextMenu.hidden && !blankContextMenu.contains(event.target)) {
    blankContextMenu.hidden = true;
  }
  if (!itemContextMenu.hidden && !itemContextMenu.contains(event.target)) {
    itemContextMenu.hidden = true;
  }
});
document.addEventListener("contextmenu", (event) => {
  if (shouldSuppressNativeTouchMenu(event)) {
    event.preventDefault();
    event.stopPropagation();
    return;
  }
  if (!event.target.closest(".tile-button") && !event.target.closest(".tile")) {
    closeAllContextMenus();
  }
});
document.addEventListener("selectstart", (event) => {
  if (shouldSuppressNativeTouchMenu(event)) {
    event.preventDefault();
  }
});
document.addEventListener("dragstart", (event) => {
  if (shouldSuppressNativeTouchMenu(event)) {
    event.preventDefault();
  }
});
grid.addEventListener("click", handleGridTileClick);
grid.addEventListener("contextmenu", handleGridTileContextMenu);
grid.addEventListener("click", handleGridRatingClick);
grid.addEventListener("pointerdown", handleGridTilePointerDown);
grid.addEventListener("pointermove", cancelLongPressIfMoved);
grid.addEventListener("pointermove", updateBoxSelection);
grid.addEventListener("pointerup", cancelLongPress);
grid.addEventListener("pointerup", finishBoxSelection);
grid.addEventListener("pointercancel", cancelLongPress);
grid.addEventListener("pointercancel", cancelBoxSelection);
copySelectedBtn.addEventListener("click", () => copyOrMoveSelected(false));
cutSelectedBtn.addEventListener("click", cutSelectedEntries);
downloadSelectedBtn.addEventListener("click", downloadSelectedEntries);
moveSelectedBtn.addEventListener("click", () => copyOrMoveSelected(true));
deleteSelectedBtn.addEventListener("click", () => deleteEntries(Array.from(state.selectedPaths)));
invertSelectionBtn.addEventListener("click", invertSelection);
exitSelectionBtn.addEventListener("click", exitSelectionMode);
batchRatingButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const rating = Number.parseInt(button.dataset.batchRating, 10);
    if (Number.isFinite(rating)) {
      rateSelectedPhotos(rating);
    }
  });
});
clearFiltersBtn.addEventListener("click", () => {
  ratingFilterInputs.forEach((input) => {
    input.checked = false;
  });
  dateFromFilter.value = "";
  dateToFilter.value = "";
  setFilterPanelOpen(false);
  applyFilters();
});
closeBtn.addEventListener("click", () => closeViewerFromUi());
bindPageButton(prevBtn, -1);
bindPageButton(nextBtn, 1);
livePhotoBtn.addEventListener("click", toggleLivePhotoPlayback);
infoBtn.addEventListener("click", togglePhotoInfoPanel);
closeInfoBtn.addEventListener("click", closePhotoInfoPanel);
downloadBtn.addEventListener("click", downloadCurrentPhoto);
deleteBtn.addEventListener("click", requestDeleteCurrentPhoto);
rotateBtn.addEventListener("click", rotateCurrentPhoto);
viewerRatingBtn.addEventListener("click", (event) => {
  event.stopPropagation();
  setViewerRatingMenuOpen(viewerRatingMenu.hidden);
});
viewerRatingMenu.addEventListener("click", (event) => event.stopPropagation());
cancelDeleteBtn.addEventListener("click", () => {
  deleteDialog.close();
});
deleteDialog.addEventListener("close", updateViewerControlsLock);
confirmDeleteBtn.addEventListener("click", async () => {
  deleteDialog.close();
  await deleteCurrentPhoto();
});
closeUploadBtn.addEventListener("click", closeUploadDialog);
createUploadFolderBtn.addEventListener("click", createUploadFolder);
uploadForm.addEventListener("submit", submitUpload);
zoomResetBtn.addEventListener("click", () => {
  setZoom(1);
});
function handleViewerWheel(event) {
  if (!viewer.open || isViewerLocked()) {
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
  if (isViewerLocked() || event.pointerType !== "mouse" || state.zoom <= 1) {
    return;
  }
  event.preventDefault();
  imageStage.setPointerCapture(event.pointerId);
  state.isDragging = true;
  state.dragStart = { x: event.clientX, y: event.clientY, panX: state.panX, panY: state.panY };
});
imageStage.addEventListener("pointermove", (event) => {
  if (viewer.open && !isCoarsePointer() && !isViewerLocked()) {
    showViewerControls({ autoHide: true });
  }
  if (isViewerLocked() || !state.isDragging || !state.dragStart) {
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
  if (isViewerLocked()) {
    return;
  }
  event.preventDefault();
  setZoom(state.zoom > 1 ? 1 : 2, event.clientX, event.clientY);
});
imageStage.addEventListener("touchstart", (event) => {
  if (isViewerLocked()) {
    return;
  }
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
    if (isViewerLocked()) {
      return;
    }
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
  if (isViewerLocked()) {
    clearEndedTouches(event);
    state.swipeStart = null;
    state.dragStart = null;
    return;
  }
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
      window.setTimeout(() => {
        if (state.lastTapTime === now && viewer.open && !isViewerLocked()) {
          state.lastTapTime = 0;
          toggleViewerControls();
        }
      }, 320);
    }
  }
  clearEndedTouches(event);
  state.swipeStart = null;
  state.dragStart = null;
});
imageStage.addEventListener("touchcancel", clearEndedTouches);
viewer.addEventListener("mousemove", () => {
  if (!viewer.open || isCoarsePointer() || isViewerLocked()) {
    return;
  }
  showViewerControls({ autoHide: true });
});
document.addEventListener("fullscreenchange", () => {
  if (document.fullscreenElement !== viewer) {
    state.viewerRequestedFullscreen = false;
  }
});
document.addEventListener("keydown", (event) => {
  if (state.selectionMode && event.key === "Escape" && !viewer.open) {
    event.preventDefault();
    exitSelectionMode();
    return;
  }
  if (!viewer.open) {
    return;
  }
  const navDirection = viewerKeyboardNavigationDirection(event);
  if (isViewerLocked()) {
    if (navDirection || ["Escape", "Delete"].includes(event.key)) {
      event.preventDefault();
    }
    return;
  }
  if (navDirection) {
    event.preventDefault();
    if (event.repeat) {
      startRapidNavigation(navDirection);
    } else {
      showAdjacentPhoto(navDirection);
    }
  } else if (event.key === "Escape") {
    event.preventDefault();
    closeViewerFromUi();
  } else if (event.key === "Delete" && !event.repeat && !deleteDialog.open) {
    event.preventDefault();
    requestDeleteCurrentPhoto();
  }
});
document.addEventListener("keyup", (event) => {
  if (isViewerLocked()) {
    stopRapidNavigation(false);
    return;
  }
  if (viewerKeyboardNavigationDirection(event)) {
    stopRapidNavigation();
  }
});
window.addEventListener("popstate", () => {
  if (viewer.open && state.viewerHistoryArmed) {
    state.closingViewerFromHistory = true;
    closeViewerAnimated();
    return;
  }
  if (handleGalleryBackNavigation()) {
    return;
  }
});

function bindPageButton(button, direction) {
  button.addEventListener("click", (event) => {
    if (isViewerLocked() || state.rapidNavSuppressClick) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    showAdjacentPhoto(direction);
  });
  button.addEventListener("pointerdown", (event) => {
    if (!viewer.open || button.disabled || isViewerLocked()) {
      return;
    }
    button.setPointerCapture(event.pointerId);
    startRapidNavigation(direction, event.pointerId);
  });
  button.addEventListener("pointerup", (event) => {
    if (state.rapidNavPointerId === event.pointerId) {
      stopRapidNavigation();
    }
  });
  button.addEventListener("pointercancel", (event) => {
    if (state.rapidNavPointerId === event.pointerId) {
      stopRapidNavigation();
    }
  });
  button.addEventListener("pointerleave", (event) => {
    if (event.pointerType !== "touch" && state.rapidNavPointerId === event.pointerId) {
      stopRapidNavigation();
    }
  });
}

function viewerKeyboardNavigationDirection(event) {
  if (event.altKey || event.ctrlKey || event.metaKey) {
    return 0;
  }
  const target = event.target;
  if (target?.closest?.("input, textarea, select, [contenteditable='true']")) {
    return 0;
  }
  if (event.key === "ArrowLeft" || event.key.toLowerCase() === "a") {
    return -1;
  }
  if (event.key === "ArrowRight" || event.key.toLowerCase() === "d") {
    return 1;
  }
  return 0;
}

function clearEndedTouches(event) {
  for (const touch of event.changedTouches) {
    state.activeTouches.delete(touch.identifier);
  }
  if (state.activeTouches.size < 2) {
    state.pinchDistance = 0;
  }
}

function updateScrollTopButton() {
  const pluginDialogOpen = Boolean(document.querySelector("#pluginDialogs dialog[open]"));
  scrollTopBtn.hidden = window.scrollY < 700 || viewer.open || pluginDialogOpen;
}

async function startGallery() {
  await loadConfig();
  await loadPluginAssets();
  await loadFolder("");
  armGalleryHistory();
  await openInitialBracketProject();
  updateScrollTopButton();
}

initializeAuth()
  .then(startGallery)
  .catch((error) => {
    if (error.message === "AUTH_REQUIRED") {
      return;
    }
    emptyState.hidden = false;
    emptyState.textContent = error.message;
  });

function openInitialBracketProject() {
  const params = new URLSearchParams(window.location.search);
  const path = params.get("bracketProject");
  if (path !== null && typeof window.openBracketProject === "function") {
    return window.openBracketProject(path || undefined);
  }
  handleSharedLaunch();
  return null;
}

