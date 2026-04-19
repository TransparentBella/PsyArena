function qs(id) {
  const el = document.getElementById(id);
  if (!el) throw new Error(`missing element: ${id}`);
  return el;
}

const els = {
  statusText: qs("statusText"),
  pendingList: qs("pendingList"),
  msgStatus: qs("msgStatus"),
  messageList: qs("messageList"),
};

function setStatus(text) {
  els.statusText.textContent = text || "";
}

function setMsgStatus(text) {
  els.msgStatus.textContent = text || "";
}

async function requireAdmin() {
  const res = await fetch("/api/auth/me");
  if (res.status === 401) {
    window.location.href = "/ui/login/";
    return null;
  }
  const me = await res.json();
  if (me.role !== "admin") {
    window.location.href = "/ui/";
    return null;
  }
  if (me.needs_password_reset) {
    window.location.href = "/ui/login/?reset=1";
    return null;
  }
  return me;
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
    throw err;
  }
  return data;
}

function makeItem(u) {
  const div = document.createElement("div");
  div.className = "judgmentItem";

  const meta = document.createElement("div");
  meta.className = "judgmentMeta";
  meta.innerHTML = `<span class="chip">${u.username}</span><span class="chip">${u.created_at}</span>`;
  div.appendChild(meta);

  const name = document.createElement("div");
  name.className = "rankingFlow";
  name.textContent = `昵称: ${u.nickname}`;
  div.appendChild(name);

  const actions = document.createElement("div");
  actions.style.display = "flex";
  actions.style.gap = "10px";
  actions.style.marginTop = "10px";

  const approve = document.createElement("button");
  approve.className = "btnSmall";
  approve.textContent = "通过";
  approve.onclick = async () => {
    try {
      await fetchJson("/api/admin/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: u.username }),
      });
      div.remove();
      loadPending();
      pollMessages();
    } catch (e) {
      if (e.status === 409) {
        setStatus("该申请已被处理");
        div.remove();
        loadPending();
        pollMessages();
        return;
      }
      setStatus(`操作失败: ${e.message || e}`);
    }
  };
  actions.appendChild(approve);

  const reject = document.createElement("button");
  reject.className = "btnSmall btnSmall--danger";
  reject.textContent = "拒绝";
  reject.onclick = async () => {
    const reason = prompt("拒绝原因（可空）", "");
    try {
      await fetchJson("/api/admin/reject", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: u.username, reason: reason || null }),
      });
      div.remove();
      loadPending();
      pollMessages();
    } catch (e) {
      if (e.status === 409) {
        setStatus("该申请已被处理");
        div.remove();
        loadPending();
        pollMessages();
        return;
      }
      setStatus(`操作失败: ${e.message || e}`);
    }
  };
  actions.appendChild(reject);

  div.appendChild(actions);
  return div;
}

let lastMessageId = 0;

function actionText(action) {
  if (action === "approve_user") return "同意";
  if (action === "reject_user") return "驳回";
  return action;
}

function makeMessageItem(m) {
  const div = document.createElement("div");
  div.className = "judgmentItem";
  const meta = document.createElement("div");
  meta.className = "judgmentMeta";
  const actor = m.actor_username || "-";
  const target = m.target || "-";
  meta.innerHTML = `<span class="chip">#${m.id}</span><span class="chip">${m.created_at}</span><span class="chip">${actor}</span>`;
  div.appendChild(meta);

  const text = document.createElement("div");
  text.className = "rankingFlow";
  const extra = m.meta && m.meta.reason ? `（原因：${m.meta.reason}）` : "";
  const nick = m.meta && m.meta.nickname ? String(m.meta.nickname) : null;
  const label = nick && nick !== target ? `${nick} (${target})` : nick || target;
  text.textContent = `${actor} 处理了 ${label} 的注册申请：${actionText(m.action)}${extra}`;
  div.appendChild(text);
  return div;
}

async function loadPending() {
  setStatus("加载中…");
  els.pendingList.innerHTML = "";
  try {
    const me = await requireAdmin();
    if (!me) return;
    const data = await fetchJson("/api/admin/pending_users");
    const users = data.users || [];
    if (!users.length) {
      setStatus("暂无待审批用户");
      return;
    }
    setStatus(`待审批: ${users.length}`);
    for (const u of users) els.pendingList.appendChild(makeItem(u));
  } catch (e) {
    setStatus(`加载失败: ${e.message || e}`);
  }
}

async function pollMessages() {
  try {
    const me = await requireAdmin();
    if (!me) return;
    const data = await fetchJson(`/api/admin/messages?after_id=${encodeURIComponent(lastMessageId)}`);
    const msgs = data.messages || [];
    if (msgs.length) {
      for (const m of msgs) {
        els.messageList.prepend(makeMessageItem(m));
        lastMessageId = Math.max(lastMessageId, m.id);
      }
    }
    if (typeof window.__setAdminPendingCount === "function") {
      window.__setAdminPendingCount(data.pending_count);
    }
    while (els.messageList.children.length > 50) {
      els.messageList.removeChild(els.messageList.lastElementChild);
    }
    setMsgStatus(msgs.length ? "已更新" : "无新增");
  } catch (e) {
    setMsgStatus(`加载失败: ${e.message || e}`);
  }
}

loadPending();
pollMessages();
setInterval(pollMessages, 30000);
