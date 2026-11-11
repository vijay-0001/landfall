// Kiln & Co. staff login (mock). Text is set with textContent only.
(() => {
  const msg = document.querySelector("#lmsg");
  document.querySelector("#lform").addEventListener("submit", async (e) => {
    e.preventDefault();
    msg.hidden = true;
    try {
      const r = await fetch("/api/admin/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user: document.querySelector("#user").value, password: document.querySelector("#password").value }) });
      if (r.ok) { location.href = "/admin"; return; }
      const j = await r.json().catch(() => ({}));
      msg.textContent = j.detail ?? "Sign-in did not work.";
    } catch { msg.textContent = "Sign-in did not work."; }
    msg.hidden = false;
  });
})();
