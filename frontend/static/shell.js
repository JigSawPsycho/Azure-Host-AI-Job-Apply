// Shared shell: shows logged-in user, redirects to /login.html on 401.
// Also fetches the user's billing state and renders the balance pill in
// the top nav so every page sees their token balance / BYOK status.
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
    window.__aiApplySettings = settings;

    const billingPill = await renderBillingPill();

    const label = settings.github_login ? "@" + settings.github_login : settings.display_name;
    userEl.innerHTML = "";
    if (billingPill) userEl.appendChild(billingPill);
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
  } catch (err) {
    userEl.textContent = "offline";
  }

  async function renderBillingPill() {
    let bal;
    try {
      const r = await fetch("/api/billing/balance", { cache: "no-store" });
      if (!r.ok) return null;
      bal = await r.json();
    } catch (_) {
      return null;
    }
    window.__aiApplyBilling = bal;

    if (bal.billing_mode === "byok") {
      const pill = document.createElement("div");
      pill.className = "billing-pill byok";
      pill.title = "Open billing settings";
      pill.style.cursor = "pointer";
      pill.addEventListener("click", () => {
        window.location.href = "/settings.html#billing";
      });
      pill.innerHTML = `<span class="bp-icon">⌘</span><span>Using own API key</span>`;
      return pill;
    }

    const pill = document.createElement("div");
    pill.className = "billing-pill tokens";

    const balanceBtn = document.createElement("button");
    balanceBtn.type = "button";
    balanceBtn.className = "bp-balance";
    balanceBtn.title = "Open billing settings";
    balanceBtn.addEventListener("click", () => {
      window.location.href = "/settings.html#billing";
    });
    const num = formatTokens(bal.token_balance);
    balanceBtn.innerHTML = `<span class="bp-num">${num}</span><span class="bp-label">tokens</span>`;

    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "bp-add";
    addBtn.setAttribute("aria-label", "Buy more tokens");
    addBtn.title = "Buy more tokens";
    addBtn.textContent = "+";
    addBtn.addEventListener("click", () => {
      window.location.href = "/settings.html#billing";
    });

    pill.append(balanceBtn, addBtn);
    return pill;
  }

  function formatTokens(t) {
    return Number(Number(t).toFixed(2)).toString();
  }
})();
