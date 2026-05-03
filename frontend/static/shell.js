// Shared shell: top nav + user panel; hydrates active link, handles 401.
// Also fetches billing state and prepends a balance pill to the user panel.
(async () => {
  "use strict";
  const userEl = document.getElementById("shell-user");
  if (!userEl) return;

  document.querySelectorAll("[data-nav]").forEach((a) => {
    const path = window.location.pathname;
    const target = a.getAttribute("data-nav");
    if (
      (target === "applications" && (path === "/" || path === "/index.html")) ||
      path === "/" + target + ".html"
    ) {
      a.classList.add("active");
    }
    if (target === "applications" && !a.querySelector(".nav-pill")) {
      const pill = document.createElement("span");
      pill.className = "nav-pill";
      pill.id = "nav-unsent-pill";
      pill.hidden = true;
      a.appendChild(pill);
    }
  });

  window.refreshUnsentPill = async function refreshUnsentPill() {
    const pill = document.getElementById("nav-unsent-pill");
    if (!pill) return;
    try {
      const res = await fetch("/api/applications/counts", { cache: "no-store" });
      if (!res.ok) return;
      const c = await res.json();
      if (c.unsent > 0) {
        pill.textContent = String(c.unsent);
        pill.hidden = false;
      } else {
        pill.hidden = true;
      }
    } catch {}
  };

  try {
    const res = await fetch("/api/settings", { cache: "no-store" });
    if (res.status === 401) {
      window.__aiApplyAnonymous = true;
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
    renderUser(userEl, settings, billingPill);
    window.refreshUnsentPill?.();
  } catch {
    userEl.textContent = "offline";
  }

  window.refreshBillingPill = async function refreshBillingPill() {
    const old = document.querySelector(".topnav-inner > .billing-pill");
    if (old) old.remove();
    const pill = await renderBillingPill();
    if (pill && userEl.parentNode) userEl.parentNode.insertBefore(pill, userEl);
  };
  document.addEventListener("billing:credited", () => window.refreshBillingPill());
  document.addEventListener("billing:mode-changed", () => window.refreshBillingPill());

  function renderUser(el, s, billingPill) {
    const label = s.email || s.display_name || "user";
    const initials = (label || "U")
      .split(/[\s.@_-]+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((p) => p[0].toUpperCase())
      .join("");
    const PROVIDER_LABEL = { github: "GitHub", google: "Google", email: "Email" };
    const providerLine = s.auth_provider
      ? `<div class="provider">Signed in via ${escapeHtml(PROVIDER_LABEL[s.auth_provider] || s.auth_provider)}</div>`
      : "";

    el.innerHTML = `
      <button class="user-trigger" id="user-trigger" type="button">
        <span class="avatar">${initials || "U"}</span>
        <span>${escapeHtml(label)}</span>
        ${window.I.chevDown(12)}
      </button>
      <div class="user-menu" id="user-menu" hidden>
        <div class="user-menu-header">
          <div class="name">${escapeHtml(s.display_name || label)}</div>
          ${s.email ? `<div class="email">${escapeHtml(s.email)}</div>` : ""}
          ${providerLine}
        </div>
        <a class="menu-item" href="/settings.html">${window.I.settings(14)} Account settings</a>
        <button class="menu-item danger" type="button" id="logout-btn">${window.I.logout(14)} Log out</button>
      </div>
    `;
    if (billingPill) el.parentNode?.insertBefore(billingPill, el);
    const trig = el.querySelector("#user-trigger");
    const menu = el.querySelector("#user-menu");
    trig.addEventListener("click", () => {
      menu.hidden = !menu.hidden;
    });
    document.addEventListener("mousedown", (e) => {
      if (!el.contains(e.target)) menu.hidden = true;
    });
    el.querySelector("#logout-btn").addEventListener("click", async () => {
      try {
        await fetch("/auth/github/logout", { method: "POST" });
      } catch {}
      window.location.replace("/login.html");
    });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[c]));
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
