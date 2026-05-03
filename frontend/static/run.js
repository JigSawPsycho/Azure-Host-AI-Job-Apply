(() => {
  "use strict";

  const els = {
    start: document.getElementById("start"),
    headline: document.getElementById("run-headline"),
    sub: document.getElementById("run-sub"),
    bannerSlot: document.getElementById("error-banner-slot"),
    completeCta: document.getElementById("run-complete-cta"),
    completeBtn: document.getElementById("run-complete-btn"),
    statCriteria: document.getElementById("stat-criteria"),
    statFetch: document.getElementById("stat-fetch"),
    statGen: document.getElementById("stat-gen"),
    progress: document.getElementById("run-progress"),
    stages: document.getElementById("run-stages"),
    counters: document.getElementById("run-counters"),
    estimate: document.getElementById("run-estimate"),
    estAmount: document.getElementById("est-amount"),
    estMeta: document.getElementById("est-meta"),
  };

  const STAGES = [
    { key: "pending", label: "Queued" },
    { key: "scraping", label: "Scraping listings" },
    { key: "fetching_cvs", label: "Loading CVs" },
    { key: "generating", label: "Generating drafts" },
    { key: "finished", label: "Done" },
  ];
  const STAGE_INDEX = Object.fromEntries(STAGES.map((s, i) => [s.key, i]));

  const HEADLINES = {
    pending: "Starting up…",
    scraping: "Scraping job boards",
    fetching_cvs: "Loading your CVs",
    generating: "Drafting cover letters",
    finished: "Run finished",
    failed: "Run failed",
  };

  let pollTimer = null;
  let running = false;

  function setBtnIdle() {
    els.start.innerHTML = window.I.play(14) + " Run pipeline";
    els.start.disabled = false;
  }
  function setBtnRunning() {
    els.start.innerHTML = window.I.refresh(16) + " Running";
    els.start.querySelector(".icon")?.classList.add("spin");
    els.start.disabled = true;
  }

  function formatTokens(t) {
    return Number(Number(t).toFixed(2)).toString();
  }

  function modelFamily(id) {
    const m = (id || "").toLowerCase();
    if (m.includes("opus")) return "Opus";
    if (m.includes("haiku")) return "Haiku";
    return "Sonnet";
  }

  function showError(title, message) {
    els.bannerSlot.innerHTML = `
      <div class="error-banner">
        ${window.I.alert(16)}
        <div>
          <div style="font-weight:600;margin-bottom:2px;">${escapeHtml(title)}</div>
          <div style="opacity:.85">${escapeHtml(message || "")}</div>
        </div>
        <button class="x" id="dismiss-err">${window.I.x(14)}</button>
      </div>`;
    document.getElementById("dismiss-err").addEventListener("click", () => (els.bannerSlot.innerHTML = ""));
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function fmtDuration(startedAt, finishedAt) {
    if (!startedAt) return "–";
    const start = new Date(startedAt).getTime();
    const end = finishedAt ? new Date(finishedAt).getTime() : Date.now();
    const sec = Math.max(0, Math.floor((end - start) / 1000));
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}m ${String(s).padStart(2, "0")}s`;
  }

  function fmtTs(iso) {
    if (!iso) return "–";
    const d = new Date(iso);
    return d.toISOString().slice(0, 16).replace("T", " ");
  }

  function showCompleteCta(generated) {
    if (!els.completeCta || !els.completeBtn) return;
    const label = generated > 0
      ? `Run complete — view ${generated} new draft${generated === 1 ? "" : "s"}`
      : "Run complete — open Applications";
    els.completeBtn.innerHTML = `${window.I.check(14)} ${escapeHtml(label)}`;
    els.completeCta.hidden = false;
  }

  function hideCompleteCta() {
    if (els.completeCta) els.completeCta.hidden = true;
  }

  function renderStages(status) {
    const failed = status === "failed";
    const currentIdx = STAGE_INDEX[status] ?? -1;
    els.stages.innerHTML = STAGES
      .map((stage, i) => {
        let cls = "stage";
        if (failed && i <= (els._lastLiveIdx ?? 0)) cls += " failed";
        else if (currentIdx > i || status === "finished") cls += " done";
        else if (currentIdx === i) cls += " active";
        return `<span class="${cls}"><span class="pip"></span>${stage.label}</span>`;
      })
      .join("");
  }

  function renderCounters(run) {
    els.counters.innerHTML = `
      <span class="ctr"><strong>${run.jobs_found || 0}</strong> jobs scraped</span>
      <span class="ctr"><strong>${run.applications_generated || 0}</strong> drafts generated</span>
      <span class="ctr"><strong>${fmtDuration(run.started_at, run.finished_at)}</strong> elapsed</span>
    `;
  }

  function subForStatus(run) {
    switch (run.status) {
      case "pending":
        return "Worker picking up the run…";
      case "scraping":
        return run.jobs_found
          ? `${run.jobs_found} listings collected — still scraping.`
          : "Scraping enabled criteria. Usually 1–3 minutes.";
      case "fetching_cvs":
        return "Loading your CV templates.";
      case "generating": {
        const gen = run.applications_generated || 0;
        const found = run.jobs_found || 0;
        if (found) return `Drafted ${gen} of ${found} listings — calling Anthropic.`;
        return "Generating cover letters…";
      }
      case "finished":
        return `Drafted ${run.applications_generated || 0} application(s) from ${run.jobs_found || 0} listing(s).`;
      case "failed":
        return run.error || "Pipeline failed. Check error details.";
      default:
        return "";
    }
  }

  async function pollRun(runId) {
    const res = await fetch(`/api/runs/${runId}`);
    if (!res.ok) return;
    const run = await res.json();

    const liveIdx = STAGE_INDEX[run.status];
    if (liveIdx !== undefined) els._lastLiveIdx = liveIdx;

    els.progress.hidden = false;
    els.headline.textContent = HEADLINES[run.status] || "Pipeline running…";
    els.sub.textContent = subForStatus(run);
    renderStages(run.status);
    renderCounters(run);

    if (["finished", "failed"].includes(run.status)) {
      clearInterval(pollTimer);
      pollTimer = null;
      running = false;
      setBtnIdle();
      if (run.status === "failed") {
        showError("Run failed", run.error || "");
        hideCompleteCta();
      } else {
        showCompleteCta(run.applications_generated || 0);
      }
      window.refreshUnsentPill?.();
    }
  }

  async function getSettings() {
    const res = await fetch("/api/settings", { cache: "no-store" });
    if (!res.ok) return window.__aiApplySettings || null;
    const s = await res.json();
    window.__aiApplySettings = s;
    return s;
  }

  async function getUploadedCount() {
    try {
      const res = await fetch("/api/cvs");
      if (!res.ok) return 0;
      const rows = await res.json();
      return rows.length;
    } catch {
      return 0;
    }
  }

  async function checkPrereqs() {
    const s = await getSettings();
    if (!s) return;
    els.statFetch.textContent = s.max_jobs_per_run;
    els.statGen.textContent = s.max_drafts_per_run;

    const [criteriaRes, uploadedCount] = await Promise.all([
      fetch("/api/settings/criteria").then((r) => (r.ok ? r.json() : [])).catch(() => []),
      getUploadedCount(),
    ]);
    els.statCriteria.textContent = criteriaRes.length;

    const issues = [];
    if (!s.has_anthropic_key) issues.push("Anthropic API key");
    const hasCvSource = uploadedCount > 0 || (s.github_connected && s.repo_full_name);
    if (!hasCvSource) issues.push("CV source (upload a CV or connect GitHub)");
    if (criteriaRes.length === 0) issues.push("at least one search criteria");
    if (issues.length > 0) {
      els.start.disabled = true;
      showError(`Set up first: ${issues.join(", ")}`, "Visit Settings to configure.");
    }
  }

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && !running) checkPrereqs();
  });
  window.addEventListener("focus", () => {
    if (!running) checkPrereqs();
  });

  els.start.addEventListener("click", async () => {
    if (running) return;
    running = true;
    els.bannerSlot.innerHTML = "";
    hideCompleteCta();
    setBtnRunning();
    const res = await fetch("/api/runs", { method: "POST" });
    if (!res.ok) {
      const body = await res.text();
      showError("Could not start run", body || `HTTP ${res.status}`);
      running = false;
      setBtnIdle();
      return;
    }
    const run = await res.json();
    els._lastLiveIdx = 0;
    els.progress.hidden = false;
    els.headline.textContent = HEADLINES.pending;
    els.sub.textContent = subForStatus({ status: "pending" });
    renderStages("pending");
    renderCounters({ jobs_found: 0, applications_generated: 0, started_at: run.started_at });
    pollTimer = setInterval(() => pollRun(run.id), 2000);
    pollRun(run.id);
  });

  function renderEstimate() {
    if (!els.estimate) return;
    const billing = window.__aiApplyBilling;
    const settings = window.__aiApplySettings;
    if (!billing || !settings) return;
    if (billing.billing_mode === "byok") {
      els.estimate.hidden = true;
      return;
    }
    const modelId = settings.generation_model;
    const model = (settings.available_models || []).find((m) => m.id === modelId);
    if (!model) return;
    const costPerLetter = (model.cost_centitokens || 0) / 100;
    const maxGen = settings.max_drafts_per_run || 0;
    const estimate = +(maxGen * costPerLetter).toFixed(2);
    const balance = billing.token_balance;
    const insufficient = balance < estimate;
    els.estimate.hidden = false;
    els.estimate.classList.toggle("insufficient", insufficient);
    els.estAmount.textContent = formatTokens(estimate);
    const estIcon = document.getElementById("est-icon");
    if (estIcon && !estIcon.innerHTML) estIcon.innerHTML = window.I.sparkles(11);
    els.estMeta.textContent =
      `${maxGen} letters × ${formatTokens(costPerLetter)} tok (${modelFamily(modelId)}) · balance ${formatTokens(balance)}`;
    if (insufficient) {
      els.start.disabled = true;
      showError(
        `Top up to run (${formatTokens(estimate - balance)} tokens short)`,
        "Or lower Max drafts in Settings, or switch to Haiku."
      );
    }
  }

  (async () => {
    setBtnIdle();
    for (let i = 0; i < 40 && !window.__aiApplyBilling; i++) {
      await new Promise((r) => setTimeout(r, 25));
    }
    if (window.__aiApplyAnonymous) return;
    await checkPrereqs();
    renderEstimate();
    try {
      const res = await fetch("/api/runs");
      if (res.ok) {
        const rows = await res.json();
        const live = rows.find((r) => !["finished", "failed"].includes(r.status));
        if (live) {
          running = true;
          setBtnRunning();
          els.progress.hidden = false;
          pollTimer = setInterval(() => pollRun(live.id), 2000);
          pollRun(live.id);
        }
      }
    } catch {}
  })();
})();
