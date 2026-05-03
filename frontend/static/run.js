(() => {
  "use strict";
  const els = {
    start: document.getElementById("start"),
    status: document.getElementById("status"),
    runStatus: document.getElementById("run-status"),
    recent: document.getElementById("recent"),
    estimate: document.getElementById("run-estimate"),
    estAmount: document.getElementById("est-amount"),
    estMeta: document.getElementById("est-meta"),
    runControls: document.getElementById("run-controls"),
  };

  let pollTimer = null;

  function setStatus(message, kind) {
    els.status.textContent = message || "";
    els.status.className = "status" + (kind ? " " + kind : "");
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

  async function loadRecent() {
    const res = await fetch("/api/runs");
    if (!res.ok) return;
    const rows = await res.json();
    els.recent.innerHTML = "";
    if (rows.length === 0) {
      els.recent.innerHTML = '<p class="model-blurb">No runs yet.</p>';
      return;
    }
    const ul = document.createElement("ul");
    for (const r of rows) {
      const li = document.createElement("li");
      const dt = new Date(r.started_at).toLocaleString();
      li.textContent = `#${r.id} · ${dt} · ${r.status} · ${r.applications_generated}/${r.jobs_found} drafted` +
        (r.error ? ` · ${r.error}` : "");
      ul.appendChild(li);
    }
    els.recent.appendChild(ul);
  }

  async function pollRun(runId) {
    const res = await fetch(`/api/runs/${runId}`);
    if (!res.ok) return;
    const run = await res.json();
    els.runStatus.textContent =
      `run #${run.id}: ${run.status}` +
      (run.jobs_found ? ` · ${run.applications_generated}/${run.jobs_found} drafted` : "");
    if (["finished", "failed"].includes(run.status)) {
      clearInterval(pollTimer);
      pollTimer = null;
      els.start.disabled = false;
      setStatus(
        run.status === "finished"
          ? `Done. ${run.applications_generated} new application(s) on the Applications page.`
          : `Failed: ${run.error}`,
        run.status === "finished" ? "ok" : "err"
      );
      loadRecent();
    }
  }

  function checkPrereqs() {
    const s = window.__aiApplySettings;
    if (!s) return;
    const issues = [];
    if (!s.github_connected) issues.push("GitHub connection");
    if (!s.repo_full_name) issues.push("repo name");
    // Anthropic key only required in BYOK mode.
    const billing = window.__aiApplyBilling;
    if (billing && billing.billing_mode === "byok" && !s.has_anthropic_key) {
      issues.push("Anthropic API key");
    }
    if (issues.length > 0) {
      els.start.disabled = true;
      setStatus(`Set up first: ${issues.join(", ")}. → Settings`, "err");
    }
  }

  function renderEstimate() {
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
    els.estMeta.textContent =
      `${maxGen} letters × ${formatTokens(costPerLetter)} tok (${modelFamily(modelId)})  ·  balance ${formatTokens(balance)}`;

    if (insufficient) {
      // Replace Run button with a top-up CTA.
      els.runControls.innerHTML = "";
      const cta = document.createElement("a");
      cta.href = "/settings.html#billing";
      cta.className = "btn btn-primary";
      cta.textContent = `+ Top up to run (${formatTokens(estimate - balance)} tokens short)`;
      els.runControls.appendChild(cta);
      const hint = document.createElement("p");
      hint.className = "model-blurb";
      hint.textContent =
        "Or lower Max cover letters per run in Settings, or switch to Haiku.";
      els.runControls.appendChild(hint);
    }
  }

  if (els.start) {
    els.start.addEventListener("click", async () => {
      els.start.disabled = true;
      setStatus("Starting…");
      const res = await fetch("/api/runs", { method: "POST" });
      if (!res.ok) {
        const body = await res.text();
        setStatus(`Could not start: ${body || res.status}`, "err");
        els.start.disabled = false;
        return;
      }
      const run = await res.json();
      setStatus("");
      pollTimer = setInterval(() => pollRun(run.id), 2000);
      pollRun(run.id);
    });
  }

  (async () => {
    // Wait long enough for shell.js to populate __aiApplySettings + __aiApplyBilling.
    for (let i = 0; i < 40 && !window.__aiApplyBilling; i++) {
      await new Promise((r) => setTimeout(r, 25));
    }
    if (window.__aiApplyAnonymous) return;
    checkPrereqs();
    renderEstimate();
    loadRecent();
  })();
})();
