(() => {
  "use strict";

  const form = document.getElementById("email-form");
  const status = document.getElementById("status");
  const submit = form.querySelector("button[type=submit]");

  function setStatus(message, kind) {
    status.textContent = message || "";
    status.className = "status" + (kind ? " " + kind : "");
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    submit.disabled = true;
    setStatus("Signing in…");
    try {
      const res = await fetch("/auth/email/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: form.email.value,
          password: form.password.value,
        }),
      });
      if (res.ok) {
        window.location.href = "/";
        return;
      }
      let detail = `${res.status} ${res.statusText}`;
      try {
        const body = await res.json();
        if (body && body.detail) detail = body.detail;
      } catch { /* not JSON */ }
      setStatus(detail, "err");
    } catch (err) {
      setStatus(err.message || String(err), "err");
    } finally {
      submit.disabled = false;
    }
  });
})();
