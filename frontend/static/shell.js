// Shared shell: shows logged-in user, redirects to login on 401.
(async () => {
  "use strict";
  const userEl = document.getElementById("shell-user");
  if (!userEl) return;
  try {
    const res = await fetch("/api/settings", { cache: "no-store" });
    if (res.status === 401) {
      const signedOut = document.getElementById("signed-out");
      if (signedOut) signedOut.hidden = false;
      userEl.innerHTML = '<a href="/auth/github/login">Sign in</a>';
      window.__aiApplyAnonymous = true;
      return;
    }
    if (!res.ok) {
      userEl.textContent = `error ${res.status}`;
      return;
    }
    const settings = await res.json();
    userEl.textContent = "@" + settings.github_login;
    window.__aiApplySettings = settings;
  } catch (err) {
    userEl.textContent = "offline";
  }
})();
