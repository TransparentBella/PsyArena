const API_BASE = "";

const STORAGE = {
  mode: "commentRanking.mode",
  videoHeightVh: "commentRanking.videoHeightVh",
  rankedCompactMode: "commentRanking.rankedCompactMode",
};

window.addEventListener("pageshow", (e) => {
  if (e && e.persisted) window.location.reload();
});

function qs(id) {
  const el = document.getElementById(id);
  if (!el) throw new Error(`missing element: ${id}`);
  return el;
}

function clamp(n, min, max) {
  return Math.max(min, Math.min(max, n));
}

function fmtTimeMs(tMs) {
  const totalSec = Math.max(0, Math.floor((tMs || 0) / 1000));
  const mm = String(Math.floor(totalSec / 60)).padStart(2, "0");
  const ss = String(totalSec % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

async function apiFetch(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!res.ok) {
    const raw = await res.text();
    let detail = raw;
    let parsed = null;
    try {
      parsed = JSON.parse(raw);
      detail = typeof parsed === "string" ? parsed : JSON.stringify(parsed);
    } catch {}
    const err = new Error(`${res.status} ${res.statusText} ${detail}`);
    err.status = res.status;
    if (parsed && typeof parsed === "object" && "detail" in parsed) err.detail = parsed.detail;
    throw err;
  }
  return res;
}

async function getNextTask({ mode }) {
  const url = new URL(`${API_BASE}/api/tasks/next`, window.location.origin);
  if (mode) url.searchParams.set("mode", mode);
  url.searchParams.set("inline_text", "true");
  const res = await apiFetch(url.pathname + url.search);
  return await res.json();
}

async function postJudgment(payload) {
  const res = await apiFetch(`/api/judgments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return await res.json();
}

function exportData() {
  window.open(`/api/export?format=jsonl`, "_blank", "noopener,noreferrer");
}

function browserInfo() {
  return {
    ua: navigator.userAgent,
    platform: navigator.platform,
    language: navigator.language,
    screen: { w: window.screen.width, h: window.screen.height },
  };
}

const state = {
  mode: localStorage.getItem(STORAGE.mode) || "both",
  tasks: [],
  index: -1,
  perTaskState: new Map(),
  activeAudioId: null,
  activeAudioMuted: false,
  activeSyncOffsetMs: 0,
  syncMode: "video_only", // video_only | video_with_commentary | video_muted_tail
  isDragging: false,
  draggingId: null,
  dragFrom: null, // unranked | ranked
  dropZone: null, // unranked | ranked
  dropIndex: null,
  autoScrollListEl: null,
  autoScrollRafId: null,
  pointerClientY: 0,
  rankedCompactMode: true,
  expandedRankedIds: new Set(),
  startedAtMs: null,
  currentUser: null,
};

const VIDEO_HEIGHT_MIN_VH = 28;
const VIDEO_HEIGHT_MAX_VH = 62;
const VIDEO_HEIGHT_MAX_SMALL_VH = 52;
const VIDEO_HEIGHT_DEFAULT_VH = 40;
const EDGE_SCROLL_ZONE_PX = 32;
const EDGE_SCROLL_MIN_PX = 2;
const EDGE_SCROLL_MAX_PX = 18;

const els = {
  modeSelect: qs("modeSelect"),
  modeLabel: qs("modeLabel"),
  reloadBtn: qs("reloadBtn"),
  exportBtn: qs("exportBtn"),
  logoutBtn: qs("logoutBtn"),
  matchMeta: qs("matchMeta"),
  userIdText: qs("userIdText"),
  progressText: qs("progressText"),
  prevBtn: qs("prevBtn"),
  nextBtn: qs("nextBtn"),
  rankedCompactToggle: qs("rankedCompactToggle"),
  videoResizeHandle: qs("videoResizeHandle"),
  statusText: qs("statusText"),
  video: qs("video"),
  unrankedList: qs("unrankedList"),
  rankedList: qs("rankedList"),
  submitBtn: qs("submitBtn"),
  completionOverlay: qs("completionOverlay"),
  completionSubtitle: qs("completionSubtitle"),
  completionDone: qs("completionDone"),
  completionTotal: qs("completionTotal"),
  completionElapsed: qs("completionElapsed"),
  completionExportJsonl: qs("completionExportJsonl"),
  completionExportCsv: qs("completionExportCsv"),
  completionRestart: qs("completionRestart"),
  completionContinue: qs("completionContinue"),
  actionsSection: qs("actionsSection"),
  taskInfoSection: qs("taskInfoSection"),
  navSection: qs("navSection"),
};

function uiReset() {
  els.completionOverlay.hidden = true;
}

uiReset();
document.addEventListener("DOMContentLoaded", uiReset, { once: true });

function setStatus(text) {
  els.statusText.textContent = text || "";
}

function getVideoHeightMaxVh() {
  return window.innerHeight < 750 ? VIDEO_HEIGHT_MAX_SMALL_VH : VIDEO_HEIGHT_MAX_VH;
}

function normalizeVideoHeightVh(raw) {
  const maxVh = getVideoHeightMaxVh();
  const n = Number(raw);
  if (!Number.isFinite(n)) return clamp(VIDEO_HEIGHT_DEFAULT_VH, VIDEO_HEIGHT_MIN_VH, maxVh);
  return clamp(Math.round(n), VIDEO_HEIGHT_MIN_VH, maxVh);
}

function applyVideoHeightVh(vh, { persist = true } = {}) {
  const normalized = normalizeVideoHeightVh(vh);
  document.documentElement.style.setProperty("--video-h", `${normalized}vh`);
  if (persist) localStorage.setItem(STORAGE.videoHeightVh, String(normalized));
}

function fmtElapsed(ms) {
  if (!ms || ms < 0) return "-";
  const sec = Math.floor(ms / 1000);
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  if (m <= 0) return `${s}s`;
  return `${m}m ${s}s`;
}

function doneCount() {
  return state.tasks.filter((t) => (state.perTaskState.get(t.match.match_id) || {}).submitted).length;
}

function initCompactMode() {
  const raw = localStorage.getItem(STORAGE.rankedCompactMode);
  state.rankedCompactMode = raw == null ? true : raw === "1";
  els.rankedCompactToggle.checked = state.rankedCompactMode;
}

function showCompletion({ subtitle }) {
  const done = doneCount();
  const total = done;
  els.completionDone.textContent = String(done);
  els.completionTotal.textContent = String(total);
  const elapsed = state.startedAtMs ? performance.now() - state.startedAtMs : null;
  els.completionElapsed.textContent = fmtElapsed(elapsed);
  els.completionSubtitle.textContent = subtitle || "感谢你的标注贡献";
  els.completionOverlay.hidden = false;
  els.submitBtn.disabled = true;
  els.prevBtn.disabled = true;
  els.nextBtn.disabled = true;
}

function hideCompletion() {
  els.completionOverlay.hidden = true;
  renderLists();
}

function updateSidebar() {
  els.modeSelect.value = state.mode;
  els.userIdText.textContent = state.currentUser ? state.currentUser.nickname : "-";
  const done = doneCount();
  els.progressText.textContent = `${done}/${state.tasks.length}`;

  const task = getCurrentTask();
  if (!task) {
    els.matchMeta.textContent = "未加载";
    els.prevBtn.disabled = true;
    els.nextBtn.disabled = true;
    return;
  }
  const m = task.match;
  const metaParts = [
    m.match_id,
    m.title ? ` ${m.title}` : "",
    m.league ? ` · ${m.league}` : "",
    m.date ? ` · ${m.date}` : "",
  ].join("");
  els.matchMeta.textContent = metaParts.trim();
  els.prevBtn.disabled = state.index <= 0;
  els.nextBtn.disabled = false;
}

function getCurrentTask() {
  if (state.index < 0 || state.index >= state.tasks.length) return null;
  return state.tasks[state.index];
}

function getOrInitTaskState(task) {
  const key = task.match.match_id;
  const existing = state.perTaskState.get(key);
  if (existing) return existing;
  const ids = task.match.commentaries.map((c) => c.commentary_id);
  const init = {
    ranked: [],
    unranked: [...ids],
    submitted: false,
    skipped: false,
  };
  state.perTaskState.set(key, init);
  return init;
}

function getCommentaryById(commentaryId) {
  const task = getCurrentTask();
  if (!task) return null;
  return task.match.commentaries.find((c) => c.commentary_id === commentaryId) || null;
}

function getAudioByCommentaryId(commentaryId) {
  if (!commentaryId) return null;
  return document.querySelector(`audio[data-commentary-id="${CSS.escape(commentaryId)}"]`);
}

function pauseAllCommentaryAudio(exceptCommentaryId = null) {
  const nodes = document.querySelectorAll("audio[data-commentary-id]");
  nodes.forEach((node) => {
    const id = node.getAttribute("data-commentary-id");
    if (!id) return;
    if (exceptCommentaryId && id === exceptCommentaryId) return;
    node.pause();
    node.muted = true;
  });
}

function syncAudioUiState() {
  const cards = document.querySelectorAll(".card");
  cards.forEach((card) => card.classList.remove("card--active"));
  const nodes = document.querySelectorAll("audio[data-commentary-id]");
  nodes.forEach((a) => {
    const id = a.getAttribute("data-commentary-id");
    if (!id) return;
    const isActive = id === state.activeAudioId;
    a.muted = isActive ? state.activeAudioMuted : true;
    const card = a.closest(".card");
    if (card && isActive) card.classList.add("card--active");
  });
}

function syncVideoToActiveAudio() {
  if (!state.activeAudioId) return;
  const audio = getAudioByCommentaryId(state.activeAudioId);
  if (!audio) return;
  const offsetSec = (state.activeSyncOffsetMs || 0) / 1000;
  const targetSec = clamp((audio.currentTime || 0) + offsetSec, 0, Number.MAX_SAFE_INTEGER);
  if (Number.isFinite(targetSec) && Math.abs((els.video.currentTime || 0) - targetSec) > 0.08) {
    els.video.currentTime = targetSec;
  }
}

function setActiveAudio(commentaryId, { restart = false, fromAudioEvent = false } = {}) {
  const commentary = getCommentaryById(commentaryId);
  if (!commentary || !commentary.audio_url) return;
  const audio = getAudioByCommentaryId(commentaryId);
  if (!audio) return;

  const changingTarget = state.activeAudioId !== commentaryId;
  state.activeAudioId = commentaryId;
  state.activeSyncOffsetMs = Number(commentary.sync_offset_ms || 0);
  state.syncMode = "video_with_commentary";
  if (changingTarget) state.activeAudioMuted = false;

  pauseAllCommentaryAudio(commentaryId);

  if (restart) {
    audio.currentTime = 0;
    const offsetSec = Math.max(0, (state.activeSyncOffsetMs || 0) / 1000);
    els.video.currentTime = offsetSec;
  } else {
    syncVideoToActiveAudio();
  }

  els.video.muted = true;
  if (els.video.paused) els.video.play().catch(() => {});
  if (!fromAudioEvent && audio.paused) audio.play().catch(() => {});
  audio.muted = state.activeAudioMuted;
  syncAudioUiState();
}

function resetPlaybackState() {
  pauseAllCommentaryAudio(null);
  state.activeAudioId = null;
  state.activeAudioMuted = false;
  state.activeSyncOffsetMs = 0;
  state.syncMode = "video_only";
  els.video.muted = false;
  syncAudioUiState();
}

function startVideoAutoplay() {
  els.video.muted = false;
  const p = els.video.play();
  if (p && typeof p.catch === "function") {
    p.catch(() => {
      setStatus("自动播放被浏览器阻止，请点击视频控件开始");
    });
  }
}

function seekToMs(tMs) {
  const sec = clamp((tMs || 0) / 1000, 0, Number.MAX_SAFE_INTEGER);
  els.video.currentTime = sec;
  const audio = state.activeAudioId ? getAudioByCommentaryId(state.activeAudioId) : null;
  if (audio) {
    const offsetSec = (state.activeSyncOffsetMs || 0) / 1000;
    audio.currentTime = Math.max(0, sec - offsetSec);
  }
}

function canSubmit(task, st) {
  return st.ranked.length === task.match.commentaries.length && st.ranked.length >= 2;
}

function setVideoSource(task) {
  const url = task.match.video?.url || "";
  resetPlaybackState();
  els.video.src = url;
}

function clearLists() {
  els.unrankedList.innerHTML = "";
  els.rankedList.innerHTML = "";
}

function ensureDropGapEl() {
  let gap = document.getElementById("dropGap");
  if (!gap) {
    gap = document.createElement("div");
    gap.id = "dropGap";
    gap.className = "dropGap";
  }
  return gap;
}

function clearDropFeedback() {
  els.unrankedList.classList.remove("list--drop-active");
  els.rankedList.classList.remove("list--drop-active");
  const gap = document.getElementById("dropGap");
  if (gap && gap.parentElement) gap.parentElement.removeChild(gap);
}

function getRankedCards() {
  return Array.from(els.rankedList.querySelectorAll(".card[data-commentary-id]"));
}

function computeRankedDropIndex(clientY) {
  const cards = getRankedCards();
  if (cards.length === 0) return 0;
  for (let i = 0; i < cards.length; i += 1) {
    const rect = cards[i].getBoundingClientRect();
    if (clientY < rect.top + rect.height / 2) return i;
  }
  return cards.length;
}

function renderRankedDropGap(index) {
  const gap = ensureDropGapEl();
  const cards = getRankedCards();
  const safeIndex = clamp(Number(index || 0), 0, cards.length);
  if (safeIndex >= cards.length) {
    els.rankedList.appendChild(gap);
  } else {
    els.rankedList.insertBefore(gap, cards[safeIndex]);
  }
}

function calcEdgeScrollDelta(listEl, clientY) {
  const rect = listEl.getBoundingClientRect();
  const topTrigger = rect.top + EDGE_SCROLL_ZONE_PX;
  const bottomTrigger = rect.bottom - EDGE_SCROLL_ZONE_PX;
  if (clientY < topTrigger) {
    const ratio = clamp((topTrigger - clientY) / EDGE_SCROLL_ZONE_PX, 0, 1);
    return -(EDGE_SCROLL_MIN_PX + (EDGE_SCROLL_MAX_PX - EDGE_SCROLL_MIN_PX) * ratio);
  }
  if (clientY > bottomTrigger) {
    const ratio = clamp((clientY - bottomTrigger) / EDGE_SCROLL_ZONE_PX, 0, 1);
    return EDGE_SCROLL_MIN_PX + (EDGE_SCROLL_MAX_PX - EDGE_SCROLL_MIN_PX) * ratio;
  }
  return 0;
}

function stopAutoScroll() {
  if (state.autoScrollRafId != null) cancelAnimationFrame(state.autoScrollRafId);
  state.autoScrollRafId = null;
  state.autoScrollListEl = null;
}

function startAutoScroll(listEl) {
  state.autoScrollListEl = listEl;
  if (state.autoScrollRafId != null) return;
  const tick = () => {
    if (!state.isDragging || !state.autoScrollListEl) {
      stopAutoScroll();
      return;
    }
    const targetList = state.autoScrollListEl;
    const delta = calcEdgeScrollDelta(targetList, state.pointerClientY);
    if (delta !== 0) {
      const before = targetList.scrollTop;
      targetList.scrollTop += delta;
      if (targetList === els.rankedList && targetList.scrollTop !== before && state.dropZone === "ranked") {
        state.dropIndex = computeRankedDropIndex(state.pointerClientY);
        renderRankedDropGap(state.dropIndex);
      }
    }
    state.autoScrollRafId = requestAnimationFrame(tick);
  };
  state.autoScrollRafId = requestAnimationFrame(tick);
}

function finishDragSession() {
  stopAutoScroll();
  state.isDragging = false;
  state.draggingId = null;
  state.dragFrom = null;
  state.dropZone = null;
  state.dropIndex = null;
  document.body.classList.remove("isDraggingCard");
  document.querySelectorAll(".card--dragging").forEach((el) => el.classList.remove("card--dragging"));
  clearDropFeedback();
}

function moveCommentary(st, { commentaryId, from, to, index = null }) {
  if (!commentaryId || !from || !to) return;
  if (from === to && to === "unranked") return;
  const rankedBefore = st.ranked.indexOf(commentaryId);
  st.unranked = st.unranked.filter((id) => id !== commentaryId);
  st.ranked = st.ranked.filter((id) => id !== commentaryId);

  if (to === "ranked") {
    let insertAt = typeof index === "number" ? index : st.ranked.length;
    if (from === "ranked" && rankedBefore >= 0 && insertAt > rankedBefore) insertAt -= 1;
    insertAt = clamp(insertAt, 0, st.ranked.length);
    st.ranked.splice(insertAt, 0, commentaryId);
  } else {
    state.expandedRankedIds.delete(commentaryId);
    st.unranked.push(commentaryId);
  }
}

function extractSummaryText(commentary) {
  const fallback = commentary.source || commentary.commentary_id;
  if (!commentary.text) return fallback;
  if (typeof commentary.text === "string") {
    const s = commentary.text.replace(/\s+/g, " ").trim();
    return s.length > 60 ? `${s.slice(0, 60)}...` : s || fallback;
  }
  if (Array.isArray(commentary.text)) {
    const first = commentary.text.find((seg) => seg && typeof seg === "object" && String(seg.text || "").trim() !== "");
    if (!first) return fallback;
    const s = String(first.text || "").replace(/\s+/g, " ").trim();
    return s.length > 60 ? `${s.slice(0, 60)}...` : s || fallback;
  }
  try {
    const s = JSON.stringify(commentary.text).replace(/\s+/g, " ").trim();
    return s.length > 60 ? `${s.slice(0, 60)}...` : s || fallback;
  } catch {
    return fallback;
  }
}

function setupDragDropLists() {
  const onDragOver = (e) => {
    if (!state.draggingId) return;
    const list = e.currentTarget;
    if (!(list instanceof HTMLElement)) return;
    e.preventDefault();
    state.pointerClientY = e.clientY;
    clearDropFeedback();
    list.classList.add("list--drop-active");

    if (list === els.rankedList) {
      state.dropZone = "ranked";
      state.dropIndex = computeRankedDropIndex(e.clientY);
      renderRankedDropGap(state.dropIndex);
    } else {
      state.dropZone = "unranked";
      state.dropIndex = null;
    }
    startAutoScroll(list);
  };

  const onDragLeave = (e) => {
    const list = e.currentTarget;
    if (!(list instanceof HTMLElement)) return;
    const next = e.relatedTarget;
    if (next instanceof Node && list.contains(next)) return;
    list.classList.remove("list--drop-active");
    if (list === els.rankedList) {
      const gap = document.getElementById("dropGap");
      if (gap && gap.parentElement) gap.parentElement.removeChild(gap);
    }
    stopAutoScroll();
  };

  const onDrop = (e) => {
    e.preventDefault();
    const task = getCurrentTask();
    if (!task || !state.draggingId || !state.dragFrom) {
      finishDragSession();
      return;
    }
    const st = getOrInitTaskState(task);
    const targetList = e.currentTarget === els.rankedList ? "ranked" : "unranked";
    const targetIndex = targetList === "ranked" ? state.dropIndex : null;
    moveCommentary(st, {
      commentaryId: state.draggingId,
      from: state.dragFrom,
      to: targetList,
      index: targetIndex,
    });
    finishDragSession();
    renderLists();
  };

  [els.unrankedList, els.rankedList].forEach((list) => {
    list.addEventListener("dragenter", (e) => e.preventDefault());
    list.addEventListener("dragover", onDragOver);
    list.addEventListener("dragleave", onDragLeave);
    list.addEventListener("drop", onDrop);
  });
}

function setupScopedListScroll() {
  const sortSection = els.unrankedList.closest(".sortSection");
  if (!sortSection) return;
  sortSection.addEventListener(
    "wheel",
    (e) => {
      if (state.isDragging) return;
      const target = e.target;
      if (!(target instanceof Element)) return;
      const list = target.closest("#unrankedList, #rankedList");
      if (!list) {
        e.preventDefault();
        return;
      }
      list.scrollTop += e.deltaY;
      e.preventDefault();
    },
    { passive: false }
  );
}

function setupVideoHeightControl() {
  const stored = localStorage.getItem(STORAGE.videoHeightVh);
  applyVideoHeightVh(stored || VIDEO_HEIGHT_DEFAULT_VH, { persist: false });
  window.addEventListener("resize", () => {
    const current = localStorage.getItem(STORAGE.videoHeightVh) || VIDEO_HEIGHT_DEFAULT_VH;
    applyVideoHeightVh(current, { persist: true });
  });
}

function setupVideoResizeHandle() {
  let dragging = false;
  let startY = 0;
  let startVh = VIDEO_HEIGHT_DEFAULT_VH;

  const onMove = (e) => {
    if (!dragging) return;
    const deltaPx = e.clientY - startY;
    const deltaVh = (deltaPx / window.innerHeight) * 100;
    applyVideoHeightVh(startVh + deltaVh, { persist: true });
  };

  const onUp = () => {
    if (!dragging) return;
    dragging = false;
    document.body.classList.remove("isResizing");
    window.removeEventListener("mousemove", onMove);
    window.removeEventListener("mouseup", onUp);
  };

  els.videoResizeHandle.addEventListener("mousedown", (e) => {
    e.preventDefault();
    dragging = true;
    startY = e.clientY;
    const raw = localStorage.getItem(STORAGE.videoHeightVh) || VIDEO_HEIGHT_DEFAULT_VH;
    startVh = normalizeVideoHeightVh(raw);
    document.body.classList.add("isResizing");
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  });
}

function makeCard({ task, st, commentaryId, where }) {
  const commentary = task.match.commentaries.find((c) => c.commentary_id === commentaryId);
  if (!commentary) return document.createElement("div");

  const card = document.createElement("div");
  card.className = "card";
  card.dataset.commentaryId = commentaryId;
  card.setAttribute("draggable", "true");

  const active = state.activeAudioId === commentaryId;
  const compact = where === "ranked" && state.rankedCompactMode;
  const expanded = where === "ranked" && state.expandedRankedIds.has(commentaryId);
  const showCompactSummary = compact && !expanded;
  if (active) card.classList.add("card--active");
  if (compact) card.classList.add("card--compact");

  card.dataset.dragId = commentaryId;

  const header = document.createElement("div");
  header.className = "card__header";

  const left = document.createElement("div");
  left.style.display = "flex";
  left.style.alignItems = "center";
  left.style.gap = "8px";

  const badge = document.createElement("div");
  badge.className = "badge";
  badge.textContent = where === "ranked" ? String(st.ranked.indexOf(commentaryId) + 1) : "·";
  left.appendChild(badge);

  const title = document.createElement("div");
  title.textContent = commentary.source || commentary.commentary_id;
  left.appendChild(title);
  header.appendChild(left);

  const controls = document.createElement("div");
  controls.className = "card__controls";

  if (where === "unranked") {
    const addBtn = document.createElement("button");
    addBtn.className = "btnSmall";
    addBtn.textContent = "加入排序";
    addBtn.onclick = () => {
      st.unranked = st.unranked.filter((id) => id !== commentaryId);
      st.ranked = [...st.ranked, commentaryId];
      renderLists();
    };
    controls.appendChild(addBtn);
  } else {
    const rmBtn = document.createElement("button");
    rmBtn.className = "btnSmall btnSmall--danger";
    rmBtn.textContent = "移出";
    rmBtn.onclick = () => {
      st.ranked = st.ranked.filter((id) => id !== commentaryId);
      st.unranked = [...st.unranked, commentaryId];
      if (state.activeAudioId === commentaryId) state.activeAudioId = null;
      renderLists();
    };
    controls.appendChild(rmBtn);

    const upBtn = document.createElement("button");
    upBtn.className = "btnSmall";
    upBtn.textContent = "上移";
    upBtn.onclick = () => {
      const idx = st.ranked.indexOf(commentaryId);
      if (idx <= 0) return;
      const next = [...st.ranked];
      [next[idx - 1], next[idx]] = [next[idx], next[idx - 1]];
      st.ranked = next;
      renderLists();
    };
    controls.appendChild(upBtn);

    const downBtn = document.createElement("button");
    downBtn.className = "btnSmall";
    downBtn.textContent = "下移";
    downBtn.onclick = () => {
      const idx = st.ranked.indexOf(commentaryId);
      if (idx < 0 || idx >= st.ranked.length - 1) return;
      const next = [...st.ranked];
      [next[idx], next[idx + 1]] = [next[idx + 1], next[idx]];
      st.ranked = next;
      renderLists();
    };
    controls.appendChild(downBtn);
  }

  header.appendChild(controls);
  card.appendChild(header);

  const meta = document.createElement("div");
  meta.className = "card__meta";
  const chipType = document.createElement("span");
  chipType.className = "chip";
  chipType.textContent = commentary.type;
  meta.appendChild(chipType);
  if (commentary.language) {
    const chipLang = document.createElement("span");
    chipLang.className = "chip";
    chipLang.textContent = commentary.language;
    meta.appendChild(chipLang);
  }
  const chipId = document.createElement("span");
  chipId.className = "chip";
  chipId.textContent = commentary.commentary_id;
  meta.appendChild(chipId);
  card.appendChild(meta);

  if (commentary.audio_url) {
    const audio = document.createElement("audio");
    audio.controls = true;
    audio.src = commentary.audio_url;
    audio.preload = "metadata";
    audio.dataset.commentaryId = commentary.commentary_id;
    audio.muted = state.activeAudioId === commentary.commentary_id ? state.activeAudioMuted : true;
    audio.addEventListener("play", () => {
      setActiveAudio(commentary.commentary_id, { restart: false, fromAudioEvent: true });
    });
    audio.addEventListener("seeking", () => {
      if (state.activeAudioId !== commentary.commentary_id) return;
      syncVideoToActiveAudio();
    });
    audio.addEventListener("seeked", () => {
      if (state.activeAudioId !== commentary.commentary_id) return;
      syncVideoToActiveAudio();
    });
    audio.addEventListener("timeupdate", () => {
      if (state.activeAudioId !== commentary.commentary_id || audio.paused) return;
      syncVideoToActiveAudio();
    });
    audio.addEventListener("pause", () => {
      if (state.activeAudioId !== commentary.commentary_id || audio.ended) return;
      if (!els.video.paused) els.video.pause();
    });
    audio.addEventListener("ended", () => {
      if (state.activeAudioId !== commentary.commentary_id) return;
      state.syncMode = "video_muted_tail";
      els.video.muted = true;
      if (els.video.paused) els.video.play().catch(() => {});
      syncAudioUiState();
    });
    card.appendChild(audio);
  } else {
    const noAudio = document.createElement("div");
    noAudio.className = "dragHint";
    noAudio.textContent = "无音频，仅展示文本";
    card.appendChild(noAudio);
  }

  if (commentary.text) {
    if (showCompactSummary) {
      const summary = document.createElement("button");
      summary.className = "textSummary";
      summary.type = "button";
      summary.textContent = extractSummaryText(commentary);
      summary.title = "点击展开详情";
      summary.onclick = (e) => {
        e.stopPropagation();
        state.expandedRankedIds.add(commentaryId);
        renderLists();
      };
      card.appendChild(summary);
    } else {
      const box = document.createElement("div");
      box.className = "textBox";

      if (Array.isArray(commentary.text)) {
        const segWrap = document.createElement("div");
        segWrap.className = "segments";
        for (const seg of commentary.text) {
          if (!seg || typeof seg !== "object") continue;
          const tMs = seg.t_ms ?? seg.t ?? seg.time_ms ?? 0;
          const text = seg.text ?? "";
          const segEl = document.createElement("div");
          segEl.className = "seg";
          segEl.onclick = () => {
            if (commentary.audio_url) setActiveAudio(commentary.commentary_id);
            seekToMs(Number(tMs) || 0);
          };
          const timeEl = document.createElement("div");
          timeEl.className = "seg__time";
          timeEl.textContent = fmtTimeMs(Number(tMs) || 0);
          const textEl = document.createElement("div");
          textEl.textContent = String(text);
          segEl.appendChild(timeEl);
          segEl.appendChild(textEl);
          segWrap.appendChild(segEl);
        }
        box.appendChild(segWrap);
      } else if (typeof commentary.text === "object") {
        box.textContent = JSON.stringify(commentary.text, null, 2);
      } else {
        box.textContent = String(commentary.text);
      }
      card.appendChild(box);

      if (compact && expanded) {
        const collapse = document.createElement("button");
        collapse.className = "btnSmall";
        collapse.type = "button";
        collapse.textContent = "收起";
        collapse.onclick = (e) => {
          e.stopPropagation();
          state.expandedRankedIds.delete(commentaryId);
          renderLists();
        };
        card.appendChild(collapse);
      }
    }
  } else if (commentary.text_url) {
    const hint = document.createElement("div");
    hint.className = "dragHint";
    hint.textContent = `文本未内联，可打开：${commentary.text_url}`;
    card.appendChild(hint);
  }

  card.addEventListener("dragstart", (e) => {
    state.isDragging = true;
    state.draggingId = commentaryId;
    state.dragFrom = where;
    state.dropZone = null;
    state.dropIndex = null;
    card.classList.add("card--dragging");
    document.body.classList.add("isDraggingCard");
    e.dataTransfer.setData("text/plain", commentaryId);
    e.dataTransfer.effectAllowed = "move";
  });
  card.addEventListener("dragend", () => {
    finishDragSession();
  });

  return card;
}

function renderLists() {
  clearDropFeedback();
  const task = getCurrentTask();
  if (!task) {
    clearLists();
    els.submitBtn.disabled = true;
    return;
  }

  const st = getOrInitTaskState(task);
  updateSidebar();

  clearLists();
  for (const id of st.unranked) {
    els.unrankedList.appendChild(makeCard({ task, st, commentaryId: id, where: "unranked" }));
  }
  for (const id of st.ranked) {
    els.rankedList.appendChild(makeCard({ task, st, commentaryId: id, where: "ranked" }));
  }

  syncAudioUiState();
  els.submitBtn.disabled = !canSubmit(task, st) || st.submitted;
}

async function loadFirstTask() {
  hideCompletion();
  setStatus("加载任务中…");
  try {
    const task = await getNextTask({ mode: state.mode });
    state.tasks = [task];
    state.index = 0;
    state.startedAtMs = performance.now();
    setVideoSource(task);
    setStatus("");
    renderLists();
    startVideoAutoplay();
  } catch (e) {
    if (e && e.status === 404 && (e.detail === "no_tasks" || String(e.message || "").includes("no_tasks"))) {
      window.location.href = "/ui/user/";
      return;
    }
    setStatus(String(e.message || e));
    state.tasks = [];
    state.index = -1;
    renderLists();
  }
}

async function checkAuth() {
  try {
    const res = await fetch(`/api/auth/me`);
    if (res.status === 401) {
      window.location.href = "/ui/login/";
      return null;
    }
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const me = await res.json();
    state.currentUser = me;
    const isAdmin = me.role === "admin";
    const statsLink = document.getElementById("statsLink");
    if (statsLink) statsLink.style.display = isAdmin ? "inline-flex" : "none";
    els.exportBtn.style.display = isAdmin ? "inline-flex" : "none";
    els.completionExportJsonl.style.display = isAdmin ? "inline-flex" : "none";
    els.completionExportCsv.style.display = isAdmin ? "inline-flex" : "none";
    if (!isAdmin) {
      // labeler sidebar should only keep logout
      els.modeLabel.hidden = true;
      els.modeSelect.hidden = true;
      els.reloadBtn.style.display = "none";
      if (statsLink) statsLink.style.display = "none";
      els.taskInfoSection.hidden = true;
      els.navSection.hidden = true;
    }
    if (isAdmin) {
      window.location.href = "/ui/stats/";
      return null;
    }
    if (me.needs_password_reset) {
      window.location.href = "/ui/login/?reset=1";
      return null;
    }
    updateSidebar();
    return me;
  } catch (e) {
    setStatus(`鉴权失败: ${e.message || e}`);
    return null;
  }
}

async function gotoNextTask({ allowSkipSubmit }) {
  const cur = getCurrentTask();
  if (!cur) return;
  const st = getOrInitTaskState(cur);

  if (allowSkipSubmit && !st.submitted) {
    const fullOrder = [...st.ranked, ...st.unranked];
    if (fullOrder.length >= 2) {
      try {
        await postJudgment({
          match_id: cur.match.match_id,
          commentary_ids: fullOrder,
          mode: state.mode,
          latency_ms: null,
          reason: null,
          flags: { skipped: true, browser_info: browserInfo() },
        });
        st.submitted = true;
        st.skipped = true;
      } catch {
      }
    }
  }

  if (state.index < state.tasks.length - 1) {
    state.index += 1;
    const task = getCurrentTask();
    setVideoSource(task);
    renderLists();
    startVideoAutoplay();
    return;
  }

  setStatus("加载下一条…");
  try {
    const next = await getNextTask({ mode: state.mode });
    state.tasks.push(next);
    state.index = state.tasks.length - 1;
    setVideoSource(next);
    setStatus("");
    renderLists();
    startVideoAutoplay();
  } catch (e) {
    if (e && e.status === 404 && (e.detail === "no_tasks" || String(e.message || "").includes("no_tasks"))) {
      window.location.href = "/ui/user/";
      return;
    }
    setStatus(String(e.message || e));
  }
}

function gotoPrevTask() {
  if (state.index <= 0) return;
  state.index -= 1;
  const task = getCurrentTask();
  setVideoSource(task);
  renderLists();
  startVideoAutoplay();
}

async function submitCurrent() {
  const task = getCurrentTask();
  if (!task) return;
  const st = getOrInitTaskState(task);
  if (!canSubmit(task, st) || st.submitted) return;

  setStatus("提交中…");
  const startedAt = performance.now();
  try {
    await postJudgment({
      match_id: task.match.match_id,
      commentary_ids: [...st.ranked],
      mode: state.mode,
      latency_ms: Math.floor(performance.now() - startedAt),
      reason: null,
      flags: { browser_info: browserInfo() },
    });
    st.submitted = true;
    setStatus("");
    renderLists();
    await gotoNextTask({ allowSkipSubmit: false });
  } catch (e) {
    setStatus(String(e.message || e));
  }
}

function wireEvents() {
  setupScopedListScroll();
  setupDragDropLists();
  setupVideoHeightControl();
  setupVideoResizeHandle();
  els.modeSelect.value = state.mode;
  els.modeSelect.addEventListener("change", async () => {
    state.mode = els.modeSelect.value;
    localStorage.setItem(STORAGE.mode, state.mode);
    state.tasks = [];
    state.index = -1;
    state.perTaskState.clear();
    state.expandedRankedIds.clear();
    resetPlaybackState();
    await loadFirstTask();
  });
  els.rankedCompactToggle.addEventListener("change", () => {
    state.rankedCompactMode = !!els.rankedCompactToggle.checked;
    localStorage.setItem(STORAGE.rankedCompactMode, state.rankedCompactMode ? "1" : "0");
    if (!state.rankedCompactMode) state.expandedRankedIds.clear();
    renderLists();
  });

  els.reloadBtn.addEventListener("click", loadFirstTask);
  els.exportBtn.addEventListener("click", exportData);
  els.logoutBtn.addEventListener("click", () => {
    fetch("/api/auth/logout", { method: "POST" }).finally(() => {
      window.location.href = "/ui/login/";
    });
  });
  els.prevBtn.addEventListener("click", gotoPrevTask);
  els.nextBtn.addEventListener("click", () => gotoNextTask({ allowSkipSubmit: true }));
  els.submitBtn.addEventListener("click", submitCurrent);

  els.completionExportJsonl.addEventListener("click", () => exportData());
  els.completionExportCsv.addEventListener("click", () => {
    window.open(`/api/export?format=csv`, "_blank", "noopener,noreferrer");
  });
  els.completionRestart.addEventListener("click", () => {
    localStorage.removeItem(STORAGE.mode);
    state.mode = "both";
    state.tasks = [];
    state.index = -1;
    state.perTaskState.clear();
    state.expandedRankedIds.clear();
    resetPlaybackState();
    state.startedAtMs = null;
    hideCompletion();
    loadFirstTask();
  });
  els.completionContinue.addEventListener("click", () => {
    hideCompletion();
    loadFirstTask();
  });
}

wireEvents();
initCompactMode();
updateSidebar();
checkAuth().then((me) => {
  if (me) loadFirstTask();
});
