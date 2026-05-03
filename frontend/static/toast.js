// Tiny toast utility shared across pages.
// Use: window.toast({ variant: "success" | "info", title, message, duration })
(() => {
  "use strict";

  let host = null;
  function getHost() {
    if (host) return host;
    host = document.createElement("div");
    host.className = "toast-stack";
    document.body.appendChild(host);
    return host;
  }

  window.toast = function (opts) {
    const o = Object.assign(
      { variant: "info", title: "", message: "", duration: 5000 },
      opts || {}
    );
    const el = document.createElement("div");
    el.className = "toast " + o.variant;

    const body = document.createElement("div");
    body.style.flex = "1";
    const t = document.createElement("div");
    t.className = "toast-title";
    t.textContent = o.title;
    body.appendChild(t);
    if (o.message) {
      const m = document.createElement("div");
      m.className = "toast-message";
      m.textContent = o.message;
      body.appendChild(m);
    }
    el.appendChild(body);

    const close = document.createElement("button");
    close.className = "toast-close";
    close.setAttribute("aria-label", "Dismiss");
    close.textContent = "×";
    close.addEventListener("click", () => el.remove());
    el.appendChild(close);

    getHost().appendChild(el);
    setTimeout(() => el.remove(), o.duration);
  };

  // Stripe checkout return — fire once on page load if the URL has the
  // ?billing=success / ?billing=cancelled query param, then strip it so
  // a refresh doesn't replay the toast.
  (() => {
    const params = new URLSearchParams(window.location.search);
    const billing = params.get("billing");
    if (!billing) return;
    const fire = () => {
      if (billing === "success") {
        window.toast({
          variant: "success",
          title: "Payment successful",
          message: "Your tokens are on the way — they'll appear in your balance shortly.",
          duration: 6000,
        });
      } else if (billing === "cancelled" || billing === "canceled") {
        window.toast({
          variant: "info",
          title: "Checkout cancelled",
          message: "No worries — no charges were made. You can pick a pack any time.",
          duration: 5000,
        });
      }
    };
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fire);
    } else {
      fire();
    }
    const url = new URL(window.location.href);
    url.searchParams.delete("billing");
    url.searchParams.delete("session_id");
    window.history.replaceState({}, "", url.toString());
  })();
})();
