function distanceBetweenTouches() {
  const touches = Array.from(state.activeTouches.values());
  if (touches.length < 2) {
    return 0;
  }
  const [first, second] = touches;
  return Math.hypot(first.x - second.x, first.y - second.y);
}

function midpointBetweenTouches() {
  const touches = Array.from(state.activeTouches.values());
  if (touches.length < 2) {
    return { x: 0, y: 0 };
  }
  const [first, second] = touches;
  return { x: (first.x + second.x) / 2, y: (first.y + second.y) / 2 };
}

function clampPan() {
  if (state.zoom <= 1) {
    state.panX = 0;
    state.panY = 0;
    return;
  }
  const maxX = (imageStage.clientWidth * (state.zoom - 1)) / 2;
  const maxY = (imageStage.clientHeight * (state.zoom - 1)) / 2;
  state.panX = Math.max(-maxX, Math.min(maxX, state.panX));
  state.panY = Math.max(-maxY, Math.min(maxY, state.panY));
}

function setZoom(nextZoom, centerX = imageStage.clientWidth / 2, centerY = imageStage.clientHeight / 2) {
  const previousZoom = state.zoom;
  state.zoom = Math.max(1, Math.min(6, nextZoom));
  if (state.zoom === 1) {
    state.panX = 0;
    state.panY = 0;
  } else if (previousZoom !== state.zoom) {
    const rect = imageStage.getBoundingClientRect();
    const dx = centerX - rect.left - rect.width / 2;
    const dy = centerY - rect.top - rect.height / 2;
    const scale = state.zoom / previousZoom;
    state.panX = state.panX * scale - dx * (scale - 1);
    state.panY = state.panY * scale - dy * (scale - 1);
    clampPan();
  }
  updateZoom();
}


