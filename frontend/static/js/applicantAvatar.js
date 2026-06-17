// Applicant account avatar (feature G27) — paints the user's finalized casting headshot into the
// little circle profile pic(s): the sidebar user bar (#user-bar-avatar) and the Settings
// account card (#settings-account-avatar). When no avatar image exists the app's initial-letter
// fallback shows through (we only ADD a background image + hide the glyph). It updates the
// moment a headshot is finalized, via the `applicant:avatarchanged` event. Fail-open, Vault-safe
// (reads only the user's own /api/applicant/avatar).
(function () {
  "use strict";

  const TARGETS = ["user-bar-avatar", "settings-account-avatar"];

  function ensureCss() {
    if (document.getElementById("applicant-avatar-css")) return;
    const s = document.createElement("style");
    s.id = "applicant-avatar-css";
    // font-size:0 hides the initial glyph without !important (the compound selector wins).
    s.textContent =
      ".user-bar-avatar.ow-has-avatar,.ow-has-avatar{background-size:cover;background-position:center;font-size:0}";
    document.head.appendChild(s);
  }

  async function apply() {
    let present = false;
    try {
      const r = await fetch("/api/applicant/avatar", { credentials: "same-origin", cache: "no-store" });
      present = r.ok;
    } catch (_) { present = false; }
    const url = present ? "/api/applicant/avatar?t=" + Date.now() : null;
    TARGETS.forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      if (url) { el.style.backgroundImage = `url("${url}")`; el.classList.add("ow-has-avatar"); }
      else { el.style.backgroundImage = ""; el.classList.remove("ow-has-avatar"); }
    });
  }

  window.ApplicantAvatar = { refresh: apply };
  // A finalized headshot dispatches this — the circle updates immediately.
  window.addEventListener("applicant:avatarchanged", apply);

  const boot = () => { ensureCss(); apply(); setTimeout(apply, 1200); }; // re-apply after app.js paints the initial
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, { once: true });
  else boot();
})();
