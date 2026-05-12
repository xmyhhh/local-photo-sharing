function getStoredThumbMode() {
  const value = window.localStorage.getItem("thumbMode");
  return THUMB_MODES.includes(value) ? value : "medium";
}

function getStoredCompactMode() {
  return window.localStorage.getItem("compactMode") === "1";
}

function getStoredThemeMode() {
  const value = window.localStorage.getItem("themeMode");
  return ["system", "light", "dark"].includes(value) ? value : "system";
}

function getStoredClientPrefetchSettings() {
  try {
    return normalizeClientPrefetchSettings(JSON.parse(window.localStorage.getItem(CLIENT_PREFETCH_STORAGE_KEY) || "{}"));
  } catch {
    return normalizeClientPrefetchSettings({});
  }
}

function normalizeClientPrefetchSettings(value) {
  const settings = value && typeof value === "object" ? value : {};
  return {
    enabled: settings.enabled !== false,
    thumbNeighborRadius: clampClientPrefetchInt(settings.thumbNeighborRadius, 0, 100, DEFAULT_CLIENT_PREFETCH.thumbNeighborRadius),
    originalForward: clampClientPrefetchInt(settings.originalForward, 0, 30, DEFAULT_CLIENT_PREFETCH.originalForward),
    originalBackward: clampClientPrefetchInt(settings.originalBackward, 0, 30, DEFAULT_CLIENT_PREFETCH.originalBackward),
    originalConcurrency: clampClientPrefetchInt(settings.originalConcurrency, 1, 6, DEFAULT_CLIENT_PREFETCH.originalConcurrency),
    originalQueueLimit: clampClientPrefetchInt(settings.originalQueueLimit, 0, 100, DEFAULT_CLIENT_PREFETCH.originalQueueLimit),
  };
}

function clampClientPrefetchInt(value, min, max, fallback) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.max(min, Math.min(max, parsed));
}

const THUMB_MODES = ["small", "medium", "large", "xlarge"];
const THUMB_QUEUE_LIMITS = {
  small: 100,
  medium: 70,
  large: 40,
  xlarge: 30,
};
const CLIENT_PREFETCH_STORAGE_KEY = "clientPrefetchSettings.v1";
const DEFAULT_CLIENT_PREFETCH = {
  enabled: true,
  thumbNeighborRadius: 20,
  originalForward: 5,
  originalBackward: 1,
  originalConcurrency: 2,
  originalQueueLimit: 25,
};

const state = {
  folder: "",
  rootId: "",
  roots: [],
  parent: "",
  entries: [],
  entryByPath: new Map(),
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
  thumbActiveKeys: new Set(),
  thumbActive: 0,
  thumbControllers: new Map(),
  visibleThumbHolders: new Set(),
  thumbPayloads: new Map(),
  thumbNeighborPrefetchTimer: null,
  thumbNeighborPrefetchKey: "",
  ratingTimers: new Map(),
  ratingObserver: null,
  ratingQueue: [],
  ratingQueued: new Set(),
  ratingActive: 0,
  visibleRatingWraps: new Set(),
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
  memoryPrefetchClientId: "",
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
  selectionAnchorPath: "",
  boxSelect: null,
  longPress: null,
  longPressTriggered: false,
  currentBracketResult: null,
  currentBracketProjectPath: null,
  currentBracketMergeResult: null,
  currentBracketFolder: null,
  currentBracketRoot: null,
  timelineViewerOpen: false,
  uploadPasswordRequired: false,
  themeMode: getStoredThemeMode(),
  authEnabled: false,
  authRole: "none",
  authHasPassword: false,
  publicAlbums: [],
  publicAlbumSet: new Set(),
  loginBackgrounds: [],
  loginBackgroundUrls: [],
  loginBackgroundMode: "none",
  loginBackgroundFolder: "",
  loginBackgroundLayout: "grid",
  clientPrefetch: getStoredClientPrefetchSettings(),
  memoryPrefetchWindowBefore: 5,
  memoryPrefetchWindowAfter: 35,
  enabledPlugins: new Set(),
  pluginAssets: [],
  pluginComponents: [],
  warmupPollTimer: null,
  backendTasksPollTimer: null,
  backendTasks: [],
  backendTasksVisibleUntil: 0,
  filters: {
    ratings: [],
    dateFrom: "",
    dateTo: "",
  },
};

const ORIGINAL_CACHE_BYTES_LIMIT = 2 * 1024 * 1024 * 1024;
const ORIGINAL_CACHE_COUNT_LIMIT = 200;
const THUMB_LOAD_CONCURRENCY = 6;
const RATING_STATUS_CONCURRENCY = 3;
const RATING_QUEUE_LIMIT = 50;
const ENTRY_PLACEHOLDER_LIMIT = 10000;

const grid = document.querySelector("#grid");
const emptyState = document.querySelector("#emptyState");
const breadcrumb = document.querySelector("#breadcrumb");
const warmupBanner = document.querySelector("#warmupBanner");
const warmupTitle = document.querySelector("#warmupTitle");
const warmupDetail = document.querySelector("#warmupDetail");
const warmupPercent = document.querySelector("#warmupPercent");
const warmupProgressFill = document.querySelector("#warmupProgressFill");
const backendTasksBtn = document.querySelector("#backendTasksBtn");
const backendTasksBadge = document.querySelector("#backendTasksBadge");
const backendTasksDialog = document.querySelector("#backendTasksDialog");
const closeBackendTasksBtn = document.querySelector("#closeBackendTasksBtn");
const backendTasksSummary = document.querySelector("#backendTasksSummary");
const backendTasksList = document.querySelector("#backendTasksList");
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
const deleteDialogMode = document.querySelector("#deleteDialogMode");
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
const selectionBox = document.querySelector("#selectionBox");
const selectionBar = document.querySelector("#selectionBar");
const selectionCount = document.querySelector("#selectionCount");
const batchRatingControl = document.querySelector("#batchRatingControl");
const batchRatingButtons = Array.from(document.querySelectorAll("[data-batch-rating]"));
const downloadSelectedBtn = document.querySelector("#downloadSelectedBtn");
const copySelectedBtn = document.querySelector("#copySelectedBtn");
const cutSelectedBtn = document.querySelector("#cutSelectedBtn");
const moveSelectedBtn = document.querySelector("#moveSelectedBtn");
const deleteSelectedBtn = document.querySelector("#deleteSelectedBtn");
const invertSelectionBtn = document.querySelector("#invertSelectionBtn");
const exitSelectionBtn = document.querySelector("#exitSelectionBtn");
const pluginDialogs = document.querySelector("#pluginDialogs");
const loginScreen = document.querySelector("#loginScreen");
const loginBackdrop = document.querySelector("#loginBackdrop");
const loginForm = document.querySelector("#loginForm");
const loginPasswordInput = document.querySelector("#loginPasswordInput");
const loginStatus = document.querySelector("#loginStatus");
const guestLoginBtn = document.querySelector("#guestLoginBtn");
const settingsDialog = document.querySelector("#settingsDialog");
const closeSettingsBtn = document.querySelector("#closeSettingsBtn");
const settingsStatus = document.querySelector("#settingsStatus");
const settingsKicker = document.querySelector("#settingsKicker");
const settingsPageTitle = document.querySelector("#settingsPageTitle");
const settingsPageDescription = document.querySelector("#settingsPageDescription");
const pluginSettingsTabs = document.querySelector("#pluginSettingsTabs");
const pluginSettingsPages = document.querySelector("#pluginSettingsPages");
const settingsTabs = () => Array.from(document.querySelectorAll("[data-settings-tab]"));
const generalSettingsPanel = document.querySelector("#generalSettingsPanel");
const authSettingsPanel = document.querySelector("#authSettingsPanel");
const pluginsSettingsPanel = document.querySelector("#pluginsSettingsPanel");
const themeModeSelect = document.querySelector("#themeModeSelect");
const memoryPrefetchEnabledInput = document.querySelector("#memoryPrefetchEnabledInput");
const memoryPrefetchLimitInput = document.querySelector("#memoryPrefetchLimitInput");
const clientPrefetchEnabledInput = document.querySelector("#clientPrefetchEnabledInput");
const clientPrefetchThumbRadiusInput = document.querySelector("#clientPrefetchThumbRadiusInput");
const clientPrefetchOriginalForwardInput = document.querySelector("#clientPrefetchOriginalForwardInput");
const clientPrefetchOriginalBackwardInput = document.querySelector("#clientPrefetchOriginalBackwardInput");
const clientPrefetchOriginalConcurrencyInput = document.querySelector("#clientPrefetchOriginalConcurrencyInput");
const clientPrefetchOriginalQueueLimitInput = document.querySelector("#clientPrefetchOriginalQueueLimitInput");
const authEnabledInput = document.querySelector("#authEnabledInput");
const authPasswordInput = document.querySelector("#authPasswordInput");
const saveAuthPasswordBtn = document.querySelector("#saveAuthPasswordBtn");
const loginBackgroundModeButtons = () => Array.from(document.querySelectorAll("[data-login-background-mode]"));
const loginBackgroundLayoutButtons = () => Array.from(document.querySelectorAll("[data-login-background-layout]"));
const loginBackgroundFolderInput = document.querySelector("#loginBackgroundFolderInput");
const useCurrentLoginBackgroundFolderBtn = document.querySelector("#useCurrentLoginBackgroundFolderBtn");
const pluginComponentList = document.querySelector("#pluginComponentList");
const isAppleMobileBrowser = /iPhone|iPad|iPod/i.test(navigator.userAgent);
