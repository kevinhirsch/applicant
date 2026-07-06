// static/js/applicantMind.js
//
// "What the assistant remembers" + "Saved playbooks" + learning curation
// approvals + a bulk "tell it about yourself" import box + "What you've told it"
// — the FR-MIND agent-learning substrate surfaced in the front door. ADDITIVE and
// self-contained: it opens its own modal panel, talks to the engine through the
// workspace proxy at /api/applicant/mind/* (plus /api/applicant/memory/ingest for
// the bulk import box, which forwards to the engine's attribute-cloud
// reconciliation, and /api/applicant/memory/feedback-history for the
// feedback-history section, which forwards to the engine's
// FeedbackSummaryProvider read-model), and never touches the native Brain modal
// (memory.js / skills.js / entities.js) or its data.
//
// Reachability: the engine owns the logic (/api/agent-memory/*, /api/feedback/*);
// this is a thin view over the owner-scoped proxy. The panel is reachable from the
// Brain modal (a "What the assistant remembers" button is appended when present)
// and from a global (window.applicantMindModule.openApplicantMind) for deep-links.
// When the engine is unreachable / no model is connected we render a graceful note
// instead of erroring, matching the rest of the Applicant front door.

import uiModule from './ui.js';
import { esc, _toast, _fetchJSON, _post, errText, loadingHTML, errorHTML, wireRetry } from './applicantCore.js';
import { registerRoute, setHash, clearHash } from './hashRouter.js';

const API = '/api/applicant/mind';
// Bulk observation reconciliation ("tell it about yourself", dark-engine audit
// #42) and feedback history (dark-engine audit #23) both ride on the
// attribute-cloud/memory proxy, not the agent-memory one above — they forward to
// the engine's FeedbackService.ingest_parsed_input / FeedbackSummaryProvider via
// routes/applicant_memory_routes.py's /ingest and /feedback-history endpoints.
const MEMORY_API = '/api/applicant/memory';

let _modalEl = null;
let _modalA11yCleanup = null;





// --- modal shell -----------------------------------------------------------

function _ensureModalEl() {
  if (_modalEl) return _modalEl;
  const el = document.createElement('div');
  el.id = 'applicant-mind-modal';
  // Item #48 (a11y-driven visual fix): `initModalA11y` (called from openApplicantMind)
  // moves focus to the FIRST focusable node inside this element. Without a tabindex
  // here, that node was the Close button (the first <button> in the markup, since the
  // body content loads async) — so Close silently grabbed initial focus and picked up
  // the shared system-blue focus-visible ring on every open, reading as the one
  // primary CTA even though it's a dismiss. Giving the dialog itself a tabindex makes
  // IT the first focusable node instead — a neutral outline on the panel, not a
  // colored ring on Close.
  el.style.cssText = 'position:fixed;inset:0;z-index:1200;display:none;align-items:center;'
    + 'justify-content:center;background:rgba(0,0,0,0.45);';
  el.innerHTML = `
    <div class="admin-card" role="dialog" aria-modal="true" aria-labelledby="applicant-mind-title"
         tabindex="0"
         style="width:min(720px,94vw);max-height:88vh;overflow:auto;padding:18px;">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
        <h3 id="applicant-mind-title" style="margin:0;font-size:16px;">What I remember</h3>
        <button type="button" class="cal-btn applicant-mind-close" aria-label="Close">Close</button>
      </div>
      <div class="applicant-mind-body" style="font-size:13px;max-width:66ch;margin:0 auto;"></div>
    </div>`;
  document.body.appendChild(el);
  el.addEventListener('click', (ev) => { if (ev.target === el) _close(); });
  el.querySelector('.applicant-mind-close').addEventListener('click', _close);
  _modalEl = el;
  return el;
}

function _close() {
  if (_modalA11yCleanup) { _modalA11yCleanup(); _modalA11yCleanup = null; }
  if (_modalEl) {
    _modalEl.style.display = 'none';
    // micro-interactions audit #94: every sibling modal also toggles the
    // shared `.hidden` class alongside its display state — Mind used to set
    // only the inline style, so any code path that reopens via
    // `classList.remove('hidden')` (matching the other surfaces' convention)
    // would leave it invisible. Keep both in sync.
    _modalEl.classList.add('hidden');
  }
  // Hash routing (audit #7): only clears when the hash is actually ours.
  clearHash('mind');
}

// Exported so other modules/tests can close Mind without reaching into its
// private state, mirroring openApplicantMind's public export.
export function closeApplicantMind() {
  _close();
}

function _body() {
  return _ensureModalEl().querySelector('.applicant-mind-body');
}

function _renderOffline() {
  _body().innerHTML = `
    <div class="memory-empty" style="padding:18px;text-align:center;opacity:0.85;">
      Connect a model in Settings or the setup wizard, and I'll start remembering
      what I learn.
    </div>`;
}

// --- bulk observation import ("tell it about yourself") --------------------
// dark-engine audit #42: FeedbackService.ingest_parsed_input's list path
// reconciles a whole batch of facts in one call — auto-apply non-integral,
// hold integral for confirmation, surface conflicts, skip sensitive (EEO).
// This box is the paste-anything front door for that bulk path (the existing
// "Add a detail" form in Settings/Profile stays the one-at-a-time path).

function _parseObservationLines(text) {
  // One fact per line: "Name: value" or "Name = value". Lines without a
  // recognizable separator, or with an empty name/value, are silently
  // skipped (matches the engine's own reconcile_inputs — it skips any
  // observation lacking a name or value rather than erroring the batch).
  const observations = [];
  const skippedLines = [];
  String(text || '').split('\n').forEach((raw) => {
    const line = raw.trim();
    if (!line) return;
    const m = line.match(/^([^:=]+)[:=](.+)$/);
    if (!m) { skippedLines.push(line); return; }
    const name = m[1].trim();
    const value = m[2].trim();
    if (!name || !value) { skippedLines.push(line); return; }
    observations.push({ name, value, source: 'paste' });
  });
  return { observations, skippedLines };
}

function _renderIngestBox() {
  return `
    <div class="memory-section applicant-mind-ingest" style="margin-bottom:18px;">
      <h4 style="margin:0 0 6px;">Tell me about yourself</h4>
      <div style="opacity:0.75;font-size:12px;margin-bottom:6px;">
        Paste anything — one detail per line, like <code>Location: Austin, TX</code>
        or <code>Years of Python: 8</code>. Each line is checked against what I
        already know: new details are saved, changes to a core detail
        wait for your OK, and sensitive details (like EEO fields) are always
        skipped here — type those in directly instead.
      </div>
      <textarea class="applicant-mind-ingest-input" rows="4"
        placeholder="Location: Austin, TX&#10;Years of Python: 8&#10;Portfolio: https://me.dev"
        style="width:100%;box-sizing:border-box;resize:vertical;font:inherit;
        padding:8px;border:1px solid var(--border,#3334);border-radius:8px;"></textarea>
      <div style="display:flex;justify-content:flex-end;margin-top:6px;">
        <button type="button" class="cal-btn applicant-mind-ingest-submit">Import</button>
      </div>
      <div class="applicant-mind-ingest-result" style="margin-top:8px;"></div>
    </div>`;
}

function _ingestGroup(title, hint, items, render) {
  if (!items.length) return '';
  return `<div style="margin-top:6px;">
    <div style="font-weight:600;">${esc(title)}</div>
    <div style="opacity:0.7;font-size:11px;margin-bottom:2px;">${esc(hint)}</div>
    <ul style="margin:2px 0 0;padding-left:18px;">${items.map(render).join('')}</ul>
  </div>`;
}

function _renderIngestResult(result, skippedLines) {
  const applied = result.applied || [];
  const pending = result.pending || [];
  const conflicts = result.conflicts || [];
  const skipped = result.skipped || [];
  if (!applied.length && !pending.length && !conflicts.length && !skipped.length && !skippedLines.length) {
    return `<div class="memory-empty" style="opacity:0.7;">
      Nothing usable in that paste — try one detail per line, like "Location: Austin, TX".</div>`;
  }
  const parts = [
    _ingestGroup('Saved', 'Applied right away.', applied, (n) => `<li>${esc(n)}</li>`),
    _ingestGroup('Waiting for your review', 'A core detail — approve or reject it in the Portal.', pending,
      (p) => `<li>${esc(p.name)}: “${esc(p.proposed_value)}”${p.current_value ? ` (currently “${esc(p.current_value)}”)` : ''}</li>`),
    _ingestGroup('Conflicts with what you already told it', 'Left as-is — nothing was overwritten.', conflicts,
      (p) => `<li>${esc(p.name)}: kept “${esc(p.current_value)}”, pasted “${esc(p.proposed_value)}”</li>`),
    _ingestGroup('Skipped (sensitive)', 'Type these in directly instead of pasting.', skipped, (n) => `<li>${esc(n)}</li>`),
  ];
  if (skippedLines.length) {
    parts.push(_ingestGroup('Not understood', 'No "name: value" pattern found on these lines.',
      skippedLines, (l) => `<li>${esc(l)}</li>`));
  }
  return parts.join('');
}

function _wireIngestBox() {
  const body = _body();
  const input = body.querySelector('.applicant-mind-ingest-input');
  const submit = body.querySelector('.applicant-mind-ingest-submit');
  const resultEl = body.querySelector('.applicant-mind-ingest-result');
  if (!input || !submit || !resultEl) return;
  submit.addEventListener('click', async () => {
    const { observations, skippedLines } = _parseObservationLines(input.value);
    if (!observations.length) {
      resultEl.innerHTML = `<div class="memory-empty" style="opacity:0.7;">
        Nothing to import yet — add at least one line like "Location: Austin, TX".</div>`;
      return;
    }
    submit.disabled = true;
    try {
      const result = await _post(`${MEMORY_API}/ingest`, { observations });
      resultEl.innerHTML = _renderIngestResult(result, skippedLines);
      input.value = '';
      _toast('Imported');
    } catch (e) {
      resultEl.innerHTML = `<div class="memory-empty" style="opacity:0.7;">${esc(errText(e) || 'Could not import that.')}</div>`;
    } finally {
      submit.disabled = false;
    }
  });
}

// --- section renderers -----------------------------------------------------

function _renderMemory(snap) {
  const env = (snap.environment || []);
  const usr = (snap.user || []);
  // Each line carries a stable ref so its "Forget" button can target exactly it.
  const line = (e) => `
    <li class="memory-item" data-mem-ref="${esc(e.ref || '')}" data-mem-text="${esc(e.text)}"
        style="display:flex;align-items:flex-start;justify-content:space-between;gap:8px;
        list-style:none;margin:4px 0;padding:2px 0;">
      <span style="flex:1;">${esc(e.text)}</span>
      <button type="button" class="cal-btn applicant-mind-forget"
          data-ref="${esc(e.ref || '')}" data-text="${esc(e.text)}"
          title="I'll forget this note"
          style="font-size:11px;opacity:0.85;">Forget</button>
    </li>`;
  const block = (title, items, hint) => {
    const body = items.length
      ? `<ul style="margin:6px 0 0;padding-left:0;">${items.map(line).join('')}</ul>`
      : `<div class="memory-empty" style="opacity:0.7;padding:6px 0;">${esc(hint)}</div>`;
    return `<div class="memory-section" style="margin-bottom:14px;">
      <div style="font-weight:600;">${esc(title)}</div>${body}</div>`;
  };
  return block('Lessons about the work', env,
      'Nothing remembered about the work yet — as the assistant handles applications, '
      + 'the lessons it picks up along the way will show up here.')
    + block('Your preferences', usr,
      'No preferences captured yet — tell the assistant what you like or want changed '
      + 'as you go, and it will remember here.');
}

function _renderSkills(skills) {
  const items = (skills.items || []);
  if (!items.length) {
    return `<div class="memory-empty" style="opacity:0.7;padding:6px 0;">
      No saved playbooks yet. I write these as I learn from my own work.</div>`;
  }
  return `<ul style="margin:6px 0 0;padding-left:0;list-style:none;">` + items.map((s) => `
    <li class="memory-item og-card applicant-mind-skill" data-skill="${esc(s.name)}" tabindex="0"
        role="button" aria-expanded="false" title="Open this playbook"
        style="border:1px solid var(--border,#3334);border-radius:8px;
        padding:8px 10px;margin:6px 0;cursor:pointer;">
      <div style="font-weight:600;">
        <span class="applicant-mind-skill-chevron" aria-hidden="true" style="display:inline-block;width:1em;opacity:0.6;">▸</span>
        ${esc(s.name)}
      </div>
      <div style="opacity:0.85;">${esc(s.description || '')}</div>
      ${s.when_to_use ? `<div style="opacity:0.7;margin-top:2px;">When: ${esc(s.when_to_use)}</div>` : ''}
      <div class="applicant-mind-skill-body" style="display:none;margin-top:8px;"></div>
    </li>`).join('') + `</ul>`;
}

function _renderSkillBody(skill) {
  const list = (title, arr) => {
    const items = (arr || []).filter(Boolean);
    if (!items.length) return '';
    return `<div style="margin-top:6px;"><div style="font-weight:600;">${esc(title)}</div>
      <ul style="margin:4px 0 0;padding-left:18px;">${items.map((x) => `<li>${esc(x)}</li>`).join('')}</ul></div>`;
  };
  const when = skill.when_to_use
    ? `<div style="margin-top:6px;"><span style="font-weight:600;">When to use:</span> ${esc(skill.when_to_use)}</div>`
    : '';
  const body = when + list('Procedure', skill.procedure)
    + list('Pitfalls', skill.pitfalls) + list('How I check it worked', skill.verification);
  return body || `<div style="opacity:0.7;">No further detail saved for this playbook yet.</div>`;
}

function _renderCuration(curation) {
  const items = (curation.items || []);
  if (!items.length) {
    return `<div class="memory-empty" style="opacity:0.7;padding:6px 0;">
      Nothing waiting for your review. New suggestions appear here before anything is saved.</div>`;
  }
  return `<ul style="margin:6px 0 0;padding-left:0;list-style:none;">` + items.map((p) => {
    const summary = p.type === 'skill'
      ? `${esc(p.label || 'Save a playbook')}: <b>${esc(p.name)}</b> — ${esc(p.description || '')}`
      : `${esc(p.label || 'Something to remember')}: ${esc(p.text || '')}`;
    const flag = p.claims_authority
      ? `<div style="color:var(--danger,#c0392b);margin-top:2px;">
           Heads up: this note mentions acting on its own. It's only a suggestion — I won't do
           anything without your say-so.</div>`
      : '';
    return `<li class="memory-item og-card" data-proposal-id="${esc(p.id)}"
        style="border:1px solid var(--border,#3334);border-radius:8px;padding:8px 10px;margin:6px 0;">
      <div>${summary}</div>${flag}
      <div style="display:flex;gap:8px;margin-top:8px;">
        <button type="button" class="cal-btn applicant-mind-approve" data-id="${esc(p.id)}"
            title="Save this — I’ll remember it and use it going forward">Approve</button>
        <button type="button" class="cal-btn applicant-mind-deny" data-id="${esc(p.id)}"
            title="Throw this away — I won’t remember it or change anything because of it">Dismiss</button>
      </div></li>`;
  }).join('') + `</ul>`;
}

function _renderLessons(data) {
  // #44 (dark-engine audit, Reflexion): a verbal lesson the loop distilled from a
  // real pre-fill failure on a given job site (ATS), recalled before its next fill
  // attempt there. Grouped by ATS, mirroring the saved-playbook list above.
  const grouped = (data && data.lessons) || {};
  const atsKeys = Object.keys(grouped).sort();
  if (!atsKeys.length) {
    return `<div class="memory-empty" style="opacity:0.7;padding:6px 0;">
      No lessons learned yet — when a pre-fill attempt runs into trouble on a job
      site, what I figure out gets remembered here for next time.</div>`;
  }
  return `<ul style="margin:6px 0 0;padding-left:0;list-style:none;">` + atsKeys.map((ats) => {
    const items = grouped[ats] || [];
    const rows = items.map((l) => `<li style="margin:4px 0;">${esc(l.lesson || '')}</li>`).join('');
    return `<li class="memory-item og-card" style="border:1px solid var(--border,#3334);
        border-radius:8px;padding:8px 10px;margin:6px 0;">
      <div style="font-weight:600;">${esc(ats)}</div>
      <ul style="margin:4px 0 0;padding-left:18px;opacity:0.9;">${rows}</ul>
    </li>`;
  }).join('') + `</ul>`;
}

function _renderRoutines(data) {
  // #45 (dark-engine audit, AWM self-improvement flywheel): after a successful
  // pre-fill on a given job site (ATS) the assistant induces a reusable routine —
  // the compact step-sequence that worked, keyed by site — so the next application
  // to that site is guided by it instead of starting from scratch. Sorted by the
  // engine (most reliable first); rendered as a simple list, mirroring the
  // lessons-learned panel above.
  const rows = (data && data.routines) || [];
  if (!rows.length) {
    return `<div class="memory-empty" style="opacity:0.7;padding:6px 0;">
      No routines learned yet — after I successfully fill out an
      application on a job site, the steps that worked get remembered here so the
      next application to that site goes faster.</div>`;
  }
  return `<ul style="margin:6px 0 0;padding-left:0;list-style:none;">` + rows.map((r) => {
    const steps = Number(r.step_count || 0);
    const wins = Number(r.successes || 0);
    const losses = Number(r.failures || 0);
    return `<li class="memory-item og-card" style="border:1px solid var(--border,#3334);
        border-radius:8px;padding:8px 10px;margin:6px 0;
        display:flex;align-items:center;justify-content:space-between;gap:8px;">
      <div>
        <div style="font-weight:600;">${esc(r.domain || '')}</div>
        <div style="opacity:0.7;">${steps} remembered step${steps === 1 ? '' : 's'}</div>
      </div>
      <div style="opacity:0.8;white-space:nowrap;" title="Times reused successfully vs. not">
        ${wins} worked / ${losses} didn’t
      </div>
    </li>`;
  }).join('') + `</ul>`;
}

function _renderFeedbackHistory(data) {
  // #23 (dark-engine audit): feedback was write-only — the user could tell the
  // assistant things (decline a match with a reason, redline a generated résumé/
  // answer) but never see what actually stuck. This reads back exactly those two
  // kinds of stated feedback, newest-shaped list first (the engine returns them in
  // storage order; no re-sorting here so this stays a faithful mirror of the read).
  const items = (data && data.items) || [];
  if (!items.length) {
    return `<div class="memory-empty" style="opacity:0.7;padding:6px 0;">
      Nothing recorded yet — when you decline a match with a reason, or redline a
      generated résumé or answer, what you told me shows up here.</div>`;
  }
  return `<ul style="margin:6px 0 0;padding-left:0;list-style:none;">` + items.map((f) => {
    const kindLabel = f.kind === 'decline' ? 'You declined a match' : 'You revised a document';
    return `<li class="memory-item og-card" style="border:1px solid var(--border,#3334);
        border-radius:8px;padding:8px 10px;margin:6px 0;">
      <div style="font-weight:600;">${esc(kindLabel)}</div>
      <div style="opacity:0.9;margin-top:2px;">${esc(f.text || '')}</div>
    </li>`;
  }).join('') + `</ul>`;
}

// --- ACE playbooks (dark-engine audit item 46) ------------------------------
// A curated, per-ATS set of strategy bullets kept current via structured
// add/revise/retire deltas (PlaybookService.apply_deltas) instead of a
// wholesale rewrite — distinct from the free-text "Saved playbooks" above
// (those are chat-authored skills). There is no cheap "every ATS" read (a
// playbook is a per-domain artifact keyed by whatever ATS the assistant has
// curated one for), so this is loaded on demand by domain, mirroring the
// lessons panel's per-ATS shape but with a real write path: the audit trail
// shows exactly which add/revise/retire deltas were applied and when.

function _renderPlaybookShell() {
  return `
    <div class="applicant-mind-playbook">
      <div style="opacity:0.75;font-size:12px;margin-bottom:6px;">
        Look up the curated playbook for a job site to see its strategies and the
        history of changes applied to it, or apply a new one.
      </div>
      <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
        <input type="text" class="applicant-mind-playbook-ats" placeholder="Job site, e.g. workday.com"
          style="flex:1;min-width:160px;padding:6px 8px;border:1px solid var(--border,#3334);
          border-radius:6px;font:inherit;">
        <button type="button" class="cal-btn applicant-mind-playbook-load">Load</button>
      </div>
      <div class="applicant-mind-playbook-result" style="margin-top:10px;"></div>
    </div>`;
}

function _renderPlaybookEntries(ats, data) {
  const entries = (data && data.entries) || [];
  const audit = (data && data.audit) || [];
  const entryRows = entries.length
    ? `<ul style="margin:6px 0 0;padding-left:0;list-style:none;">` + entries.map((e) => `
        <li class="memory-item og-card" style="border:1px solid var(--border,#3334);
            border-radius:8px;padding:6px 8px;margin:4px 0;">
          <div><b>${esc(e.key)}</b> <span style="opacity:0.6;">(revision ${esc(String(e.revision))})</span></div>
          <div style="opacity:0.9;">${esc(e.text)}</div>
        </li>`).join('') + `</ul>`
    : `<div class="memory-empty" style="opacity:0.7;padding:6px 0;">
        No curated strategies for ${esc(ats)} yet.</div>`;
  const auditRows = audit.length
    ? `<ul style="margin:6px 0 0;padding-left:18px;opacity:0.8;font-size:12px;">`
      + audit.slice().reverse().map((a) => `<li>${esc(a.op)} “${esc(a.key)}”${a.text ? `: ${esc(a.text)}` : ''}</li>`).join('')
      + `</ul>`
    : `<div style="opacity:0.6;font-size:12px;">No changes recorded yet.</div>`;
  return `
    <div style="font-weight:600;margin-top:6px;">Strategies for ${esc(ats)}</div>
    ${entryRows}
    <div style="font-weight:600;margin-top:10px;">Audit trail</div>
    ${auditRows}
    <div style="font-weight:600;margin-top:10px;">Apply a change</div>
    <div class="applicant-mind-playbook-form" style="display:flex;gap:6px;flex-wrap:wrap;margin-top:4px;">
      <select class="applicant-mind-playbook-op"
        style="padding:6px;border:1px solid var(--border,#3334);border-radius:6px;font:inherit;">
        <option value="add">Add</option>
        <option value="revise">Revise</option>
        <option value="retire">Retire</option>
      </select>
      <input type="text" class="applicant-mind-playbook-key" placeholder="Strategy key"
        style="flex:1;min-width:120px;padding:6px 8px;border:1px solid var(--border,#3334);
        border-radius:6px;font:inherit;">
      <input type="text" class="applicant-mind-playbook-text" placeholder="Strategy text (add / revise only)"
        style="flex:2;min-width:180px;padding:6px 8px;border:1px solid var(--border,#3334);
        border-radius:6px;font:inherit;">
      <button type="button" class="cal-btn applicant-mind-playbook-apply">Apply</button>
    </div>`;
}

async function _loadPlaybook(ats) {
  const resultEl = _body().querySelector('.applicant-mind-playbook-result');
  if (!resultEl) return;
  // micro-interactions cross-cutting rule (busy/disabled guard on in-flight
  // actions): the Load button had no guard, so an impatient double-click (or
  // click during the apply-triggered reload) could stack two fetches.
  const loadBtn = _body().querySelector('.applicant-mind-playbook-load');
  if (loadBtn) loadBtn.disabled = true;
  resultEl.innerHTML = '<div style="opacity:0.7;">Loading…</div>';
  try {
    const data = await _fetchJSON(`${API}/playbooks/${encodeURIComponent(ats)}`);
    resultEl.innerHTML = _renderPlaybookEntries(ats, data);
    _wirePlaybookApply(ats);
  } catch (e) {
    resultEl.innerHTML = `<div style="opacity:0.7;">${esc(errText(e) || 'Could not load that playbook.')}</div>`;
  } finally {
    if (loadBtn) loadBtn.disabled = false;
  }
}

function _wirePlaybookApply(ats) {
  const body = _body();
  const btn = body.querySelector('.applicant-mind-playbook-apply');
  if (!btn) return;
  btn.addEventListener('click', async () => {
    const op = body.querySelector('.applicant-mind-playbook-op').value;
    const key = (body.querySelector('.applicant-mind-playbook-key').value || '').trim();
    const text = (body.querySelector('.applicant-mind-playbook-text').value || '').trim();
    if (!key) { _toast('Give the strategy a key first.'); return; }
    btn.disabled = true;
    try {
      await _post(`${API}/playbooks/${encodeURIComponent(ats)}/apply-deltas`, {
        deltas: [{ op, key, text }],
      });
      _toast('Playbook updated');
      await _loadPlaybook(ats);
    } catch (e) {
      _toast(errText(e) || 'Could not update that playbook.');
    } finally {
      btn.disabled = false;
    }
  });
}

function _wirePlaybookBox() {
  const body = _body();
  const input = body.querySelector('.applicant-mind-playbook-ats');
  const loadBtn = body.querySelector('.applicant-mind-playbook-load');
  if (!input || !loadBtn) return;
  const load = () => {
    const ats = (input.value || '').trim();
    if (!ats) { _toast('Type a job site to look up first.'); return; }
    _loadPlaybook(ats);
  };
  loadBtn.addEventListener('click', load);
  input.addEventListener('keydown', (ev) => {
    // micro-interactions audit #15 (cross-cutting IME guard): don't submit on
    // the Enter that merely commits an IME composition (CJK / dead-key input).
    if (ev.isComposing || ev.keyCode === 229) return;
    if (ev.key === 'Enter') { ev.preventDefault(); load(); }
  });
}

// Same async confirm shape as applicantVault.js's `_confirm()` / applicantRemote.js's
// `_confirm()`: uiModule.styledConfirm with a window.confirm fallback.
async function _confirm(message, opts) {
  try {
    if (uiModule.styledConfirm) return await uiModule.styledConfirm(message, opts);
  } catch { /* fall through */ }
  try { return window.confirm(message); } catch { return false; }
}

// Removes the acted-on `<li>` in place instead of tearing down and re-fetching
// the whole modal (micro-interactions audit #38) — every approve/deny/forget
// used to `await openApplicantMind()`, re-running all six section fetches,
// resetting scroll, and collapsing every expanded playbook row.
function _removeMindRow(btn) {
  const row = btn.closest('li');
  if (row) row.remove();
}

function _wireCurationButtons() {
  const body = _body();
  body.querySelectorAll('.applicant-mind-approve').forEach((btn) => {
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      try {
        await _post(`${API}/curation/${encodeURIComponent(btn.dataset.id)}/approve`);
        _toast('Saved');
        _removeMindRow(btn);
      } catch (e) {
        _toast(errText(e) || 'Could not save that.');
        btn.disabled = false;
      }
    });
  });
  body.querySelectorAll('.applicant-mind-deny').forEach((btn) => {
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      try {
        await _post(`${API}/curation/${encodeURIComponent(btn.dataset.id)}/deny`);
        _toast('Dismissed');
        _removeMindRow(btn);
      } catch (e) {
        _toast(errText(e) || 'Could not dismiss that.');
        btn.disabled = false;
      }
    });
  });
}

function _wireForgetButtons() {
  const body = _body();
  body.querySelectorAll('.applicant-mind-forget').forEach((btn) => {
    btn.addEventListener('click', async (ev) => {
      ev.stopPropagation();
      const text = btn.dataset.text || '';
      // Confirm first — a forget is a real change to what I remember. Routed
      // through the shared styled dialog (micro-interactions audit #76)
      // instead of the native window.confirm every neighbouring flow avoids.
      const ok = await _confirm(`Forget this note? I'll stop using it and it won't come back.\n\n${text}`,
        { confirmText: 'Forget it', cancelText: 'Cancel', danger: true });
      if (!ok) return;
      btn.disabled = true;
      try {
        const ref = btn.dataset.ref || '';
        const payload = ref ? { ref } : { text };
        const res = await _fetchJSON(`${API}/forget`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        // Honest feedback: the engine may apply now or stage for approval. Only
        // remove the row when it is actually gone — a staged forget is still
        // in memory until approved elsewhere, so leave it visible (it will
        // reflect correctly the next time this modal is opened fresh).
        if (res && res.staged) {
          _toast('Sent to your review queue — approve it to forget this.');
        } else {
          _toast('Forgotten');
          _removeMindRow(btn);
        }
      } catch (e) {
        _toast(errText(e) || 'Could not forget that.');
        btn.disabled = false;
      }
    });
  });
}

// micro-interactions audit #70: nothing communicated open/closed state on
// these rows, visually or to AT — sync both the chevron glyph and
// `aria-expanded` whenever a row's expansion state changes.
function _setSkillRowExpanded(row, expanded) {
  row.setAttribute('aria-expanded', String(expanded));
  const chevron = row.querySelector('.applicant-mind-skill-chevron');
  if (chevron) chevron.textContent = expanded ? '▾' : '▸';
}

function _wireSkillRows() {
  const body = _body();
  body.querySelectorAll('.applicant-mind-skill').forEach((row) => {
    const open = async () => {
      const slot = row.querySelector('.applicant-mind-skill-body');
      if (!slot) return;
      // Toggle: collapse if already open.
      if (slot.style.display !== 'none' && slot.dataset.loaded === '1') {
        slot.style.display = 'none';
        _setSkillRowExpanded(row, false);
        return;
      }
      if (slot.dataset.loaded === '1') { slot.style.display = 'block'; _setSkillRowExpanded(row, true); return; }
      slot.style.display = 'block';
      _setSkillRowExpanded(row, true);
      slot.innerHTML = '<div style="opacity:0.7;">Loading…</div>';
      try {
        const skill = await _fetchJSON(`${API}/skills/${encodeURIComponent(row.dataset.skill)}`);
        slot.innerHTML = _renderSkillBody(skill);
        slot.dataset.loaded = '1';
      } catch (e) {
        slot.innerHTML = `<div style="opacity:0.7;">${esc(errText(e) || 'Could not open that playbook.')}</div>`;
      }
    };
    row.addEventListener('click', open);
    row.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); open(); }
    });
  });
}

// --- open ------------------------------------------------------------------

export async function openApplicantMind(opts) {
  const el = _ensureModalEl();
  el.style.display = 'flex';
  el.classList.remove('hidden');
  if (!(opts && opts.skipHashUpdate)) setHash('mind');
  if (_modalA11yCleanup) _modalA11yCleanup();
  _modalA11yCleanup = uiModule.initModalA11y(el, _close);
  // a11y-deep audit #12 / micro-interactions audit #81: reuse the shared
  // spinner kit instead of a bare "Loading…" div, matching every other
  // applicant surface.
  _body().innerHTML = loadingHTML();
  let status;
  try {
    status = await _fetchJSON(`${API}/status`);
  } catch (e) {
    // micro-interactions audit #79: a genuine auth/network failure talking to
    // the workspace backend is not the same thing as "no model connected" —
    // don't collapse both into the connect-a-model gate.
    if (e && e.kind === 'auth') {
      _body().innerHTML = errorHTML(errText(e));
      wireRetry(_body(), () => openApplicantMind(opts));
    } else {
      _renderOffline();
    }
    return;
  }
  if (!status.engine_available) { _renderOffline(); return; }
  try {
    const [snap, skills, curation, lessons, routines, feedbackHistory] = await Promise.all([
      _fetchJSON(`${API}/memory`).catch(() => ({ environment: [], user: [] })),
      _fetchJSON(`${API}/skills`).catch(() => ({ items: [] })),
      _fetchJSON(`${API}/curation`).catch(() => ({ items: [] })),
      _fetchJSON(`${API}/lessons`).catch(() => ({ lessons: {} })),
      _fetchJSON(`${API}/routines`).catch(() => ({ routines: [] })),
      _fetchJSON(`${MEMORY_API}/feedback-history`).catch(() => ({ items: [] })),
    ]);
    _body().innerHTML = `
      ${_renderIngestBox()}
      <div class="memory-section" style="margin-bottom:18px;">
        <h4 style="margin:0 0 6px;">Waiting for your review</h4>
        ${_renderCuration(curation)}
      </div>
      <div class="memory-section" style="margin-bottom:18px;">
        <!-- Item #62: was "What the assistant remembers" again — the dialog's own
             title already says that; this inner section needs its own, distinct
             label rather than repeating the header. -->
        <h4 style="margin:0 0 6px;">Memory</h4>
        ${_renderMemory(snap)}
      </div>
      <div class="memory-section" style="margin-bottom:18px;">
        <h4 style="margin:0 0 6px;">Saved playbooks</h4>
        <div style="opacity:0.75;font-size:12px;margin-bottom:6px;">
          A playbook is a set of steps I write for myself after working through something
          tricky — I check the relevant one before doing similar work again, so I don’t
          have to relearn the same lesson twice.
        </div>
        ${_renderSkills(skills)}
      </div>
      <div class="memory-section" style="margin-bottom:18px;">
        <h4 style="margin:0 0 6px;">Lessons learned from job sites</h4>
        ${_renderLessons(lessons)}
      </div>
      <div class="memory-section" style="margin-bottom:18px;">
        <h4 style="margin:0 0 6px;">Learned site routines</h4>
        ${_renderRoutines(routines)}
      </div>
      <div class="memory-section" style="margin-bottom:18px;">
        <h4 style="margin:0 0 6px;">What you've told it</h4>
        ${_renderFeedbackHistory(feedbackHistory)}
      </div>
      <div class="memory-section">
        <h4 style="margin:0 0 6px;">Curated strategies by job site</h4>
        ${_renderPlaybookShell()}
      </div>`;
    _wireIngestBox();
    _wireCurationButtons();
    _wireForgetButtons();
    _wireSkillRows();
    _wirePlaybookBox();
  } catch (e) {
    // 401 / engine unreachable — degrade to the connect-a-model note.
    _renderOffline();
  }
}

// --- launcher --------------------------------------------------------------

function _wireLauncher() {
  // Add a discreet entry point inside the Brain modal (the existing memory
  // surface) without hijacking its own launcher. We append a button once.
  const host = document.getElementById('memory-modal') || document.body;
  if (!host || host._applicantMindWired) return;
  const anchor = document.querySelector('#memory-modal h4') || null;
  if (anchor && !document.getElementById('applicant-mind-open-btn')) {
    const btn = document.createElement('button');
    btn.id = 'applicant-mind-open-btn';
    btn.type = 'button';
    btn.className = 'cal-btn';
    btn.textContent = 'What I remember';
    btn.style.cssText = 'margin-left:10px;font-size:12px;';
    btn.addEventListener('click', openApplicantMind);
    anchor.appendChild(btn);
    host._applicantMindWired = true;
  }
}

function _boot() {
  _wireLauncher();
  let tries = 0;
  const iv = setInterval(() => {
    tries += 1;
    _wireLauncher();
    if (document.getElementById('applicant-mind-open-btn') || tries > 20) clearInterval(iv);
  }, 500);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _boot);
} else {
  _boot();
}

// Hash routing (audit #7): '#mind' deep-links straight into "What the
// assistant remembers" — a refresh/shared-link/back-forward on that hash
// opens/closes it. Registered at module-eval time (runs as soon as app.js's
// dynamic import resolves, well before app.js calls
// hashRouter.initHashRouting()).
registerRoute('mind', { open: openApplicantMind, close: _close });

const applicantMindModule = { openApplicantMind, closeApplicantMind };
try { window.applicantMindModule = applicantMindModule; } catch { /* no-op */ }

export default applicantMindModule;
