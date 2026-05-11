function getStoredThumbMode() {
  const value = window.localStorage.getItem("thumbMode");
  return THUMB_MODES.includes(value) ? value : "medium";
}

function getStoredCompactMode() {
  return window.localStorage.getItem("compactMode") === "1";
}

const THUMB_MODES = ["small", "medium", "large", "xlarge"];
const THUMB_QUEUE_LIMITS = {
  small: 100,
  medium: 70,
  large: 40,
  xlarge: 30,
};

const state = {
  folder: "",
  rootId: "",
  roots: [],
  parent: "",
  entries: [],
  loadingMore: false,
  loadingFolder: false,
  indexing: false,
  currentPhoto: null,
  viewerLiveMode: false,
  viewerControlsVisible: true,
  viewerControlsTimer: null,
  viewerRequestedFullscreen: false,
  lastViewerTapTime: 0,
  deleteInProgress: false,
  zoom: 1,
  panX: 0,
  panY: 0,
  isDragging: false,
  dragStart: null,
  thumbTimers: new Map(),
  thumbQueue: [],
  thumbQueued: new Set(),
  thumbActive: 0,
  thumbControllers: new Map(),
  ratingTimers: new Map(),
  ratingObserver: null,
  ratingQueue: [],
  ratingQueued: new Set(),
  ratingActive: 0,
  filterGeneration: 0,
  filterRefreshTimer: null,
  folderCountRefreshTimer: null,
  previewTimer: null,
  originalCache: new Map(),
  originalCacheBytes: 0,
  originalFetches: new Map(),
  originalControllers: new Map(),
  originalPrefetchQueue: [],
  originalPrefetchActive: 0,
  originalLoadTimer: null,
  viewerGeneration: 0,
  photoInfoController: null,
  photoInfoPath: "",
  rapidNavTimer: null,
  rapidNavStopTimer: null,
  rapidNavDirection: 0,
  rapidNavStarted: false,
  rapidNavSuppressClick: false,
  rapidNavDelay: 0,
  rapidNavPointerId: null,
  thumbObserver: null,
  thumbMode: getStoredThumbMode(),
  compactMode: getStoredCompactMode(),
  activeTouches: new Map(),
  pinchDistance: 0,
  pinchZoom: 1,
  swipeStart: null,
  swipeMoved: false,
  lastTapTime: 0,
  viewerHistoryArmed: false,
  closingViewerFromHistory: false,
  galleryHistoryArmed: false,
  handlingGalleryBack: false,
  visibleScanTimer: null,
  wheelZoomFrame: 0,
  wheelZoomDelta: 0,
  wheelZoomCenter: null,
  contextFolder: null,
  contextEntry: null,
  selectionMode: false,
  selectedPaths: new Set(),
  longPress: null,
  longPressTriggered: false,
  currentBracketResult: null,
  currentBracketProjectPath: null,
  currentBracketMergeResult: null,
  currentBracketFolder: null,
  currentBracketRoot: null,
  uploadPasswordRequired: false,
  enabledPlugins: new Set(),
  pluginAssets: [],
  pluginComponents: [],
  filters: {
    ratings: [],
    dateFrom: "",
    dateTo: "",
  },
};

const ORIGINAL_CACHE_BYTES_LIMIT = 2 * 1024 * 1024 * 1024;
const ORIGINAL_CACHE_COUNT_LIMIT = 200;
const ORIGINAL_PREFETCH_CONCURRENCY = 2;
const ORIGINAL_PREFETCH_QUEUE_LIMIT = 25;
const THUMB_LOAD_CONCURRENCY = 6;
const RATING_STATUS_CONCURRENCY = 3;
const RATING_QUEUE_LIMIT = 50;
const ENTRY_PLACEHOLDER_LIMIT = 10000;

const grid = document.querySelector("#grid");
const emptyState = document.querySelector("#emptyState");
const breadcrumb = document.querySelector("#breadcrumb");
const topbarActions = document.querySelector("#topbarActions");
const openUploadBtn = document.querySelector("#openUploadBtn");
const openSettingsBtn = document.querySelector("#openSettingsBtn");
const backBtn = document.querySelector("#backBtn");
const refreshBtn = document.querySelector("#refreshBtn");
const filterPanel = document.querySelector("#filterPanel");
const filterPanelToggleBtn = document.querySelector("#filterPanelToggleBtn");
const ratingFilterBtn = document.querySelector("#ratingFilterBtn");
const ratingFilterMenu = document.querySelector("#ratingFilterMenu");
const ratingFilterInputs = Array.from(document.querySelectorAll("#ratingFilterMenu input"));
const dateFromFilter = document.querySelector("#dateFromFilter");
const dateToFilter = document.querySelector("#dateToFilter");
const thumbModeSelect = document.querySelector("#thumbModeSelect");
const compactToggleBtn = document.querySelector("#compactToggleBtn");
const clearFiltersBtn = document.querySelector("#clearFiltersBtn");
const scrollTopBtn = document.querySelector("#scrollTopBtn");
const viewer = document.querySelector("#viewer");
const viewerTitle = document.querySelector("#viewerTitle");
const viewerImage = document.querySelector("#viewerImage");
const viewerVideo = document.querySelector("#viewerVideo");
const viewerRatingBtn = document.querySelector("#viewerRatingBtn");
const viewerRatingMenu = document.querySelector("#viewerRatingMenu");
const livePhotoBtn = document.querySelector("#livePhotoBtn");
const infoBtn = document.querySelector("#infoBtn");
const photoInfoPanel = document.querySelector("#photoInfoPanel");
const photoInfoBody = document.querySelector("#photoInfoBody");
const closeInfoBtn = document.querySelector("#closeInfoBtn");
const imageStage = document.querySelector("#imageStage");
const zoomResetBtn = document.querySelector("#zoomResetBtn");
const rotateBtn = document.querySelector("#rotateBtn");
const downloadBtn = document.querySelector("#downloadBtn");
const deleteBtn = document.querySelector("#deleteBtn");
const closeBtn = document.querySelector("#closeBtn");
const prevBtn = document.querySelector("#prevBtn");
const nextBtn = document.querySelector("#nextBtn");
const deleteDialog = document.querySelector("#deleteDialog");
const deleteDialogPath = document.querySelector("#deleteDialogPath");
const cancelDeleteBtn = document.querySelector("#cancelDeleteBtn");
const confirmDeleteBtn = document.querySelector("#confirmDeleteBtn");
const uploadDialog = document.querySelector("#uploadDialog");
const uploadForm = document.querySelector("#uploadForm");
const closeUploadBtn = document.querySelector("#closeUploadBtn");
const uploadRootLabel = document.querySelector("#uploadRootLabel");
const uploadFolderInput = document.querySelector("#uploadFolderInput");
const uploadPasswordLabel = document.querySelector("#uploadPasswordLabel");
const uploadPasswordInput = document.querySelector("#uploadPasswordInput");
const uploadFilesInput = document.querySelector("#uploadFilesInput");
const uploadStatus = document.querySelector("#uploadStatus");
const createUploadFolderBtn = document.querySelector("#createUploadFolderBtn");
const submitUploadBtn = document.querySelector("#submitUploadBtn");
const folderContextMenu = document.querySelector("#folderContextMenu");
const blankContextMenu = document.querySelector("#blankContextMenu");
const itemContextMenu = document.querySelector("#itemContextMenu");
const selectionBar = document.querySelector("#selectionBar");
const selectionCount = document.querySelector("#selectionCount");
const downloadSelectedBtn = document.querySelector("#downloadSelectedBtn");
const copySelectedBtn = document.querySelector("#copySelectedBtn");
const moveSelectedBtn = document.querySelector("#moveSelectedBtn");
const deleteSelectedBtn = document.querySelector("#deleteSelectedBtn");
const exitSelectionBtn = document.querySelector("#exitSelectionBtn");
const pluginDialogs = document.querySelector("#pluginDialogs");
const settingsDialog = document.querySelector("#settingsDialog");
const closeSettingsBtn = document.querySelector("#closeSettingsBtn");
const settingsStatus = document.querySelector("#settingsStatus");
const pluginComponentList = document.querySelector("#pluginComponentList");
const isAppleMobileBrowser = /iPhone|iPad|iPod/i.test(navigator.userAgent);
