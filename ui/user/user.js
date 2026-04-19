function qs(id) {
  const el = document.getElementById(id);
  if (!el) throw new Error(`missing element: ${id}`);
  return el;
}

const els = {
  statusText: qs("statusText"),
  pendingCount: qs("pendingCount"),
  summaryText: qs("summaryText"),
  manifestAt: qs("manifestAt"),
  lastSeenAt: qs("lastSeenAt"),
  goLabelBtn: qs("goLabelBtn"),
  logoutBtn: qs("logoutBtn"),
};

function setStatus(text) {
  els.statusText.textContent = text || "";
}

async function fetchJson(url, options) {
  const res = await fetch(url, options);
  const raw = await res.text();
  let data = null;
  try {
    data = JSON.parse(raw);
  } catch {}
  if (!res.ok) {
    const msg = (data && data.detail) || raw || `${res.status} ${res.statusText}`;
    const err = new Error(msg);
    err.status = res.status;
    err.detail = data && data.detail;
    throw err;
  }
  return data;
}

async function requireUser() {
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
  if (me.role === "admin") {
    window.location.href = "/ui/stats/";
    return null;
  }
  return me;
}

function renderInbox(data) {
  const pending = Number(data.pending_count || 0);
  els.pendingCount.textContent = String(pending);
  els.manifestAt.textContent = data.last_manifest_updated_at || "-";
  els.lastSeenAt.textContent = data.last_seen_at || "-";
  const newN = Number(data.new_since_last_seen || 0);
  if (newN > 0 && data.last_manifest_updated_at) {
    els.summaryText.textContent = `${data.last_manifest_updated_at} 新增了 ${newN} 条待标注数据`;
  } else if (pending > 0) {
    els.summaryText.textContent = `当前有 ${pending} 条待标注数据`;
  } else {
    els.summaryText.textContent = "当前没有新的待标注任务";
  }
  els.goLabelBtn.disabled = pending <= 0;
}

async function refresh() {
  setStatus("加载中…");
  try {
    const me = await requireUser();
    if (!me) return;
    const inbox = await fetchJson("/api/user/inbox");
    renderInbox(inbox);
    setStatus("");
    fetchJson("/api/user/inbox/seen", { method: "POST" }).catch(() => {});
  } catch (e) {
    setStatus(`加载失败: ${e.message || e}`);
  }
}

els.goLabelBtn.addEventListener("click", () => {
  window.location.href = "/ui/";
});
els.logoutBtn.addEventListener("click", () => {
  fetch("/api/auth/logout", { method: "POST" }).finally(() => {
    window.location.href = "/ui/login/";
  });
});

refresh();
