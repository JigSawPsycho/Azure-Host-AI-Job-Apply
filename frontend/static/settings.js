// Settings — wires design markup to /api/settings + /api/settings/criteria.
(() => {
  "use strict";

  const els = {
    save: document.getElementById("save"),
    anthropic: document.getElementById("anthropic-key"),
    toggleKey: document.getElementById("toggle-key"),
    model: document.getElementById("model"),
    modelBlurb: document.getElementById("model-blurb"),
    ghBadge: document.getElementById("gh-badge"),
    ghStatus: document.getElementById("gh-status"),
    ghActions: document.getElementById("gh-actions"),
    repo: document.getElementById("repo-name"),
    cvDir: document.getElementById("cv-dir"),
    maxJobs: document.getElementById("max-jobs"),
    maxDrafts: document.getElementById("max-drafts"),
    clearSeen: document.getElementById("clear-seen"),
    clearRejected: document.getElementById("clear-rejected"),
    balanceNum: document.getElementById("balance-num"),
    balanceHelper: document.getElementById("balance-helper"),
    balanceBuy: document.getElementById("balance-buy"),
    billingModes: document.getElementById("billing-modes"),
    modeStatus: document.getElementById("mode-status"),
    pkgGrid: document.getElementById("pkg-grid"),
    pkgDisabledNote: document.getElementById("pkg-disabled-note"),
    activityContainer: document.getElementById("activity-container"),
    anthropicBadge: document.getElementById("anthropic-inactive-badge"),
    addCriteria: document.getElementById("add-criteria-btn"),
    criteriaList: document.getElementById("criteria-list"),
    criteriaSub: document.getElementById("criteria-sub"),
    nav: document.getElementById("settings-nav"),
    status: document.getElementById("status"),
    dialogMount: document.getElementById("dialog-mount"),
    cvFile: document.getElementById("cv-file"),
    cvUploadBtn: document.getElementById("cv-upload-btn"),
    uploadedCvList: document.getElementById("uploaded-cv-list"),
  };

  let modelBlurbs = {};
  let modelCosts = {};
  let billingState = { billing_mode: "tokens" };
  let showKey = false;
  let criteriaCache = [];
  let isDirty = false;
  let suppressDirtyOnce = false;

  const DIRTY_INPUTS = ["anthropic", "model", "repo", "cvDir", "maxJobs", "maxDrafts"];

  function markDirty() {
    if (suppressDirtyOnce) return;
    if (isDirty) return;
    isDirty = true;
    updateDirtyUI();
  }

  function clearDirty() {
    isDirty = false;
    updateDirtyUI();
  }

  function updateDirtyUI() {
    const heading = document.querySelector("main.page .page-header .h1");
    if (heading) {
      let star = heading.querySelector(".dirty-star");
      if (isDirty) {
        if (!star) {
          star = document.createElement("span");
          star.className = "dirty-star";
          star.title = "Unsaved changes";
          star.textContent = " *";
          heading.appendChild(star);
        }
      } else if (star) {
        star.remove();
      }
    }
    document.title = isDirty ? "ai-apply — settings *" : "ai-apply — settings";
    if (els.save) {
      els.save.classList.toggle("attention", isDirty);
      const baseLabel = window.I.check(13) + " Save settings";
      els.save.innerHTML = isDirty ? baseLabel + " *" : baseLabel;
    }
    const banner = document.getElementById("dirty-banner");
    if (isDirty) {
      if (!banner) {
        const b = document.createElement("div");
        b.id = "dirty-banner";
        b.className = "dirty-banner";
        b.innerHTML = `${window.I.alert(14)} Unsaved changes — click <strong>Save settings</strong> to apply.`;
        const main = document.querySelector("main.page");
        const header = main?.querySelector(".page-header");
        if (header && header.nextSibling) main.insertBefore(b, header.nextSibling);
        else main?.prepend(b);
      }
    } else if (banner) {
      banner.remove();
    }
  }

  function attachDirtyTracking() {
    for (const key of DIRTY_INPUTS) {
      const el = els[key];
      if (!el) continue;
      const evt = el.tagName === "SELECT" ? "change" : "input";
      el.addEventListener(evt, markDirty);
    }
  }

  window.addEventListener("beforeunload", (e) => {
    if (!isDirty) return;
    e.preventDefault();
    e.returnValue = "";
    return "";
  });

  document.addEventListener(
    "click",
    (e) => {
      if (!isDirty) return;
      const a = e.target.closest("a[href]");
      if (!a) return;
      const href = a.getAttribute("href");
      if (!href || href.startsWith("#") || a.target === "_blank") return;
      // Allow GitHub OAuth redirect since it is the user's intent and would
      // navigate away regardless. For all other in-app links, intercept.
      if (a.href === window.location.href) return;
      e.preventDefault();
      openConfirm({
        title: "Discard unsaved changes?",
        body: "You have unsaved changes on this page. Leaving now will lose them.",
        items: ["Click Cancel to stay and save first.", "Click Discard to leave anyway."],
        danger: true,
        confirmLabel: "Discard",
        onConfirm: () => {
          isDirty = false;
          window.location.href = a.href;
        },
      });
    },
    true,
  );

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function setStatus(message, kind) {
    els.status.textContent = message || "";
    els.status.style.color =
      kind === "err" ? "oklch(0.82 0.15 25)" : kind === "ok" ? "oklch(0.82 0.14 155)" : "var(--text-muted)";
    if (message) {
      clearTimeout(setStatus._t);
      setStatus._t = setTimeout(() => (els.status.textContent = ""), 2500);
    }
  }

  function setIcons() {
    els.save.innerHTML = window.I.check(13) + " Save settings";
    els.toggleKey.innerHTML = window.I.eye(14);
    els.addCriteria.innerHTML = window.I.plus(13) + " Add criteria";
    els.clearSeen.innerHTML = window.I.trash(13) + " Clear seen";
    els.clearRejected.innerHTML = window.I.trash(13) + " Clear rejected";
    if (els.cvUploadBtn) els.cvUploadBtn.innerHTML = window.I.plus(13) + " Choose file";
  }

  function fmtBytes(n) {
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / (1024 * 1024)).toFixed(2) + " MB";
  }

  async function loadUploadedCvs() {
    if (!els.uploadedCvList) return;
    const res = await fetch("/api/cvs");
    if (!res.ok) {
      els.uploadedCvList.innerHTML = `<div class="muted" style="font-size:13px;text-align:center;padding:18px;">Could not load uploads.</div>`;
      return;
    }
    const rows = await res.json();
    if (!rows.length) {
      els.uploadedCvList.innerHTML = `<div class="muted" style="font-size:13px;text-align:center;padding:18px;">No files uploaded yet.</div>`;
      return;
    }
    els.uploadedCvList.innerHTML = rows
      .map(
        (r) => `
      <div class="crit-row" data-id="${r.id}">
        <div>
          <div class="name">${escapeHtml(r.name)}</div>
          <div class="meta">${fmtBytes(r.size)} · ${escapeHtml(r.sha.slice(0, 8))} · uploaded ${escapeHtml(new Date(r.uploaded_at).toLocaleString())}</div>
        </div>
        <div class="actions">
          <button class="btn sm danger" data-act="del">${window.I.trash(12)}</button>
        </div>
      </div>`
      )
      .join("");
    els.uploadedCvList.querySelectorAll(".crit-row").forEach((row) => {
      const id = +row.dataset.id;
      const r = rows.find((x) => x.id === id);
      row.querySelector('[data-act="del"]').addEventListener("click", () =>
        openConfirm({
          title: `Delete "${r.name}"?`,
          body: "This removes the uploaded file. Future runs will not see it.",
          danger: true,
          onConfirm: async () => {
            const res = await fetch(`/api/cvs/${id}`, { method: "DELETE" });
            if (!res.ok) {
              setStatus(`Delete failed: ${res.status}`, "err");
              return;
            }
            await loadUploadedCvs();
            setStatus("Deleted", "ok");
          },
        })
      );
    });
  }

  els.cvUploadBtn?.addEventListener("click", () => els.cvFile.click());

  els.cvFile?.addEventListener("change", async () => {
    const f = els.cvFile.files && els.cvFile.files[0];
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    setStatus("Uploading…");
    const res = await fetch("/api/cvs", { method: "POST", body: fd });
    els.cvFile.value = "";
    if (!res.ok) {
      const body = await res.text();
      setStatus(`Upload failed: ${body || res.status}`, "err");
      return;
    }
    setStatus("Uploaded", "ok");
    await loadUploadedCvs();
  });

  els.toggleKey?.addEventListener("click", () => {
    showKey = !showKey;
    els.anthropic.type = showKey ? "text" : "password";
  });

  // Side-nav scroll + active state
  els.nav.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => {
      els.nav.querySelectorAll("button").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("sec-" + btn.dataset.section)?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });

  async function loadSettings() {
    suppressDirtyOnce = true;
    const res = await fetch("/api/settings");
    if (res.status === 401) {
      suppressDirtyOnce = false;
      return;
    }
    if (!res.ok) {
      suppressDirtyOnce = false;
      setStatus(`Could not load settings: ${res.status}`, "err");
      return;
    }
    const s = await res.json();
    if (s.has_anthropic_key) els.anthropic.placeholder = "(set — paste a new value to replace)";

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
    els.modelBlurb.textContent = modelBlurbs[s.generation_model] || "";
    window.__aiApplyGenerationModel = s.generation_model;

    els.repo.value = s.repo_full_name || "";
    els.cvDir.value = s.cv_dir || "cv";
    els.maxJobs.value = s.max_jobs_per_run;
    els.maxDrafts.value = s.max_drafts_per_run;

    if (s.github_connected) {
      const who = s.github_login ? "@" + s.github_login : "your GitHub account";
      els.ghStatus.textContent = `Authorized as ${who}.`;
      els.ghBadge.hidden = false;
      els.ghActions.innerHTML = `<a class="btn" href="/auth/github/login">${window.I.github(14)} Reconnect</a>`;
    } else {
      els.ghStatus.textContent = "Not connected. ai-apply can't fetch CVs or open PRs until you connect.";
      els.ghBadge.hidden = true;
      els.ghActions.innerHTML = `<a class="btn primary" href="/auth/github/login">${window.I.github(14)} Connect GitHub</a>`;
    }
    setTimeout(() => {
      suppressDirtyOnce = false;
      clearDirty();
    }, 0);
  }

  els.model.addEventListener("change", () => (els.modelBlurb.textContent = modelBlurbs[els.model.value] || ""));

  function renderCriteria() {
    els.criteriaSub.textContent = `${criteriaCache.length} active. Each runs independently per pipeline.`;
    if (criteriaCache.length === 0) {
      els.criteriaList.innerHTML = `<div class="muted" style="font-size:13px;text-align:center;padding:24px;">No criteria yet. Add at least one to start running pipelines.</div>`;
      return;
    }
    const SITE_LABEL = { au: "Seek AU", nz: "Seek NZ", wanted: "Wanted" };
    els.criteriaList.innerHTML = criteriaCache
      .map(
        (c) => `
      <div class="crit-row" data-id="${c.id}">
        <div>
          <div class="name">${escapeHtml(c.name)}</div>
          <div class="meta">${escapeHtml(SITE_LABEL[c.site] || c.site)} · ${escapeHtml(c.keywords || "(no keywords)")} · ${escapeHtml(c.location || "")}</div>
        </div>
        <div class="actions">
          <button class="btn sm" data-act="edit">${window.I.edit(12)} Edit</button>
          <button class="btn sm danger" data-act="del">${window.I.trash(12)}</button>
        </div>
      </div>`
      )
      .join("");
    els.criteriaList.querySelectorAll(".crit-row").forEach((row) => {
      const id = +row.dataset.id;
      const c = criteriaCache.find((x) => x.id === id);
      row.querySelector('[data-act="edit"]').addEventListener("click", () => openCriteriaEditor(c));
      row.querySelector('[data-act="del"]').addEventListener("click", () =>
        openConfirm({
          title: `Delete "${c.name}"?`,
          body: "This removes the search from future runs. Cover letters already drafted from it stay on the Applications page.",
          danger: true,
          onConfirm: async () => {
            await fetch(`/api/settings/criteria/${id}`, { method: "DELETE" });
            await loadCriteria();
          },
        })
      );
    });
  }

  async function loadCriteria() {
    const res = await fetch("/api/settings/criteria");
    if (!res.ok) return;
    criteriaCache = await res.json();
    renderCriteria();
  }

  els.save.addEventListener("click", async () => {
    const payload = {
      generation_model: els.model.value,
      repo_full_name: els.repo.value.trim(),
      cv_dir: els.cvDir.value.trim() || "cv",
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
    clearDirty();
    setStatus("Saved", "ok");
    loadSettings();
  });

  els.clearSeen.addEventListener("click", () =>
    openConfirm({
      title: "Clear seen jobs cache?",
      body: "ai-apply will forget every listing it has shown you so far. After clearing:",
      items: [
        "Listings already shown to you may be re-fetched",
        "Generated cover letters stay attached to original listings",
        "Applied/rejected statuses are NOT affected",
      ],
      danger: true,
      onConfirm: async () => {
        setStatus("Clearing seen…");
        const res = await fetch("/api/settings/clear-seen", { method: "POST" });
        if (!res.ok) {
          setStatus(`Clear failed: ${res.status}`, "err");
          return;
        }
        const body = await res.json();
        setStatus(`Cleared ${body.deleted} seen jobs`, "ok");
      },
    })
  );

  els.clearRejected.addEventListener("click", () =>
    openConfirm({
      title: "Clear rejected applications?",
      body: "This permanently clears your rejected applications log. Going forward:",
      items: [
        "Previously rejected listings will be eligible to reappear in future runs",
        "Cover letters drafted for those listings stay archived",
        "This does not affect 'Sent' history",
      ],
      danger: true,
      onConfirm: async () => {
        setStatus("Clearing rejected…");
        const res = await fetch("/api/settings/clear-rejected", { method: "POST" });
        if (!res.ok) {
          setStatus(`Clear failed: ${res.status}`, "err");
          return;
        }
        const body = await res.json();
        setStatus(`Cleared ${body.deleted} rejected`, "ok");
      },
    })
  );

  els.addCriteria.addEventListener("click", () => openCriteriaEditor(null));

  function openConfirm({ title, body, items = [], danger = false, onConfirm, confirmLabel }) {
    els.dialogMount.innerHTML = `
      <div class="dialog-backdrop" id="db">
        <div class="dialog" id="dlg">
          <h3>${escapeHtml(title)}</h3>
          <p>${escapeHtml(body)}</p>
          ${items.length ? `<ul>${items.map((i) => `<li>${escapeHtml(i)}</li>`).join("")}</ul>` : ""}
          <div class="dialog-actions">
            <button class="btn ghost" id="cancel">Cancel</button>
            <button class="btn ${danger ? "danger" : "primary"}" id="ok">${escapeHtml(confirmLabel || (danger ? "Confirm" : "OK"))}</button>
          </div>
        </div>
      </div>`;
    const close = () => (els.dialogMount.innerHTML = "");
    document.getElementById("db").addEventListener("click", (e) => {
      if (e.target.id === "db") close();
    });
    document.getElementById("cancel").addEventListener("click", close);
    document.getElementById("ok").addEventListener("click", async () => {
      close();
      await onConfirm?.();
    });
  }

  function openCriteriaEditor(initial) {
    const isNew = !initial;
    const c = initial || { name: "", site: "au", keywords: "", location: "All Australia" };
    els.dialogMount.innerHTML = `
      <div class="dialog-backdrop" id="db">
        <div class="dialog" id="dlg" style="max-width: 520px;">
          <h3>${isNew ? "New search criteria" : "Edit search criteria"}</h3>
          <div class="stack" style="gap: 14px;">
            <div class="field"><label>Name</label><input id="f-name" class="input" value="${escapeHtml(c.name)}" placeholder="e.g. NZ Senior Frontend" /></div>
            <div class="field">
              <label>Job board</label>
              <select id="f-site" class="select">
                <option value="au"${c.site === "au" ? " selected" : ""}>Seek AU</option>
                <option value="nz"${c.site === "nz" ? " selected" : ""}>Seek NZ</option>
                <option value="wanted"${c.site === "wanted" ? " selected" : ""}>Wanted (KO)</option>
              </select>
            </div>
            <div class="field"><label>Keywords</label><input id="f-keywords" class="input" value="${escapeHtml(c.keywords)}" placeholder="comma, separated, terms" /></div>
            <div class="field"><label>Location</label><input id="f-location" class="input" value="${escapeHtml(c.location)}" placeholder="City, Region, or Remote" /></div>
          </div>
          <div class="dialog-actions" style="margin-top: 18px;">
            <button class="btn ghost" id="cancel">Cancel</button>
            <button class="btn primary" id="ok">Save</button>
          </div>
        </div>
      </div>`;
    const close = () => (els.dialogMount.innerHTML = "");
    document.getElementById("db").addEventListener("click", (e) => {
      if (e.target.id === "db") close();
    });
    document.getElementById("cancel").addEventListener("click", close);
    document.getElementById("ok").addEventListener("click", async () => {
      const payload = {
        name: document.getElementById("f-name").value.trim(),
        site: document.getElementById("f-site").value,
        keywords: document.getElementById("f-keywords").value.trim(),
        location: document.getElementById("f-location").value.trim() || "All Australia",
      };
      if (!payload.name) {
        setStatus("Name is required", "err");
        return;
      }
      const url = isNew ? "/api/settings/criteria" : `/api/settings/criteria/${initial.id}`;
      const method = isNew ? "POST" : "PUT";
      const fullPayload = isNew
        ? payload
        : { ...initial, ...payload, work_arrangement: initial.work_arrangement || [], work_type: initial.work_type || [], exclude_keywords: initial.exclude_keywords || [] };
      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fullPayload),
      });
      if (!res.ok) {
        setStatus(`Save failed: ${res.status}`, "err");
        return;
      }
      close();
      await loadCriteria();
      setStatus("Saved", "ok");
    });
  }

  function initScrollSpy() {
    const buttons = Array.from(els.nav.querySelectorAll("button[data-section]"));
    if (!buttons.length || !("IntersectionObserver" in window)) return;
    const sections = buttons
      .map((b) => ({ btn: b, el: document.getElementById("sec-" + b.dataset.section) }))
      .filter((x) => x.el);
    const visible = new Set();
    const setActive = (btn) => {
      buttons.forEach((b) => b.classList.toggle("active", b === btn));
    };
    const observer = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) visible.add(e.target);
          else visible.delete(e.target);
        }
        // Pick the topmost visible section.
        const top = sections
          .filter((x) => visible.has(x.el))
          .sort((a, b) => a.el.getBoundingClientRect().top - b.el.getBoundingClientRect().top)[0];
        if (top) setActive(top.btn);
      },
      { rootMargin: "-25% 0px -55% 0px", threshold: 0 },
    );
    sections.forEach((x) => observer.observe(x.el));
  }

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
      r.closest(".billing-mode").classList.toggle("active", r.value === mode);
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
      buy.className = "btn block" + (idx === 1 ? " primary" : "");
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
        <div class="activity-empty-icon">${window.I.sparkles(22)}</div>
        <div class="activity-empty-title">No activity yet</div>
        <div class="activity-empty-desc">Buy a token pack or run your pipeline — every debit and credit will show up here so you can see exactly where your tokens go.</div>
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
    document.dispatchEvent(new CustomEvent("billing:mode-changed", { detail: updated }));
    els.modeStatus.textContent = "Saved";
    els.modeStatus.className = "status ok";
    setTimeout(() => (els.modeStatus.textContent = ""), 2000);
  });

  els.balanceBuy.addEventListener("click", () => {
    document.getElementById("pkg-grid")?.scrollIntoView({ behavior: "smooth", block: "center" });
  });

  document.addEventListener("billing:credited", async () => {
    await loadBilling();
  });

  (async () => {
    setIcons();
    attachDirtyTracking();
    await new Promise((r) => setTimeout(r, 30));
    if (window.__aiApplyAnonymous) return;
    await loadSettings();
    await loadBilling();
    await loadCriteria();
    await loadUploadedCvs();
    initScrollSpy();
  })();
})();
