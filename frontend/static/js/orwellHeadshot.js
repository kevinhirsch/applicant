// Orwell headshot studio (features G26/G27/G28) — the player's OWN portrait + account avatar.
//
// Make your houseguest's portrait (and your account profile pic) from a photo of yourself:
//   • exact  — your photo, cropped to your face, used as-is (no AI);
//   • studio — AI recreates you in the house style; you GENERATE 3 OPTIONS AT A TIME and pick
//              one, regenerate for a fresh set (indefinitely), or upload a different photo.
// Finalizing sets it as your houseguest portrait AND your account avatar (the circle updates at
// once, via `orwell:avatarchanged`).
//
// The STUDIO (`window.OrwellHeadshotStudio.mount(bodyEl)`) is reusable — the pre-game casting
// card mounts it (game-build, state.started===false), and Settings → Account mounts the same
// thing (G28). Vault-safe: only the player's own image, never game state. Fail-open.
(function () {
  "use strict";

  const ID = "orwell-headshot";
  const ready = (fn) =>
    document.readyState === "loading"
      ? document.addEventListener("DOMContentLoaded", fn, { once: true })
      : fn();

  async function jget(url) {
    try { const r = await fetch(url, { credentials: "same-origin" }); return r.ok ? r.json() : null; }
    catch (_) { return null; }
  }

  function ensureCss() {
    if (document.getElementById("orwell-headshot-css")) return;
    const s = document.createElement("style");
    s.id = "orwell-headshot-css";
    s.textContent = `
      #${ID} { margin: 0 auto 8px; max-width: 760px; width: 100%;
        border: 1px solid var(--border, #355a66); border-radius: 10px;
        background: color-mix(in srgb, var(--panel, #1b1f27) 92%, transparent);
        font-size: 13px; overflow: hidden; }
      #${ID} .hs-head { display: flex; align-items: center; gap: 8px; cursor: pointer;
        padding: 8px 12px; user-select: none; color: var(--fg, #cfd8e3); }
      #${ID} .hs-head .hs-chev { margin-left: auto; opacity: .6; transition: transform .15s; }
      #${ID}.hs-open .hs-head .hs-chev { transform: rotate(90deg); }
      #${ID} .hs-body { display: none; padding: 4px 12px 12px; }
      #${ID}.hs-open .hs-body { display: block; }
      /* the studio body — shared by the casting card AND Settings (scoped to the class) */
      .ow-headshot-studio { font-size: 13px; }
      .ow-headshot-studio .hs-msg { opacity: .75; font-size: 12px; }
      .ow-headshot-studio .hs-actions { display: flex; gap: 8px; align-items: center; margin-top: 10px; flex-wrap: wrap; }
      .ow-headshot-studio .hs-btn { font: inherit; font-size: 12.5px; padding: 6px 12px; border-radius: 8px; cursor: pointer;
        background: var(--brand-color, var(--accent, #4a9)); color: var(--bg, #111); border: 1px solid transparent; font-weight: 600; }
      .ow-headshot-studio .hs-btn[disabled] { opacity: .5; cursor: default; }
      .ow-headshot-studio .hs-btn-ghost { background: transparent; color: var(--fg, #cfd8e3); border-color: var(--border, #355a66); font-weight: 400; }
      .ow-headshot-studio .hs-preview { width: 92px; height: 92px; border-radius: 8px; flex: none;
        border: 1px solid var(--border, #355a66); background: #0d0f14 center/cover no-repeat;
        display: flex; align-items: center; justify-content: center; font-size: 28px; opacity: .85; }
      .ow-headshot-studio .hs-row { display: flex; gap: 12px; align-items: flex-start; flex-wrap: wrap; }
      .ow-headshot-studio .hs-opts { flex: 1; min-width: 220px; display: flex; flex-direction: column; gap: 8px; }
      .ow-headshot-studio .hs-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 6px 0 2px; }
      .ow-headshot-studio .hs-cand { position: relative; aspect-ratio: 1; border-radius: 8px; overflow: hidden; cursor: pointer;
        border: 2px solid transparent; background: #0d0f14 center/cover no-repeat; }
      .ow-headshot-studio .hs-cand.sel { border-color: var(--brand-color, var(--accent, #4a9)); }
      .ow-headshot-studio .hs-cand img { width: 100%; height: 100%; object-fit: cover; display: block; }
      .ow-headshot-studio .hs-lib { margin-bottom: 12px; padding-bottom: 10px; border-bottom: 1px solid var(--border, #355a66); }
      .ow-headshot-studio .hs-libstrip { display: flex; gap: 8px; flex-wrap: wrap; }
      .ow-headshot-studio .hs-libitem { position: relative; width: 56px; height: 56px; border-radius: 8px; overflow: hidden; cursor: pointer;
        border: 2px solid transparent; background: #0d0f14 center/cover no-repeat; flex: none; }
      .ow-headshot-studio .hs-libitem.cur { border-color: var(--brand-color, var(--accent, #4a9)); }
      .ow-headshot-studio .hs-libitem img { width: 100%; height: 100%; object-fit: cover; display: block; }
      .ow-headshot-studio .hs-libdel { position: absolute; top: 1px; right: 1px; width: 16px; height: 16px; line-height: 14px;
        border-radius: 50%; border: none; cursor: pointer; font-size: 12px; padding: 0;
        background: rgba(0,0,0,.6); color: #fff; opacity: 0; transition: opacity .12s; }
      .ow-headshot-studio .hs-libitem:hover .hs-libdel { opacity: 1; }
      @media (prefers-reduced-motion: reduce) { #${ID} .hs-head .hs-chev, .ow-headshot-studio .hs-libdel { transition: none; } }`;
    document.head.appendChild(s);
  }

  function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

  // ── the reusable studio: mount the state machine into any container ─────────
  // opts.onSummary(text) — optional, for a host that shows a status chip (the casting card).
  function buildStudio(body, opts) {
    ensureCss();
    opts = opts || {};
    body.classList.add("ow-headshot-studio");

    const st = { file: null, fileUrl: null, candidates: [], selected: null, busy: false, library: [] };
    let _msg = "";
    let status = { present: false, finalized: false, mode: null };
    const msg = (m) => { _msg = m || ""; };
    const setBusy = (b) => { st.busy = b; render(); };
    const summary = (t) => { try { opts.onSummary && opts.onSummary(t); } catch (_) {} };
    function avatarChanged() { try { window.dispatchEvent(new CustomEvent("orwell:avatarchanged")); } catch (_) {} }

    async function upload(mode) {
      if (!st.file) return false;
      setBusy(true);
      try {
        const fd = new FormData(); fd.append("file", st.file); fd.append("mode", mode);
        const r = await fetch("/api/orwell/portrait/intake", { method: "POST", credentials: "same-origin", body: fd });
        const d = r.ok ? await r.json() : null;
        st.busy = false;
        if (!d || !d.ok) { msg(d && d.error ? d.error : "That image couldn't be used — try another."); render(); return false; }
        return true;
      } catch (e) {
        if (window.OrwellReport) window.OrwellReport.fail("headshot", "upload", e);
        st.busy = false; msg("Upload failed — the photo service is offline."); render(); return false;
      }
    }

    async function useExact() {
      const ok = await upload("exact");
      if (ok) { avatarChanged(); st.candidates = []; st.selected = null; await refreshStatus(); }
    }

    async function studioGenerate() {
      if (st.file) { const ok = await upload("reference"); if (!ok) return; st.file = null; }
      setBusy(true); msg("Generating 3 studio options…");
      try {
        const r = await fetch("/api/orwell/portrait/studio/generate", { method: "POST", credentials: "same-origin" });
        const d = r.ok ? await r.json() : null;
        st.busy = false;
        if (d && d.generated > 0) { st.candidates = d.candidates; st.selected = null; msg("Pick your favorite — or generate 3 more."); }
        else { msg((d && d.reason) || "Couldn't generate options — check the image model in Settings."); }
      } catch (e) {
        if (window.OrwellReport) window.OrwellReport.fail("headshot", "studio", e);
        st.busy = false; msg("The photo service is offline right now.");
      }
      render();
    }

    async function finalizeSelected() {
      if (st.selected === null || st.selected === undefined) return;
      setBusy(true);
      try {
        const r = await fetch("/api/orwell/portrait/studio/finalize", {
          method: "POST", credentials: "same-origin",
          headers: { "Content-Type": "application/json" }, body: JSON.stringify({ index: st.selected }) });
        const d = r.ok ? await r.json() : null;
        st.busy = false;
        if (d && d.ok) { avatarChanged(); st.candidates = []; st.selected = null; await refreshStatus(); }
        else { msg("Couldn't set that option — try again."); render(); }
      } catch (e) { st.busy = false; msg("The photo service is offline right now."); render(); }
    }

    async function removeAll() {
      try { await fetch("/api/orwell/portrait/intake", { method: "DELETE", credentials: "same-origin" }); } catch (_) {}
      st.file = null; st.fileUrl = null; st.candidates = []; st.selected = null;
      avatarChanged(); msg("Removed."); await refreshStatus();
    }

    async function refreshStatus() {
      status = (await jget("/api/orwell/portrait/intake")) || status;
      const lib = await jget("/api/orwell/portrait/library");
      st.library = (lib && lib.headshots) || [];
      // G32: a generated-but-unpicked photoset must survive a refresh/new session. The
      // candidate images persist server-side (intake reports the count) — rebuild the picker
      // from that count so the options reappear, instead of dropping to the upload chooser.
      if (!status.finalized && (status.candidates || 0) > 0 && !st.candidates.length) {
        st.candidates = Array.from({ length: status.candidates },
          (_, i) => ({ index: i, ref: "/api/orwell/portrait/studio/candidate/" + i }));
      }
      render();
    }

    // G30: pick a cached headshot — it becomes the current avatar + season portrait.
    async function selectFromLibrary(id) {
      setBusy(true);
      try {
        const r = await fetch("/api/orwell/portrait/library/select", {
          method: "POST", credentials: "same-origin",
          headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id }) });
        st.busy = false;
        if (r.ok) { avatarChanged(); status.finalized = true; await refreshStatus(); }
        else { msg("Couldn't use that one — try again."); render(); }
      } catch (e) { st.busy = false; msg("The photo service is offline right now."); render(); }
    }
    async function deleteFromLibrary(id) {
      try { await fetch("/api/orwell/portrait/library/" + encodeURIComponent(id), { method: "DELETE", credentials: "same-origin" }); } catch (_) {}
      await refreshStatus();
    }

    // The cached-headshots strip — shown above every state so a past portrait is always one tap away.
    function libraryHtml() {
      if (!st.library.length) return "";
      return `<div class="hs-lib"><div class="hs-msg" style="margin-bottom:6px">Your headshots — tap one to use it</div>
        <div class="hs-libstrip">${st.library.map((h) =>
          `<div class="hs-libitem${h.current ? " cur" : ""}" data-pick="${esc(h.id)}" title="${h.current ? "current" : "use this headshot"}">
             <img src="${esc(h.ref)}" alt="headshot"><button type="button" class="hs-libdel" data-del="${esc(h.id)}" title="Remove" aria-label="Remove">×</button></div>`).join("")}</div></div>`;
    }
    function wireLibrary() {
      body.querySelectorAll("[data-pick]").forEach((d) => d.addEventListener("click", (e) => {
        if (e.target && e.target.closest("[data-del]")) return; // the × handles itself
        selectFromLibrary(d.dataset.pick);
      }));
      body.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", (e) => {
        e.stopPropagation(); deleteFromLibrary(b.dataset.del);
      }));
    }

    function render() {
      summary(status.finalized ? "set ✓" : (st.candidates.length ? "pick an option" : "make your portrait"));
      if (st.busy) { body.innerHTML = `<div class="hs-msg">${esc(_msg || "Working…")}</div>`; return; }
      const lib = libraryHtml();

      if (status.finalized) {
        body.innerHTML = lib + `
          <div class="hs-row">
            <div class="hs-preview" style="background-image:url('/api/orwell/avatar?t=${Date.now()}')"></div>
            <div class="hs-opts"><div>Your headshot is set — it's your houseguest portrait and your profile pic.</div>
              <div class="hs-actions">
                <button type="button" class="hs-btn hs-btn-ghost" id="hs-redo">Make another</button>
                <button type="button" class="hs-btn hs-btn-ghost" id="hs-remove">Remove</button>
                <span class="hs-msg">${esc(_msg)}</span>
              </div></div></div>`;
        body.querySelector("#hs-redo").addEventListener("click", () => { status.finalized = false; render(); });
        body.querySelector("#hs-remove").addEventListener("click", removeAll);
        wireLibrary();
        return;
      }

      if (st.candidates.length) {
        body.innerHTML = lib + `
          <div>${esc(_msg || "Pick your favorite — or generate 3 more.")}</div>
          <div class="hs-grid">${st.candidates.map((c) =>
            `<div class="hs-cand${st.selected === c.index ? " sel" : ""}" data-i="${c.index}"><img src="${esc(c.ref)}" alt="option"></div>`).join("")}</div>
          <div class="hs-actions">
            <button type="button" class="hs-btn" id="hs-use" ${st.selected === null ? "disabled" : ""}>Use this one</button>
            <button type="button" class="hs-btn hs-btn-ghost" id="hs-more">Generate 3 more</button>
            <button type="button" class="hs-btn hs-btn-ghost" id="hs-new">Upload a different photo</button>
          </div>`;
        body.querySelectorAll(".hs-cand").forEach((d) => d.addEventListener("click", () => { st.selected = parseInt(d.dataset.i, 10); render(); }));
        body.querySelector("#hs-use").addEventListener("click", finalizeSelected);
        body.querySelector("#hs-more").addEventListener("click", studioGenerate);
        body.querySelector("#hs-new").addEventListener("click", () => { st.candidates = []; st.selected = null; st.file = null; render(); });
        wireLibrary();
        return;
      }

      const previewBg = st.fileUrl ? `style="background-image:url('${st.fileUrl}')"` : "";
      body.innerHTML = lib + `
        <div class="hs-msg" style="margin-bottom:8px">${st.library.length ? "…or make a new one from a photo of yourself." : "Make your houseguest's portrait — and your profile pic — from a photo of yourself."}</div>
        <div class="hs-row">
          <div class="hs-preview" ${previewBg}>${st.fileUrl ? "" : "👤"}</div>
          <div class="hs-opts">
            <input type="file" id="hs-file" accept="image/*" aria-label="Choose a photo of yourself">
            <div class="hs-actions">
              <button type="button" class="hs-btn" id="hs-studio" ${st.file ? "" : "disabled"}>Make AI studio portraits</button>
              <button type="button" class="hs-btn hs-btn-ghost" id="hs-exact" ${st.file ? "" : "disabled"}>Use photo as-is</button>
            </div>
            <div class="hs-msg" id="hs-msg2">${esc(_msg)}</div>
          </div></div>`;
      const fi = body.querySelector("#hs-file");
      fi.addEventListener("change", () => {
        st.file = fi.files && fi.files[0];
        if (st.fileUrl) { try { URL.revokeObjectURL(st.fileUrl); } catch (_) {} }
        st.fileUrl = st.file ? URL.createObjectURL(st.file) : null;
        render();
      });
      body.querySelector("#hs-studio").addEventListener("click", studioGenerate);
      body.querySelector("#hs-exact").addEventListener("click", useExact);
      wireLibrary();
    }

    refreshStatus();
    return { refresh: refreshStatus };
  }

  // expose the reusable studio for Settings → Account (G28)
  window.OrwellHeadshotStudio = { mount: buildStudio };

  // ── the pre-game casting card (collapsible host for the studio) ─────────────
  function build() {
    const el = document.createElement("div");
    el.id = ID;
    el.innerHTML = `
      <div class="hs-head" role="button" tabindex="0" aria-expanded="false">
        <span>📷</span><b>Casting headshot</b><span class="hs-msg" id="hs-summary">make your portrait</span>
        <span class="hs-chev">▶</span>
      </div>
      <div class="hs-body" id="hs-body"></div>`;
    return el;
  }

  function wire(el, openByDefault) {
    const head = el.querySelector(".hs-head");
    const summary = el.querySelector("#hs-summary");
    const toggle = () => { const o = el.classList.toggle("hs-open"); head.setAttribute("aria-expanded", o ? "true" : "false"); };
    head.addEventListener("click", toggle);
    head.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
    if (openByDefault) { el.classList.add("hs-open"); head.setAttribute("aria-expanded", "true"); }
    buildStudio(el.querySelector("#hs-body"), { onSummary: (t) => { summary.textContent = t; } });
  }

  function mount() {
    if (document.getElementById(ID)) return;
    const bar = document.querySelector(".chat-input-bar");
    if (!bar || !bar.parentNode) return;
    ensureCss();
    const el = build();
    bar.parentNode.insertBefore(el, bar);
    wire(el, true); // G29: producers push it — the casting card opens expanded, not tucked away
  }
  function unmount() { const el = document.getElementById(ID); if (el) el.remove(); }

  async function route() {
    const gameBuild = document.body && document.body.hasAttribute("data-game-build");
    if (!gameBuild) return;
    const st = await jget("/api/orwell/state");
    if (st && st.started === false) mount(); else unmount();
  }

  window.addEventListener("orwell:gamechanged", route);
  ready(route);
})();
