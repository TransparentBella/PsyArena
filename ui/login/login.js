function qs(id) {
  const el = document.getElementById(id);
  if (!el) throw new Error(`missing element: ${id}`);
  return el;
}

const els = {
  usernameInput: qs("usernameInput"),
  passwordInput: qs("passwordInput"),
  loginBtn: qs("loginBtn"),
  resetBox: qs("resetBox"),
  newPasswordInput: qs("newPasswordInput"),
  changePwdBtn: qs("changePwdBtn"),
  logoutBtn: qs("logoutBtn"),
  statusText: qs("statusText"),
};

function setStatus(text) {
  els.statusText.textContent = text || "";
}

function showReset() {
  els.resetBox.hidden = false;
}

async function routeUserAfterLogin(role) {
  if (role === "admin") {
    window.location.href = "/ui/stats/";
    return;
  }
  try {
    const inboxRes = await fetch("/api/user/inbox");
    if (!inboxRes.ok) throw new Error(`${inboxRes.status} ${inboxRes.statusText}`);
    const inbox = await inboxRes.json();
    const pending = Number(inbox && inbox.pending_count ? inbox.pending_count : 0);
    window.location.href = pending > 0 ? "/ui/" : "/ui/user/";
  } catch {
    window.location.href = "/ui/";
  }
}

async function login() {
  setStatus("登录中…");
  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: (els.usernameInput.value || "").trim(),
        password: els.passwordInput.value || "",
      }),
    });
    const raw = await res.text();
    let data = null;
    try {
      data = JSON.parse(raw);
    } catch {}
    if (!res.ok) throw new Error((data && data.detail) || raw || `${res.status} ${res.statusText}`);
    if (data && data.needs_password_reset) {
      setStatus("首次登录需要改密");
      showReset();
      return;
    }
    await routeUserAfterLogin(data && data.role);
  } catch (e) {
    setStatus(`登录失败: ${e.message || e}`);
  }
}

async function changePwd() {
  setStatus("改密中…");
  try {
    const res = await fetch("/api/auth/change_password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_password: els.newPasswordInput.value || "" }),
    });
    const raw = await res.text();
    let data = null;
    try {
      data = JSON.parse(raw);
    } catch {}
    if (!res.ok) throw new Error((data && data.detail) || raw || `${res.status} ${res.statusText}`);
    setStatus("改密成功，跳转中…");
    let role = "user";
    try {
      const meRes = await fetch("/api/auth/me");
      if (meRes.ok) {
        const me = await meRes.json();
        role = (me && me.role) || "user";
      }
    } catch {}
    await routeUserAfterLogin(role);
  } catch (e) {
    setStatus(`改密失败: ${e.message || e}`);
  }
}

async function logout() {
  fetch("/api/auth/logout", { method: "POST" }).finally(() => {
    window.location.href = "/ui/login/";
  });
}

els.loginBtn.addEventListener("click", login);
els.changePwdBtn.addEventListener("click", changePwd);
els.logoutBtn.addEventListener("click", logout);

window.addEventListener("keydown", (e) => {
  if (e.key === "Enter") login();
});

if (new URLSearchParams(window.location.search).get("reset") === "1") {
  showReset();
  setStatus("需要改密后才能继续");
}
