// Port of website/apply.js for the ai-apply web app.
// Differences from the original:
//   - Loads from /api/applications (auth'd) instead of a static manifest.
//   - English-only at v1 (no Korean tailored-CV branch).
//   - Edits POST to /api/applications/:id (PATCH) before mark-sent.
(() => {
  "use strict";

  const els = {
    card: document.getElementById("card"),
    empty: document.getElementById("empty"),
    error: document.getElementById("error"),
    errorDetail: document.getElementById("error-detail"),
    counter: document.getElementById("counter"),
    companyRole: document.getElementById("company-role"),
    cvLine: document.getElementById("cv-line"),
    cvName: document.getElementById("cv-name"),
    meta: document.getElementById("meta"),
    jobLink: document.getElementById("job-link"),
    letter: document.getElementById("letter"),
    copy: document.getElementById("copy"),
    download: document.getElementById("download"),
    skip: document.getElementById("skip"),
    save: document.getElementById("save"),
    markSent: document.getElementById("mark-sent"),
    prev: document.getElementById("prev"),
    next: document.getElementById("next"),
    status: document.getElementById("status"),
    printArea: document.getElementById("print-area"),
  };

  const SOURCE_LABELS = {
    au: "Open on Seek",
    nz: "Open on Seek NZ",
    wanted: "Open on Wanted",
  };

  const state = { items: [], cursor: 0, detailCache: new Map() };

  function showStatus(message, kind) {
    els.status.textContent = message || "";
    els.status.className = "status" + (kind ? " " + kind : "");
    if (message) {
      clearTimeout(showStatus._timer);
      showStatus._timer = setTimeout(() => {
        els.status.textContent = "";
        els.status.className = "status";
      }, 2500);
    }
  }

  function showError(detail) {
    els.card.hidden = true;
    els.empty.hidden = true;
    els.error.hidden = false;
    if (detail) els.errorDetail.textContent = detail;
  }

  async function fetchDetail(id) {
    if (state.detailCache.has(id)) return state.detailCache.get(id);
    const res = await fetch(`/api/applications/${id}`);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const detail = await res.json();
    state.detailCache.set(id, detail);
    return detail;
  }

  async function render() {
    if (state.items.length === 0) {
      els.card.hidden = true;
      els.empty.hidden = false;
      els.counter.textContent = "0 of 0";
      return;
    }
    els.empty.hidden = true;
    els.card.hidden = false;

    const item = state.items[state.cursor];
    const title = [item.company, item.title].filter(Boolean).join(" — ");
    els.companyRole.textContent = title || `application ${item.id}`;

    if (item.recommended_cv) {
      els.cvLine.hidden = false;
      els.cvName.textContent = item.recommended_cv;
    } else {
      els.cvLine.hidden = true;
    }

    els.meta.innerHTML = "";
    for (const part of [item.location, SOURCE_LABELS[item.source] || ""].filter(Boolean)) {
      const span = document.createElement("span");
      span.textContent = part;
      els.meta.appendChild(span);
    }

    if (item.url) {
      els.jobLink.href = item.url;
      els.jobLink.textContent = (SOURCE_LABELS[item.source] || "Open job posting") + " ↗";
      els.jobLink.style.pointerEvents = "";
    } else {
      els.jobLink.removeAttribute("href");
      els.jobLink.style.pointerEvents = "none";
    }

    try {
      const detail = await fetchDetail(item.id);
      els.letter.value = detail.edited_body_md ?? detail.body_md ?? "";
    } catch (err) {
      els.letter.value = "";
      showStatus("Could not load body: " + err.message, "err");
    }

    els.counter.textContent = `${state.cursor + 1} of ${state.items.length} unsent`;
  }

  function advance(delta) {
    if (state.items.length === 0) return;
    state.cursor = (state.cursor + delta + state.items.length) % state.items.length;
    render();
  }

  async function save() {
    const item = state.items[state.cursor];
    if (!item) return;
    els.save.disabled = true;
    try {
      const res = await fetch(`/api/applications/${item.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ edited_body_md: els.letter.value }),
      });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const detail = await res.json();
      state.detailCache.set(item.id, detail);
      showStatus("Saved", "ok");
    } catch (err) {
      showStatus("Save failed: " + err.message, "err");
    } finally {
      els.save.disabled = false;
    }
  }

  async function markSent() {
    const item = state.items[state.cursor];
    if (!item) return;
    els.markSent.disabled = true;
    els.skip.disabled = true;
    try {
      // Persist edits first.
      await fetch(`/api/applications/${item.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ edited_body_md: els.letter.value }),
      });
      const res = await fetch(`/api/applications/${item.id}/mark-sent`, { method: "POST" });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      state.items.splice(state.cursor, 1);
      if (state.cursor >= state.items.length) state.cursor = 0;
      render();
      showStatus("Marked sent", "ok");
    } catch (err) {
      showStatus("Mark sent failed: " + err.message, "err");
    } finally {
      els.markSent.disabled = false;
      els.skip.disabled = false;
    }
  }

  async function skip() {
    const item = state.items[state.cursor];
    if (!item) return;
    try {
      await fetch(`/api/applications/${item.id}/skip`, { method: "POST" });
      state.items.splice(state.cursor, 1);
      if (state.cursor >= state.items.length) state.cursor = 0;
      render();
    } catch (err) {
      showStatus("Skip failed: " + err.message, "err");
    }
  }

  async function copyText() {
    try {
      await navigator.clipboard.writeText(els.letter.value);
      showStatus("Copied", "ok");
    } catch (err) {
      els.letter.focus();
      els.letter.select();
      showStatus("Select & copy manually", "err");
    }
  }

  function downloadPdf() {
    const item = state.items[state.cursor];
    if (!item) return;
    const header = [item.company, item.title].filter(Boolean).join(" — ");
    els.printArea.innerHTML = "";
    if (header) {
      const h = document.createElement("div");
      h.className = "print-header";
      h.textContent = header;
      els.printArea.appendChild(h);
    }
    const body = document.createElement("div");
    body.textContent = els.letter.value;
    els.printArea.appendChild(body);
    setTimeout(() => window.print(), 50);
  }

  function wire() {
    els.copy.addEventListener("click", copyText);
    els.download.addEventListener("click", downloadPdf);
    els.markSent.addEventListener("click", markSent);
    els.skip.addEventListener("click", skip);
    els.save.addEventListener("click", save);
    els.next.addEventListener("click", () => advance(1));
    els.prev.addEventListener("click", () => advance(-1));
  }

  async function init() {
    // shell.js sets __aiApplyAnonymous if /api/settings returned 401.
    // Wait one tick for it to run.
    await new Promise((r) => setTimeout(r, 30));
    if (window.__aiApplyAnonymous) return;
    wire();
    try {
      const res = await fetch("/api/applications?status=unsent");
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      state.items = await res.json();
    } catch (err) {
      showError(err.message || String(err));
      return;
    }
    render();
  }

  init();
})();
