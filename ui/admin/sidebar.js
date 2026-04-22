function qs(sel) {
  const el = document.querySelector(sel);
  if (!el) throw new Error(`missing element: ${sel}`);
  return el;
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

function isActive(pathname, target) {
  if (target === "/ui/stats/") return pathname.startsWith("/ui/stats");
  if (target === "/ui/admin/") return pathname.startsWith("/ui/admin");
  return pathname === target;
}

function setPendingCount(count) {
  const badge = document.getElementById("pendingBadge");
  if (!badge) return;
  const n = Number.isFinite(Number(count)) ? Number(count) : 0;
  badge.textContent = String(n);
  badge.hidden = n <= 0;
}

async function logout() {
  try {
    await fetch("/api/auth/logout", { method: "POST" });
  } finally {
    window.location.href = "/ui/login/";
  }
}

export async function initAdminSidebar() {
  const root = qs("#sidebar-root");

  let me = null;
  try {
    me = await fetchJson("/api/auth/me");
  } catch (e) {
    window.location.href = "/ui/login/";
    return;
  }
  if (!me || me.role !== "admin") {
    window.location.href = "/ui/login/";
    return;
  }
  if (me.needs_password_reset) {
    window.location.href = "/ui/login/?reset=1";
    return;
  }

  root.innerHTML = `
    <div class="adminSidebar__section">
      <div class="adminSidebar__title">PsyRanking</div>
      <div class="muted">管理员：${me.nickname || me.username}</div>
    </div>

    <div class="adminSidebar__section">
      <a class="adminNavItem" data-href="/ui/stats/" href="/ui/stats/">
        <span>统计页</span>
      </a>
      <a class="adminNavItem" data-href="/ui/admin/" href="/ui/admin/">
        <span>消息中心</span>
        <span id="pendingBadge" class="adminNavBadge" hidden>0</span>
      </a>
    </div>

    <div class="adminSidebar__spacer"></div>

    <div class="adminSidebar__section">
      <button id="logoutBtn" class="btn btn--ghost adminLogout">退出登录</button>
    </div>
  `;

  const pathname = window.location.pathname;
  root.querySelectorAll(".adminNavItem").forEach((a) => {
    const href = a.getAttribute("data-href") || "";
    if (isActive(pathname, href)) a.classList.add("adminNavItem--active");
  });
  qs("#logoutBtn").addEventListener("click", logout);

  window.__setAdminPendingCount = setPendingCount;

  document.body.style.visibility = "visible";

  try {
    const data = await fetchJson(`/api/admin/messages?after_id=${encodeURIComponent(9007199254740991)}`);
    setPendingCount(data.pending_count);
  } catch {}
}

initAdminSidebar();
