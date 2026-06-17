// static/js/fileHandler.js

/**
 * File attachment and upload handling.
 *
 * The picker UX (open dialog → preview chips → dedupe cap → upload progress
 * whirlpool) lives in the reusable `FilePicker` class below. The chat composer
 * drives the default instance bound to `#file-input` / `#attach-strip` /
 * `/api/upload`, and the legacy module-level exports (`openPicker`, `addFiles`,
 * `uploadPending`, `renderAttachStrip`, …) simply delegate to it so existing
 * call sites need no changes.
 *
 * Other surfaces (e.g. the first-run setup wizard's resume + font-file inputs)
 * reuse the SAME chip/preview/progress code by calling `createPicker()` with
 * their own input element, strip element and upload URL — no parallel uploader.
 */

import uiModule from './ui.js';
import spinnerModule from './spinner.js';

const _previewUrls = new WeakMap();

function _getPreviewUrl(f) {
  if (!f) return '';
  let url = _previewUrls.get(f);
  if (!url) {
    url = URL.createObjectURL(f);
    _previewUrls.set(f, url);
  }
  return url;
}

function _revokePreviewUrl(f) {
  const url = _previewUrls.get(f);
  if (url) {
    try { URL.revokeObjectURL(url); } catch (_) {}
    _previewUrls.delete(f);
  }
}

const MAX_VISIBLE = 3;
const MAX_EXPAND = 6;   // beyond this, the badge stays collapsed (too many chips to preview)
const MAX_FILES = 10;

/**
 * A self-contained file picker bound to one `<input type=file>` + one preview
 * strip + one upload endpoint. Holds the picker/preview/progress/dedupe logic
 * that used to live as module globals so it can be reused on any surface.
 *
 * @param {Object} opts
 * @param {string|HTMLElement} [opts.inputEl]  file input (id string or node)
 * @param {string|HTMLElement} [opts.stripEl]  preview strip (id string or node)
 * @param {string} [opts.uploadUrl='/api/upload']  POST target for uploadPending()
 * @param {string} [opts.fieldName='files']  multipart field name
 * @param {number} [opts.maxFiles=MAX_FILES]  cap (1 ⇒ single-file picker)
 * @param {string} [opts.apiBase='']  prefix prepended to uploadUrl
 */
export class FilePicker {
  constructor(opts = {}) {
    this.pendingFiles = [];
    this.uploaded = [];
    this._lastUploadedMeta = [];
    this._uploadSpinners = [];
    this._expanded = false;
    this._inputRef = opts.inputEl || 'file-input';
    this._stripRef = opts.stripEl || 'attach-strip';
    this.uploadUrl = opts.uploadUrl || '/api/upload';
    this.fieldName = opts.fieldName || 'files';
    this.maxFiles = opts.maxFiles || MAX_FILES;
    this.apiBase = opts.apiBase || '';
    // Extra multipart fields posted alongside the file(s) on uploadPending()
    // (e.g. the font name for /fonts/install). Plain object of name → value.
    this.extraFields = opts.extraFields || null;
    this.onChange = typeof opts.onChange === 'function' ? opts.onChange : null;
  }

  _input() {
    return typeof this._inputRef === 'string'
      ? document.getElementById(this._inputRef) : this._inputRef;
  }

  _strip() {
    return typeof this._stripRef === 'string'
      ? document.getElementById(this._stripRef) : this._stripRef;
  }

  /** Open file picker dialog */
  openPicker() {
    const input = this._input();
    if (input) input.click();
  }

  /**
   * Render the attachment strip with pending files.
   * 1-3 files: show individual chips.
   * 4+  files: collapse into a single "N files" badge (click to expand).
   */
  renderAttachStrip() {
    const strip = this._strip();
    if (!strip) return;

    while (strip.firstChild) strip.removeChild(strip.firstChild);
    if (this.pendingFiles.length === 0) {
      this._expanded = false;
      if (window._updateSendBtnIcon) window._updateSendBtnIcon();
      return;
    }

    const total = this.pendingFiles.length;
    const collapsed = total > MAX_VISIBLE && !this._expanded;

    if (collapsed) {
      // Single compact badge: "5 files ×"
      const badge = document.createElement('div');
      badge.className = 'thumb thumb-collapsed';
      const label = document.createElement('span');
      label.textContent = total + ' file' + (total > 1 ? 's' : '');
      label.className = 'thumb-collapsed-label';
      badge.appendChild(label);
      badge.title = this.pendingFiles.map(f => f.name || 'pasted-image').join('\n');
      const canExpand = total <= MAX_EXPAND;
      badge.style.cursor = canExpand ? 'pointer' : 'default';
      badge.addEventListener('click', (e) => {
        if (e.target.closest('.thumb-collapsed-x')) return;
        if (!canExpand) return;   // too many files — don't expand into chips
        this._expanded = true;
        this.renderAttachStrip();
      });
      const x = document.createElement('button');
      x.className = 'thumb-collapsed-x';
      x.textContent = '×';
      x.title = 'Remove all';
      x.addEventListener('click', (e) => { e.stopPropagation(); this.clearPending(); });
      badge.appendChild(x);
      strip.appendChild(badge);
    } else {
      // Show individual chips
      for (let idx = 0; idx < total; idx++) {
        strip.appendChild(this._createChip(this.pendingFiles[idx], idx));
      }
    }
    if (window._updateSendBtnIcon) window._updateSendBtnIcon();
  }

  _createChip(f, idx) {
    const chip = document.createElement('div');
    chip.className = 'thumb';
    const isImage = f.type?.startsWith('image/') || /\.(png|jpg|jpeg|gif|webp|svg|bmp)$/i.test(f.name || '');
    if (isImage) {
      chip.classList.add('thumb-image');  // lets CSS overlay the remove-X on the corner (mobile)
      const img = document.createElement('img');
      img.className = 'thumb-img';
      img.src = _getPreviewUrl(f);
      img.alt = f.name || 'image';
      chip.appendChild(img);
    } else {
      const span = document.createElement('span');
      span.textContent = f.name || 'pasted-image';
      chip.appendChild(span);
    }
    const x = document.createElement('button');
    x.textContent = '×';
    x.setAttribute('aria-label', 'Remove attachment');
    x.addEventListener('click', (e) => { e.stopPropagation(); this.removePending(idx); });
    chip.appendChild(x);
    return chip;
  }

  /** Remove a pending file by index */
  removePending(idx) {
    _revokePreviewUrl(this.pendingFiles[idx]);
    this.pendingFiles.splice(idx, 1);
    this.renderAttachStrip();
    if (this.onChange) try { this.onChange(this); } catch (_) {}
  }

  /** Upload all pending files to server */
  async uploadPending() {
    if (this.pendingFiles.length === 0) return [];

    // The message bubble is shown immediately, but the upload can take a moment —
    // dim the chips and overlay a whirlpool so it's clear the files are still
    // being sent (and aren't stuck). Cleared in the finally below.
    const strip = this._strip();
    if (strip) {
      strip.classList.add('attach-uploading');
      // Put a whirlpool ON each attachment chip (image/doc) so the spinner sits on
      // the thing being uploaded, not floating over the whole strip.
      strip.querySelectorAll('.thumb').forEach(chip => {
        try {
          const sp = spinnerModule.create('', 'clean', 'whirlpool');
          const ov = document.createElement('span');
          ov.className = 'thumb-upload-spinner';
          ov.appendChild(sp.createElement());
          chip.appendChild(ov);
          sp.start();
          this._uploadSpinners.push(sp);
        } catch (_) { /* spinner is best-effort */ }
      });
    }

    const fd = new FormData();
    this.pendingFiles.forEach(f => fd.append(this.fieldName, f, f.name || 'paste.png'));
    if (this.extraFields) {
      for (const [k, v] of Object.entries(this.extraFields)) fd.append(k, v);
    }

    try {
      const res = await fetch(`${this.apiBase}${this.uploadUrl}`, {
        method: 'POST',
        credentials: 'same-origin',
        body: fd,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = (data && (data.detail || data.message)) || `Upload failed (${res.status})`;
        throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
      }
      this.uploaded = (data.files || []);
      this.pendingFiles = [];     // clear only on success
      // Stash the full meta (incl. width/height for images) so callers that want
      // it can grab it via getLastUploadedMeta(). Keep the returned shape as
      // `ids` for backward-compatibility with existing call sites; the raw server
      // payload is also returned so non-chat callers (wizard) can read it.
      this._lastUploadedMeta = this.uploaded;
      this._lastResponse = data;
      return this.uploaded.map(x => x.id);
    } finally {
      this._uploadSpinners.forEach(sp => { try { sp.stop && sp.stop(); } catch (_) {} });
      this._uploadSpinners = [];
      if (strip) strip.classList.remove('attach-uploading');
      // Re-render: empty on success (chips gone), or restored on error so the
      // user can retry — and either way the spinners are removed.
      this.renderAttachStrip();
    }
  }

  /** The raw JSON from the most recent uploadPending() (for non-chat callers). */
  getLastResponse() { return this._lastResponse || null; }

  /** Add files to pending list (capped at maxFiles) */
  addFiles(files) {
    // Single-file pickers (maxFiles === 1) replace the current selection rather
    // than rejecting the new one.
    if (this.maxFiles === 1) this.clearPending();
    for (const f of files) {
      if (this.pendingFiles.length >= this.maxFiles) {
        _showToast(`Max ${this.maxFiles} file${this.maxFiles > 1 ? 's' : ''} allowed`);
        break;
      }
      this.pendingFiles.push(f);
    }
    this.renderAttachStrip();
    if (this.onChange) try { this.onChange(this); } catch (_) {}
  }

  getPendingCount() { return this.pendingFiles.length; }

  /** Raw pending File objects (for reading content before upload clears them) */
  getPendingRaw() { return [...this.pendingFiles]; }

  /** Pending file metadata (name, size, type, previewUrl) for display */
  getPendingInfo() {
    return this.pendingFiles.map(f => {
      const isImage = f.type?.startsWith('image/') || /\.(png|jpg|jpeg|gif|webp|svg|bmp)$/i.test(f.name || '');
      return {
        name: f.name || 'pasted-image',
        size: f.size || 0,
        mime: f.type || '',
        previewUrl: isImage ? _getPreviewUrl(f) : '',
      };
    });
  }

  /** Clear all pending files */
  clearPending() {
    this.pendingFiles.forEach(_revokePreviewUrl);
    this.pendingFiles = [];
    this.renderAttachStrip();
  }

  /** Full meta (incl. width/height for images) from the most recent uploadPending(). */
  getLastUploadedMeta() { return this._lastUploadedMeta; }
}

function _showToast(msg) {
  if (window.showToast) { window.showToast(msg); return; }
  // Fallback inline toast
  let t = document.getElementById('_attach-toast');
  if (!t) {
    t = document.createElement('div');
    t.id = '_attach-toast';
    t.style.cssText = 'position:fixed;bottom:16px;left:50%;transform:translateX(-50%);background:var(--panel);border:1px solid var(--red);color:var(--red);padding:6px 14px;border-radius:6px;font-size:13px;z-index:9999;opacity:0;transition:opacity .3s';
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.style.opacity = '1';
  clearTimeout(t._timer);
  t._timer = setTimeout(() => { t.style.opacity = '0'; }, 2500);
}

/**
 * Build a fresh, isolated picker bound to a caller-supplied input + strip + URL.
 * Used by surfaces other than the chat composer (e.g. the setup wizard).
 */
export function createPicker(opts) {
  return new FilePicker(opts);
}

// ── chat composer default instance ──────────────────────────────────────────
// The chat composer keeps its existing API; these thin shims delegate to one
// shared FilePicker bound to the chat's `#file-input` / `#attach-strip` /
// `/api/upload` so chat.js (and every other legacy call site) is unchanged.

const _default = new FilePicker({
  inputEl: 'file-input',
  stripEl: 'attach-strip',
  uploadUrl: '/api/upload',
  fieldName: 'files',
});

/** Initialize the chat default with an API base. */
export function init(apiBase) { _default.apiBase = apiBase || ''; }
export function openPicker() { return _default.openPicker(); }
export function renderAttachStrip() { return _default.renderAttachStrip(); }
export function removePending(idx) { return _default.removePending(idx); }
export function uploadPending() { return _default.uploadPending(); }
export function addFiles(files) { return _default.addFiles(files); }
export function getPendingCount() { return _default.getPendingCount(); }
export function getPendingRaw() { return _default.getPendingRaw(); }
export function getPendingInfo() { return _default.getPendingInfo(); }
export function clearPending() { return _default.clearPending(); }
export function getLastUploadedMeta() { return _default.getLastUploadedMeta(); }

const fileHandlerModule = {
  init,
  createPicker,
  FilePicker,
  openPicker,
  renderAttachStrip,
  removePending,
  uploadPending,
  addFiles,
  getPendingCount,
  getPendingInfo,
  getPendingRaw,
  clearPending,
  getLastUploadedMeta,
};

export default fileHandlerModule;
