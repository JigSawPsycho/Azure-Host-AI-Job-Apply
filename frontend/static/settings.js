(() => {
  "use strict";

  const els = {
    anthropic: document.getElementById("anthropic-key"),
    anthropicHint: document.getElementById("anthropic-key-hint"),
    anthropicBadge: document.getElementById("anthropic-inactive-badge"),
    model: document.getElementById("model"),
    blurb: document.getElementById("model-blurb"),
    ghStatus: document.getElementById("github-status"),
    ghConnectBtn: document.getElementById("github-connect-btn"),
    ghPrBtn: document.getElementById("github-connect-pr-btn"),
    repo: document.getElementById("repo-name"),
    cvDir: document.getElementById("cv-dir"),
    pr: document.getElementById("deliver-as-pr"),
    maxJobs: document.getElementById("max-jobs"),
    maxDrafts: document.getElementById("max-drafts"),
    save: document.getElementById("save"),
    status: document.getElementById("status"),
    list: document.getElementById("criteria-list"),
    newName: document.getElementById("new-name"),
    newSite: document.getElementById("new-site"),
    newKeywords: document.getElementById("new-keywords"),
    newLocation: document.getElementById("new-location"),
    addCriteria: document.getElementById("add-criteria"),
    clearSeen: document.getElementById("clear-seen"),
    clearRejected: document.getElementById("clear-rejected"),
    // billing
    balanceNum: document.getElementById("balance-num"),
    balanceHelper: document.getElementById("balance-helper"),
    balanceBuy: document.getElementById("balance-buy"),
    billingModes: document.getElementById("billing-modes"),
    modeStatus: document.getElementById("mode-status"),
    pkgGrid: document.getElementById("pkg-grid"),
    pkgDisabledNote: document.getElementById("pkg-disabled-note"),
    activityContainer: document.getElementById("activity-container"),
  };

  let modelBlurbs = {};
  let modelCosts = {};
  let billingState = { billing_mode: "tokens" };

  function setStatus(message, kind) {
    els.status.textContent = message || "";
    els.status.className = "status" + (kind ? " " + kind : "");
  }

  async function loadSettings() {
    const res = await fetch("/api/settings");
    if (res.status === 401) return;
    if (!res.ok) {
      setStatus(`Could not load settings: ${res.status}`, "err");
      return;
    }
    const s = await res.json();
    if (s.has_anthropic_key) {
      els.anthropic.placeholder = "(set — paste a new value to replace)";
    }
    els.model.innerHTML = "";
    modelBlurbs = {};
    modelCosts = {};
    for (const opt of s.available_models) {
      const tokens = (opt.cost_centitokens || 0) / 100;
      const showCost = billingState.billing_mode !== "byok";
      const costSuffix = showCost
        ? `  —  ${formatTokens(tokens)} ${tokens === 1 ? "token" : "tokens"}/letter`
        : "";
      const o = document.createElement("option");
      o.value = opt.id;
      o.textContent = opt.label + costSuffix;
      if (opt.id === s.generation_model) o.selected = true;
      els.model.appendChild(o);
      modelBlurbs[opt.id] = opt.blurb;
      modelCosts[opt.id] = opt.cost_centitokens;
    }
    els.blurb.textContent = modelBlurbs[s.generation_model] || "";
    // Stash so the run page (or any other page) can read the chosen model
    // and per-model cost without refetching.
    window.__aiApplyModelCosts = modelCosts;
    window.__aiApplyGenerationModel = s.generation_model;
    els.repo.value = s.repo_full_name || "";
    els.cvDir.value = s.cv_dir || "cv";
    els.pr.checked = !!s.deliver_as_pr;
    els.maxJobs.value = s.max_jobs_per_run;
    els.maxDrafts.value = s.max_drafts_per_run;

    if (s.github_connected) {
      const who = s.github_login ? "@" + s.github_login : "your GitHub account";
      els.ghStatus.textContent = `Connected as ${who}.`;
      els.ghStatus.style.color = "var(--accent)";
      els.ghConnectBtn.textContent = "Reconnect GitHub";
      els.ghPrBtn.hidden = false;
    } else {
      els.ghStatus.textContent = "Not connected. ai-apply can't fetch CVs or open PRs until you connect.";
      els.ghStatus.style.color = "";
      els.ghConnectBtn.textContent = "Connect GitHub";
      els.ghPrBtn.hidden = true;
    }
  }

  async function loadCriteria() {
    const res = await fetch("/api/settings/criteria");
    if (!res.ok) return;
    const rows = await res.json();
    els.list.innerHTML = "";
    if (rows.length === 0) {
      els.list.innerHTML = '<p class="model-blurb">No saved searches yet.</p>';
      return;
    }
    for (const c of rows) {
      const row = document.createElement("div");
      row.className = "criteria-row";
      const name = document.createElement("strong");
      name.textContent = c.name;
      const site = document.createElement("span");
      site.textContent = `${c.site} · ${c.keywords || "(no keywords)"}`;
      site.style.color = "var(--text-secondary)";
      const del = document.createElement("button");
      del.className = "btn btn-ghost";
      del.textContent = "Delete";
      del.addEventListener("click", async () => {
        if (!confirm(`Delete "${c.name}"?`)) return;
        await fetch(`/api/settings/criteria/${c.id}`, { method: "DELETE" });
        loadCriteria();
      });
      row.append(name, site, del);
      els.list.appendChild(row);
    }
  }

  els.model.addEventListener("change", () => {
    els.blurb.textContent = modelBlurbs[els.model.value] || "";
  });

  els.save.addEventListener("click", async () => {
    const payload = {
      generation_model: els.model.value,
      repo_full_name: els.repo.value.trim(),
      cv_dir: els.cvDir.value.trim() || "cv",
      deliver_as_pr: els.pr.checked,
      max_jobs_per_run: parseInt(els.maxJobs.value, 10),
      max_drafts_per_run: parseInt(els.maxDrafts.value, 10),
    };
    if (els.anthropic.value) payload.anthropic_key = els.anthropic.value;
    setStatus("Saving…");
    const res = await fetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const body = await res.text();
      setStatus(`Save failed: ${body || res.status}`, "err");
      return;
    }
    els.anthropic.value = "";
    setStatus("Saved", "ok");
    loadSettings();
  });

  els.addCriteria.addEventListener("click", async () => {
    const payload = {
      name: els.newName.value.trim(),
      site: els.newSite.value,
      keywords: els.newKeywords.value.trim(),
      location: els.newLocation.value.trim() || "All Australia",
    };
    if (!payload.name) { setStatus("Name is required", "err"); return; }
    const res = await fetch("/api/settings/criteria", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) { setStatus(`Add failed: ${res.status}`, "err"); return; }
    els.newName.value = "";
    els.newKeywords.value = "";
    setStatus("Added", "ok");
    loadCriteria();
  });

  els.clearSeen.addEventListener("click", async () => {
    if (!confirm("Clear all seen jobs? This deletes every scraped listing and its generated cover letter (including unsent drafts). The scraper can re-find them on the next run.")) return;
    setStatus("Clearing seen…");
    const res = await fetch("/api/settings/clear-seen", { method: "POST" });
    if (!res.ok) { setStatus(`Clear failed: ${res.status}`, "err"); return; }
    const body = await res.json();
    setStatus(`Cleared ${body.deleted} seen jobs`, "ok");
  });

  els.clearRejected.addEventListener("click", async () => {
    if (!confirm("Clear all rejected applications? This deletes jobs you skipped so they can be re-considered on a future run.")) return;
    setStatus("Clearing rejected…");
    const res = await fetch("/api/settings/clear-rejected", { method: "POST" });
    if (!res.ok) { setStatus(`Clear failed: ${res.status}`, "err"); return; }
    const body = await res.json();
    setStatus(`Cleared ${body.deleted} rejected applications`, "ok");
  });

  // ─── Billing ───────────────────────────────────────────────────────

  function formatTokens(t) {
    // 0.25 / 1 / 5.5 — never trailing zeros.
    return Number(t.toFixed(2)).toString();
  }

  function reasonLabel(reason, modelId) {
    if (reason === "generation") {
      const m = (modelId || "").toLowerCase();
      const family = m.includes("opus")
        ? "Opus"
        : m.includes("haiku")
        ? "Haiku"
        : m.includes("sonnet")
        ? "Sonnet"
        : "model";
      return `Cover letter (${family})`;
    }
    if (reason === "purchase") return "Top-up";
    if (reason === "refund") return "Refund";
    if (reason === "admin_grant") return "Admin grant";
    if (reason === "admin_debit") return "Admin debit";
    return reason || "Activity";
  }

  function applyBillingMode(mode) {
    billingState.billing_mode = mode;
    // Reflect on the radios.
    const radios = els.billingModes.querySelectorAll('input[name="billing-mode"]');
    radios.forEach((r) => {
      r.checked = r.value === mode;
      r.closest(".billing-mode-opt").classList.toggle("active", r.value === mode);
    });
    // Gate the Anthropic key field.
    const isByok = mode === "byok";
    els.anthropic.disabled = !isByok;
    if (els.anthropicBadge) els.anthropicBadge.hidden = isByok;
    if (els.anthropicHint) {
      els.anthropicHint.textContent = isByok
        ? "Stored encrypted at rest. Never shared with third parties."
        : 'Switch billing mode to "Use my own Anthropic API key" to enable.';
    }
    // Gate package buttons.
    if (els.pkgDisabledNote) els.pkgDisabledNote.hidden = !isByok;
    els.pkgGrid.querySelectorAll(".pkg .btn").forEach((b) => {
      b.disabled = isByok;
    });
    // Refresh the model dropdown so cost suffixes appear/disappear.
    if (window.__aiApplySettings) {
      // Re-render labels in place to avoid wiping the user's selection.
      els.model.querySelectorAll("option").forEach((o) => {
        const id = o.value;
        const tokens = (modelCosts[id] || 0) / 100;
        const base = (window.__aiApplySettings.available_models.find((m) => m.id === id) || {}).label || o.textContent;
        o.textContent = isByok
          ? base
          : `${base}  —  ${formatTokens(tokens)} ${tokens === 1 ? "token" : "tokens"}/letter`;
      });
    }
  }

  function renderBalance(b) {
    const tokens = b.token_balance;
    els.balanceNum.textContent = formatTokens(tokens);
    els.balanceHelper.textContent =
      `Enough for ~${formatTokens(tokens)} Sonnet, ~${formatTokens(tokens * 4)} Haiku, or ~${formatTokens(tokens * 0.2)} Opus letters.`;
  }

  function renderPackages(packages) {
    els.pkgGrid.innerHTML = "";
    packages.forEach((p, idx) => {
      const card = document.createElement("div");
      card.className = "pkg" + (idx === 1 ? " popular" : "");
      if (idx === 1) {
        const ribbon = document.createElement("div");
        ribbon.className = "pkg-ribbon";
        ribbon.textContent = "Best value";
        card.appendChild(ribbon);
      }
      const name = document.createElement("div");
      name.className = "pkg-name";
      name.textContent = p.label;
      const tokens = document.createElement("div");
      tokens.className = "pkg-tokens";
      tokens.innerHTML = `${formatTokens(p.tokens)}<span> tokens</span>`;
      const price = document.createElement("div");
      price.className = "pkg-price";
      price.innerHTML = `$${(p.amount_cents / 100).toFixed(0)}<span class="muted"> USD</span>`;
      const rate = document.createElement("div");
      rate.className = "pkg-rate";
      rate.textContent = `$${(p.amount_cents / 100 / p.tokens).toFixed(2)} / token`;
      const buy = document.createElement("button");
      buy.type = "button";
      buy.className = "btn " + (idx === 1 ? "btn-primary" : "btn-outline");
      buy.textContent = `Buy ${p.label}`;
      buy.disabled = billingState.billing_mode === "byok";
      buy.addEventListener("click", () => startCheckout(p));
      card.append(name, tokens, price, rate, buy);
      els.pkgGrid.appendChild(card);
    });
  }

  async function startCheckout(pkg) {
    const ok = confirm(
      `Buy ${pkg.label} pack — $${(pkg.amount_cents / 100).toFixed(0)} USD for ${formatTokens(pkg.tokens)} tokens?\n\nYou'll be redirected to Stripe to complete payment.`
    );
    if (!ok) return;
    const res = await fetch("/api/billing/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ package: pkg.key }),
    });
    if (res.status === 501) {
      window.toast && window.toast({
        variant: "info",
        title: "Billing not configured",
        message: "Stripe isn't set up on this server yet. Contact the admin.",
      });
      return;
    }
    if (!res.ok) {
      const body = await res.text();
      window.toast && window.toast({
        variant: "info",
        title: "Checkout failed",
        message: body || `Status ${res.status}`,
      });
      return;
    }
    const { url } = await res.json();
    window.location.href = url;
  }

  function renderActivity(rows) {
    els.activityContainer.innerHTML = "";
    if (!rows.length) {
      const empty = document.createElement("div");
      empty.className = "activity-empty";
      empty.innerHTML = `
        <div class="title">No activity yet</div>
        <div class="desc">Buy a token pack or run your pipeline — every debit and credit will show up here so you can see exactly where your tokens go.</div>
      `;
      els.activityContainer.appendChild(empty);
      return;
    }
    const table = document.createElement("div");
    table.className = "activity-table";
    const head = document.createElement("div");
    head.className = "activity-row head";
    head.innerHTML = `<div>Date</div><div>Description</div><div class="right">Change</div><div class="right">Balance</div>`;
    table.appendChild(head);
    rows.forEach((r) => {
      const row = document.createElement("div");
      row.className = "activity-row";
      const ts = document.createElement("div");
      ts.className = "ts";
      ts.textContent = new Date(r.created_at).toISOString().slice(0, 16).replace("T", " ");
      const desc = document.createElement("div");
      const descTitle = document.createElement("div");
      descTitle.className = "a-desc";
      descTitle.textContent = reasonLabel(r.reason, r.model_id);
      desc.appendChild(descTitle);
      if (r.note) {
        const meta = document.createElement("div");
        meta.className = "a-meta";
        meta.textContent = r.note;
        desc.appendChild(meta);
      }
      const delta = document.createElement("div");
      delta.className = "right delta " + (r.delta_tokens > 0 ? "pos" : "neg");
      const sign = r.delta_tokens > 0 ? "+" : "";
      delta.textContent = sign + formatTokens(r.delta_tokens);
      const bal = document.createElement("div");
      bal.className = "right bal";
      bal.textContent = formatTokens(r.balance_after_tokens);
      row.append(ts, desc, delta, bal);
      table.appendChild(row);
    });
    els.activityContainer.appendChild(table);
  }

  async function loadBilling() {
    const balRes = await fetch("/api/billing/balance");
    if (!balRes.ok) return;
    const bal = await balRes.json();
    billingState = bal;
    renderBalance(bal);
    renderPackages(bal.packages || []);
    applyBillingMode(bal.billing_mode);

    const ledRes = await fetch("/api/billing/ledger?limit=20");
    if (ledRes.ok) renderActivity(await ledRes.json());
  }

  els.billingModes.addEventListener("change", async (e) => {
    const t = e.target;
    if (!(t instanceof HTMLInputElement) || t.name !== "billing-mode") return;
    const mode = t.value;
    els.modeStatus.textContent = "Updating…";
    els.modeStatus.className = "status";
    const res = await fetch("/api/billing/mode", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ billing_mode: mode }),
    });
    if (!res.ok) {
      const body = await res.text();
      els.modeStatus.textContent = body || `Update failed: ${res.status}`;
      els.modeStatus.className = "status err";
      // revert
      applyBillingMode(billingState.billing_mode);
      return;
    }
    const updated = await res.json();
    billingState = updated;
    applyBillingMode(updated.billing_mode);
    els.modeStatus.textContent = "Saved";
    els.modeStatus.className = "status ok";
    setTimeout(() => (els.modeStatus.textContent = ""), 2000);
  });

  els.balanceBuy.addEventListener("click", () => {
    document.getElementById("pkg-grid")?.scrollIntoView({ behavior: "smooth", block: "center" });
  });

  (async () => {
    await new Promise((r) => setTimeout(r, 30));
    if (window.__aiApplyAnonymous) return;
    await loadSettings();
    await loadBilling();
    await loadCriteria();
  })();
})();
