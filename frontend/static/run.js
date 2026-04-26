(() => {
  "use strict";
  const els = {
    start: document.getElementById("start"),
    status: document.getElementById("status"),
    runStatus: document.getElementById("run-status"),
    recent: document.getElementById("recent"),
  };

  let pollTimer = null;

  function setStatus(message, kind) {
    els.status.textContent = message || "";
    els.status.className = "status" + (kind ? " " + kind : "");
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
    if (!s.has_anthropic_key) issues.push("Anthropic API key");
    if (!s.github_connected) issues.push("GitHub connection");
    if (!s.repo_full_name) issues.push("repo name");
    if (issues.length > 0) {
      els.start.disabled = true;
      setStatus(
        `Set up first: ${issues.join(", ")}. → Settings`,
        "err"
      );
    }
  }

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

  (async () => {
    await new Promise((r) => setTimeout(r, 30));
    if (window.__aiApplyAnonymous) return;
    checkPrereqs();
    loadRecent();
  })();
})();
