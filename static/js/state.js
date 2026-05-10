function getStoredThumbMode() {
  const value = window.localStorage.getItem("thumbMode");
  return ["small", "medium", "large"].includes(value) ? value : "medium";
}

const state = {
  folder: "",
  parent: "",
  entries: [],
  nextCursor: null,
  loadingMore: false,
  indexing: false,
  currentPhoto: null,
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
  previewTimer: null,
  originalCache: new Map(),
  originalCacheBytes: 0,
  originalFetches: new Map(),
  originalPrefetchQueue: [],
  originalPrefetchActive: 0,
  thumbObserver: null,
  thumbMode: getStoredThumbMode(),
  activeTouches: new Map(),
  pinchDistance: 0,
  pinchZoom: 1,
  swipeStart: null,
  swipeMoved: false,
  lastTapTime: 0,
  visibleScanTimer: null,
  wheelZoomFrame: 0,
  wheelZoomDelta: 0,
  wheelZoomCenter: null,
  contextFolder: null,
  filters: {
    ratings: [],
    dateFrom: "",
    dateTo: "",
  },
};

const ORIGINAL_CACHE_LIMIT = 1024 * 1024 * 1024;
const ORIGINAL_PREFETCH_CONCURRENCY = 2;
const ORIGINAL_PREFETCH_QUEUE_LIMIT = 25;
const THUMB_LOAD_CONCURRENCY = 6;
const THUMB_QUEUE_LIMIT = 50;
const RATING_STATUS_CONCURRENCY = 3;
const RATING_QUEUE_LIMIT = 50;

const grid = document.querySelector("#grid");
const emptyState = document.querySelector("#emptyState");
const breadcrumb = document.querySelector("#breadcrumb");
const rootPath = document.querySelector("#rootPath");
const backBtn = document.querySelector("#backBtn");
const refreshBtn = document.querySelector("#refreshBtn");
const ratingFilterBtn = document.querySelector("#ratingFilterBtn");
const ratingFilterMenu = document.querySelector("#ratingFilterMenu");
const ratingFilterInputs = Array.from(document.querySelectorAll("#ratingFilterMenu input"));
const dateFromFilter = document.querySelector("#dateFromFilter");
const dateToFilter = document.querySelector("#dateToFilter");
const thumbModeSelect = document.querySelector("#thumbModeSelect");
const clearFiltersBtn = document.querySelector("#clearFiltersBtn");
const viewer = document.querySelector("#viewer");
const viewerTitle = document.querySelector("#viewerTitle");
const viewerImage = document.querySelector("#viewerImage");
const viewerRating = document.querySelector("#viewerRating");
const imageStage = document.querySelector("#imageStage");
const zoomOutBtn = document.querySelector("#zoomOutBtn");
const zoomResetBtn = document.querySelector("#zoomResetBtn");
const zoomInBtn = document.querySelector("#zoomInBtn");
const downloadBtn = document.querySelector("#downloadBtn");
const deleteBtn = document.querySelector("#deleteBtn");
const closeBtn = document.querySelector("#closeBtn");
const prevBtn = document.querySelector("#prevBtn");
const nextBtn = document.querySelector("#nextBtn");
const deleteDialog = document.querySelector("#deleteDialog");
const deleteDialogPath = document.querySelector("#deleteDialogPath");
const cancelDeleteBtn = document.querySelector("#cancelDeleteBtn");
const confirmDeleteBtn = document.querySelector("#confirmDeleteBtn");
const folderContextMenu = document.querySelector("#folderContextMenu");
const detectBracketsBtn = document.querySelector("#detectBracketsBtn");
const bracketDialog = document.querySelector("#bracketDialog");
const bracketDialogPath = document.querySelector("#bracketDialogPath");
const bracketStatus = document.querySelector("#bracketStatus");
const bracketResults = document.querySelector("#bracketResults");
const closeBracketDialogBtn = document.querySelector("#closeBracketDialogBtn");
const isAppleMobileBrowser = /iPhone|iPad|iPod/i.test(navigator.userAgent);
