(() => {
  "use strict";

  const els = {
    anthropic: document.getElementById("anthropic-key"),
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
  };

  let modelBlurbs = {};

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
    for (const opt of s.available_models) {
      const o = document.createElement("option");
      o.value = opt.id;
      o.textContent = opt.label;
      if (opt.id === s.generation_model) o.selected = true;
      els.model.appendChild(o);
      modelBlurbs[opt.id] = opt.blurb;
    }
    els.blurb.textContent = modelBlurbs[s.generation_model] || "";
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

  (async () => {
    await new Promise((r) => setTimeout(r, 30));
    if (window.__aiApplyAnonymous) return;
    await loadSettings();
    await loadCriteria();
  })();
})();
