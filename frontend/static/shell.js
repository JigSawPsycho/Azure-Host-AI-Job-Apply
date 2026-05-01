// Shared shell: shows logged-in user, redirects to /login.html on 401.
(async () => {
  "use strict";
  const userEl = document.getElementById("shell-user");
  if (!userEl) return;
  try {
    const res = await fetch("/api/settings", { cache: "no-store" });
    if (res.status === 401) {
      window.__aiApplyAnonymous = true;
      // Don't redirect-loop if we're already on an auth page.
      if (!/\/(login|signup)\.html$/.test(window.location.pathname)) {
        const next = encodeURIComponent(window.location.pathname + window.location.search);
        window.location.replace(`/login.html?next=${next}`);
      }
      return;
    }
    if (!res.ok) {
      userEl.textContent = `error ${res.status}`;
      return;
    }
    const settings = await res.json();
    const label = settings.github_login ? "@" + settings.github_login : settings.display_name;
    userEl.innerHTML = "";
    const nameSpan = document.createElement("span");
    nameSpan.className = "shell-user-name";
    nameSpan.textContent = label;
    const logoutBtn = document.createElement("button");
    logoutBtn.type = "button";
    logoutBtn.className = "shell-logout";
    logoutBtn.textContent = "Log out";
    logoutBtn.addEventListener("click", async () => {
      logoutBtn.disabled = true;
      try {
        await fetch("/auth/github/logout", { method: "POST" });
      } catch (_) {}
      window.location.replace("/login.html");
    });
    userEl.append(nameSpan, logoutBtn);
    window.__aiApplySettings = settings;
  } catch (err) {
    userEl.textContent = "offline";
  }
})();
