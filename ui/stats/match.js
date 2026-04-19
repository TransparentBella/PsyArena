function qs(id) {
  const el = document.getElementById(id);
  if (!el) throw new Error(`missing element: ${id}`);
  return el;
}

function qsa(sel) {
  return Array.from(document.querySelectorAll(sel));
}

function getParam(name) {
  return new URLSearchParams(window.location.search).get(name);
}

function setText(el, text) {
  el.textContent = text || "";
}

function fmtPct(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "-";
  return `${n.toFixed(1)}%`;
}

function fmtNum(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "-";
  return `${n.toFixed(2)}`;
}

function rankingFlow(j) {
  const parts = (j.ranking || []).map((x) => `${x.rank}. ${x.source || x.id}`);
  return parts.join(" → ");
}

const els = {
  metaText: qs("metaText"),
  exportJsonlBtn: qs("exportJsonlBtn"),
  exportCsvBtn: qs("exportCsvBtn"),
  video: qs("video"),
  statsTable: qs("statsTable"),
  list: qs("list"),
  statusText: qs("statusText"),
  previewBtn: qs("previewBtn"),
  previewBox: qs("previewBox"),
};

const matchId = getParam("match_id");
if (!matchId) {
  setText(els.statusText, "缺少 match_id 参数");
}

let data = null;
let activeTab = "audio";

function setStatus(text) {
  setText(els.statusText, text);
}

async function requireAdmin() {
  const res = await fetch("/api/auth/me");
  if (res.status === 401) {
    window.location.href = "/ui/login/";
    return null;
  }
  const me = await res.json();
  if (me.needs_password_reset) {
    window.location.href = "/ui/login/?reset=1";
    return null;
  }
  if (me.role !== "admin") {
    window.location.href = "/ui/";
    return null;
  }
  return me;
}

function setActiveTab(tab) {
  activeTab = tab;
  for (const b of qsa(".tabBtn")) {
    b.classList.toggle("tabBtn--active", b.dataset.tab === tab);
  }
  renderJudgments();
  renderStats();
}

function renderStats() {
  if (!data) return;
  const rows = data.win_stats_by_mode?.[activeTab] || [];
  els.statsTable.innerHTML = "";
  if (!rows.length) {
    const empty = document.createElement("div");
    empty.className = "muted";
    empty.textContent = "暂无统计（还没有标注数据）";
    els.statsTable.appendChild(empty);
    return;
  }
  const header = document.createElement("div");
  header.className = "statsRow muted";
  header.innerHTML = "<div>解说源</div><div>第一名占比</div><div>平均名次</div><div>两两胜率</div>";
  els.statsTable.appendChild(header);

  for (const r of rows) {
    const row = document.createElement("div");
    row.className = "statsRow";
    const name = r.source || r.id;
    row.innerHTML = `<div>${name}</div><div>${fmtPct(r.top1_pct)}</div><div>${fmtNum(r.avg_rank)}</div><div>${fmtPct((r.pairwise_win_rate ?? 0) * 100)}</div>`;
    els.statsTable.appendChild(row);
  }
}

function renderJudgments() {
  if (!data) return;
  const list = data.by_mode?.[activeTab] || [];
  els.list.innerHTML = "";
  if (!list.length) {
    const empty = document.createElement("div");
    empty.className = "muted";
    empty.textContent = "暂无标注数据";
    els.list.appendChild(empty);
    return;
  }

  for (const j of list) {
    const item = document.createElement("div");
    item.className = "judgmentItem";

    const meta = document.createElement("div");
    meta.className = "judgmentMeta";
    meta.innerHTML = `<span class="chip">编号: ${j.judgment_id}</span><span class="chip">${j.created_at}</span><span class="chip">用户: ${j.user_id}</span>`;
    item.appendChild(meta);

    const flow = document.createElement("div");
    flow.className = "rankingFlow";
    flow.textContent = rankingFlow(j);
    item.appendChild(flow);

    const ids = document.createElement("div");
    ids.className = "muted";
    ids.style.marginTop = "6px";
    ids.textContent = (j.ranking_ids || []).join(" > ");
    item.appendChild(ids);

    els.list.appendChild(item);
  }
}

async function loadPreview() {
  if (!matchId) return;
  setText(els.previewBox, "加载中...");
  try {
    const me = await requireAdmin();
    if (!me) return;
    const res = await fetch(`/api/export?format=jsonl&match_id=${encodeURIComponent(matchId)}&limit=50`);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const text = await res.text();
    setText(els.previewBox, text.trim() || "(empty)");
  } catch (e) {
    setText(els.previewBox, `预览失败: ${e.message || e}`);
  }
}

async function loadDetail() {
  if (!matchId) return;
  setStatus("加载中...");
  try {
    const me = await requireAdmin();
    if (!me) return;
    const res = await fetch(`/api/stats/match?match_id=${encodeURIComponent(matchId)}`);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    data = await res.json();
    const m = data.match;
    const meta = [m.match_id, m.title, m.league, m.date].filter(Boolean).join(" · ");
    setText(els.metaText, meta);
    if (m.video_url) els.video.src = m.video_url;
    setStatus("");
    setActiveTab(activeTab);
    loadPreview();
  } catch (e) {
    setStatus(`加载失败: ${e.message || e}`);
  }
}

function wire() {
  for (const b of qsa(".tabBtn")) {
    b.addEventListener("click", () => setActiveTab(b.dataset.tab));
  }
  els.previewBtn.addEventListener("click", loadPreview);
  els.exportJsonlBtn.addEventListener("click", () => {
    window.open(`/api/export?format=jsonl&match_id=${encodeURIComponent(matchId)}`, "_blank", "noopener,noreferrer");
  });
  els.exportCsvBtn.addEventListener("click", () => {
    window.open(`/api/export?format=csv&match_id=${encodeURIComponent(matchId)}`, "_blank", "noopener,noreferrer");
  });
}

wire();
setActiveTab(activeTab);
loadDetail();
