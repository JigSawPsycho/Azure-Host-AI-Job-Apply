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
    userEl.textContent = settings.github_login ? "@" + settings.github_login : settings.display_name;
    window.__aiApplySettings = settings;
  } catch (err) {
    userEl.textContent = "offline";
  }
})();
