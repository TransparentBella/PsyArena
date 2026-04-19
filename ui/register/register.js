function qs(id) {
  const el = document.getElementById(id);
  if (!el) throw new Error(`missing element: ${id}`);
  return el;
}

const els = {
  nicknameInput: qs("nicknameInput"),
  passwordInput: qs("passwordInput"),
  registerBtn: qs("registerBtn"),
  statusText: qs("statusText"),
};

function setStatus(text) {
  els.statusText.textContent = text || "";
}

async function register() {
  setStatus("提交中…");
  try {
    const res = await fetch("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        nickname: (els.nicknameInput.value || "").trim(),
        password: els.passwordInput.value || "",
      }),
    });
    const raw = await res.text();
    let data = null;
    try {
      data = JSON.parse(raw);
    } catch {}
    if (!res.ok) throw new Error((data && data.detail) || raw || `${res.status} ${res.statusText}`);
    setStatus("已提交，等待管理员审批。审批通过后可登录。");
    els.registerBtn.disabled = true;
  } catch (e) {
    setStatus(`注册失败: ${e.message || e}`);
  }
}

els.registerBtn.addEventListener("click", register);
window.addEventListener("keydown", (e) => {
  if (e.key === "Enter") register();
});

