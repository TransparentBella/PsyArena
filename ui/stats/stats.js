function qs(id) {
  const el = document.getElementById(id);
  if (!el) throw new Error(`missing element: ${id}`);
  return el;
}

const els = {
  queryInput: qs("queryInput"),
  exportJsonlBtn: qs("exportJsonlBtn"),
  exportCsvBtn: qs("exportCsvBtn"),
  statusText: qs("statusText"),
  grid: qs("grid"),
};

function setStatus(text) {
  els.statusText.textContent = text || "";
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

function openExport(format) {
  window.open(`/api/export?format=${encodeURIComponent(format)}`, "_blank", "noopener,noreferrer");
}

function matchesQuery(item, q) {
  const hay = `${item.match_id} ${item.title || ""} ${item.league || ""} ${item.date || ""}`.toLowerCase();
  return hay.includes(q);
}

function fmtCounts(counts) {
  const a = counts.audio || 0;
  const t = counts.text || 0;
  const b = counts.both || 0;
  const total = counts.total || a + t + b;
  return { a, t, b, total };
}

function makeCountChip(label, value) {
  const chip = document.createElement("span");
  chip.className = "chip";
  chip.textContent = `${label}: ${value}`;
  return chip;
}

function makeCard(item) {
  const card = document.createElement("div");
  card.className = "matchCard";
  card.onclick = () => {
    window.location.href = `/ui/stats/match.html?match_id=${encodeURIComponent(item.match_id)}`;
  };

  const coverUrl = item.cover_url || item.video_url || "";
  const useVideo = coverUrl.endsWith(".mp4") || coverUrl.includes("video");

  if (useVideo) {
    const v = document.createElement("video");
    v.className = "cover";
    v.src = coverUrl;
    v.muted = true;
    v.playsInline = true;
    v.preload = "metadata";
    v.addEventListener("loadedmetadata", () => {
      try {
        v.currentTime = 0.1;
      } catch {}
    });
    card.appendChild(v);
  } else {
    const img = document.createElement("img");
    img.className = "cover";
    img.src = coverUrl;
    card.appendChild(img);
  }

  const body = document.createElement("div");
  body.className = "matchBody";

  const id = document.createElement("div");
  id.className = "matchId";
  id.textContent = item.match_id;
  body.appendChild(id);

  const meta = document.createElement("div");
  meta.className = "muted";
  meta.textContent = [item.title, item.league, item.date].filter(Boolean).join(" · ");
  body.appendChild(meta);

  const counts = document.createElement("div");
  counts.className = "counts";
  const c = fmtCounts(item.counts || {});
  counts.appendChild(makeCountChip("audio", c.a));
  counts.appendChild(makeCountChip("text", c.t));
  counts.appendChild(makeCountChip("both", c.b));
  counts.appendChild(makeCountChip("total", c.total));
  body.appendChild(counts);

  card.appendChild(body);
  return card;
}

let all = [];

function render() {
  els.grid.innerHTML = "";
  const q = (els.queryInput.value || "").trim().toLowerCase();
  const shown = q ? all.filter((m) => matchesQuery(m, q)) : all;
  if (shown.length === 0) {
    setStatus(q ? "无匹配结果" : "暂无数据");
    return;
  }
  setStatus(`共 ${shown.length} 场`);
  for (const m of shown) {
    els.grid.appendChild(makeCard(m));
  }
}

async function load() {
  setStatus("加载中...");
  try {
    const me = await requireAdmin();
    if (!me) return;
    const res = await fetch(`/api/stats/matches`);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const data = await res.json();
    all = (data.matches || []).slice().sort((a, b) => (b.counts?.total || 0) - (a.counts?.total || 0));
    render();
  } catch (e) {
    setStatus(`加载失败: ${e.message || e}`);
  }
}

els.queryInput.addEventListener("input", render);
els.exportJsonlBtn.addEventListener("click", () => openExport("jsonl"));
els.exportCsvBtn.addEventListener("click", () => openExport("csv"));

load();
