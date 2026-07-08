// static/js/documentLibrary.js
/**
 * Document Library — modal with Chats / Documents / Research / Archive tabs.
 * Extracted from document.js to reduce file size.
 */

import uiModule from './ui.js';
import sessionModule from './sessions.js';
import spinnerModule from './spinner.js';
import markdownModule from './markdown.js';
import { makeWindowDraggable } from './windowDrag.js';
import { langIcon } from './langIcons.js';
import { ensureSubmittable } from './applicantReachability.js';

// ── Injected references from documentModule ──
let API_BASE = '';
let _esc;          // HTML-escape function
let _getDocs;      // () => Map of open docs
let _isOpenFn;     // () => boolean — is doc panel open
let _createDocument;
let _loadDocument;
let _switchToDoc;
let _openPanel;
let _addDocToTabs;
let _syncDocIndicator;

export function initLibrary(config) {
  API_BASE        = config.apiBase;
  _esc            = config.esc;
  _getDocs        = config.getDocs;
  _isOpenFn       = config.isOpen;
  _createDocument = config.createDocument;
  _loadDocument   = config.loadDocument;
  _switchToDoc    = config.switchToDoc;
  _openPanel      = config.openPanel;
  _addDocToTabs   = config.addDocToTabs;
  _syncDocIndicator = config.syncDocIndicator;
}

// ── Library state ──
let _libraryOpen = false;
// Track which tabs have already played their domino-in cascade so we only
// animate the *first* time content loads per page session — tab swaps and
// re-renders after that are instant.
const _libraryCascadedTabs = new Set();
function _maybeCascadeGrid(grid, tabKey) {
  if (!grid || !tabKey || _libraryCascadedTabs.has(tabKey)) return;
  _libraryCascadedTabs.add(tabKey);
  grid.classList.add('doclib-just-opened');
  setTimeout(() => grid.classList.remove('doclib-just-opened'), 900);
}
let _libraryDocs = [];
let _libraryTotal = 0;
let _libraryOffset = 0;
let _docsVisibleLimit = 20;  // chunked reveal (matches the Chats tab's 20)
let _libraryLanguages = {};
let _librarySessionCount = 0;
let _libraryActiveLanguage = null;
let _librarySort = 'recent';
let _librarySearch = '';
let _librarySearchDebounce = null;

// Highlight the active search terms inside a plain string. Escapes first,
// then wraps each whitespace-separated term in <mark>. Multi-term, matching
// the backend's per-term search, so every word that matched is marked.
function _hlSearch(text) {
  const esc = _esc(text || '');
  const q = (_librarySearch || '').trim();
  if (!q) return esc;
  const toks = [...new Set(q.split(/\s+/).filter(Boolean))]
    .sort((a, b) => b.length - a.length)             // prefer longer matches
    .map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  if (!toks.length) return esc;
  try {
    return esc.replace(new RegExp(`(${toks.join('|')})`, 'gi'),
                       '<mark class="doclib-search-hl">$1</mark>');
  } catch { return esc; }
}
let _libraryEscHandler = null;
let _librarySelectMode = false;
let _librarySelectedIds = new Set();
let _libraryImportMode = false;
let _libScrollBound = false;   // infinite-scroll listener attached once
let _libraryArchivedView = false;   // Documents tab showing archived docs?

// ---- Library animation helpers ----

  /** Collapse an expanded card */
  function _collapseExpandedCard(card) {
    const grid = card.closest('.doclib-grid');
    const instant = card?.dataset?.spaceToggle === '1';
    card.classList.remove('doclib-card-expanded');
    // Release the height lock so grid returns to natural size
    if (grid) {
      grid.style.minHeight = '';
      grid.style.maxHeight = '';
    }
    const reader = card.querySelector('.doclib-card-reader');
    if (reader) reader.remove();

    // Fade siblings back in
    if (grid && !instant) {
      const siblings = [...grid.querySelectorAll('.doclib-card')].filter(c => c !== card);
      siblings.forEach(s => { s.style.opacity = '0'; });
      requestAnimationFrame(() => {
        siblings.forEach(s => {
          s.style.transition = 'opacity 0.15s ease';
          s.style.opacity = '1';
        });
        setTimeout(() => { siblings.forEach(s => { s.style.transition = ''; s.style.opacity = ''; }); }, 200);
      });
    }
  }

  // Fetch a chat's full history and serialize as plain-text transcript,
  // then write to the clipboard. Same User: / Assistant: format the chat
  // header's "Copy Chat" button uses, but works for any session ID — the
  // library doesn't need the chat to be loaded in the UI first.
  async function _copyChatById(sessionId) {
    try {
      const res = await fetch(`${API_BASE}/api/history/${sessionId}`, { credentials: 'same-origin' });
      if (!res.ok) throw new Error(res.statusText);
      const data = await res.json();
      const history = Array.isArray(data) ? data : (data.history || []);
      const lines = [];
      for (const m of history) {
        if (m.role !== 'user' && m.role !== 'assistant') continue;
        const label = m.role === 'user' ? 'User' : 'Assistant';
        const body = (m.content || '')
          .replace(/<think>[\s\S]*?<\/think>/g, '')
          .replace(/<think>[\s\S]*$/, '')
          .trim();
        if (body) lines.push(`${label}: ${body}`);
      }
      const text = lines.join('\n\n');
      if (uiModule && uiModule.copyToClipboard) {
        await uiModule.copyToClipboard(text);
      } else {
        await navigator.clipboard.writeText(text);
      }
    } catch (err) {
      if (uiModule && uiModule.showError) uiModule.showError('Failed to copy chat');
    }
  }

  // Long-press a list card to open its actions menu. `menuSelector` resolves
  // the existing ••• button on the card; on hold we trigger its click so the
  // dropdown opens in its usual spot. Moved finger >10px or release before
  // 500ms cancels.
  function _attachLongPressMenu(card, menuSelector) {
    let hold = null;
    let start = null;
    const cancel = () => { if (hold) { clearTimeout(hold); hold = null; } start = null; };
    card.addEventListener('pointerdown', (e) => {
      if (e.target.closest(menuSelector + ', .memory-select-cb, button')) return;
      start = { x: e.clientX, y: e.clientY };
      hold = setTimeout(() => {
        hold = null;
        card._suppressNextClick = true;
        setTimeout(() => { card._suppressNextClick = false; }, 400);
        if (navigator.vibrate) try { navigator.vibrate(15); } catch {}
        const btn = card.querySelector(menuSelector);
        if (btn) btn.click();
      }, 500);
    });
    card.addEventListener('pointermove', (e) => {
      if (!start) return;
      if (Math.hypot(e.clientX - start.x, e.clientY - start.y) > 10) cancel();
    });
    card.addEventListener('pointerup', cancel);
    card.addEventListener('pointercancel', cancel);
  }

  // Inline icons used by the chats/archive/research dropdown rows. Match the
  // ones used by the documents-tab card menu so the visual language stays
  // consistent across tabs.
  const _LIB_DD_ICONS = {
    open: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>',
    archive: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/><line x1="10" y1="12" x2="14" y2="12"/></svg>',
    restore: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9"/><polyline points="3 4 3 9 8 9"/></svg>',
    delete: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>',
    clone: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>',
    copy: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>',
  };

  function _showLibDropdown(anchor, items, opts) {
    opts = opts || {};
    document.querySelectorAll('._lib-dd').forEach(d => d.remove());
    const dd = document.createElement('div');
    dd.className = 'dropdown session-dropdown-menu _lib-dd';
    for (const item of items) {
      const row = document.createElement('div');
      row.className = 'dropdown-item-compact' + (item.danger ? ' dropdown-item-danger' : '');
      const iconKey = item.icon || item.label.toLowerCase();
      const iconSvg = _LIB_DD_ICONS[iconKey] || '';
      row.innerHTML = (iconSvg ? '<span class="dropdown-icon">' + iconSvg + '</span>' : '') + '<span>' + item.label + '</span>';
      row.addEventListener('click', (e) => { e.stopPropagation(); dd.remove(); item.action(); });
      dd.appendChild(row);
    }
    if (typeof opts.onSelect === 'function') {
      const sel = document.createElement('div');
      sel.className = 'dropdown-item-compact';
      sel.innerHTML =
        '<span class="dropdown-icon"><span style="font-size:16px;line-height:1;position:relative;top:-2px;">●</span></span>'
        + '<span>Select</span>';
      sel.addEventListener('click', (e) => { e.stopPropagation(); dd.remove(); opts.onSelect(); });
      dd.appendChild(sel);
    }
    const cancel = document.createElement('div');
    cancel.className = 'dropdown-item-compact dropdown-cancel-mobile';
    cancel.innerHTML =
      '<span class="dropdown-icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></span>'
      + '<span>Cancel</span>';
    cancel.addEventListener('click', (e) => { e.stopPropagation(); dd.remove(); if (typeof opts.onCancel === 'function') opts.onCancel(); });
    dd.appendChild(cancel);
    document.body.appendChild(dd);
    const rect = anchor.getBoundingClientRect();
    dd.style.right = (window.innerWidth - rect.right) + 'px';
    dd.style.top = (rect.bottom + 2) + 'px';
    dd.style.display = 'block';
    dd.style.zIndex = '100000';
    requestAnimationFrame(() => {
      const mr = dd.getBoundingClientRect();
      if (mr.bottom > window.innerHeight - 8) {
        dd.style.top = (rect.top - mr.height - 2) + 'px';
      }
      if (mr.left < 8) { dd.style.left = '8px'; dd.style.right = 'auto'; }
    });
    const close = (e) => { if (!dd.contains(e.target)) { dd.remove(); document.removeEventListener('click', close); } };
    setTimeout(() => document.addEventListener('click', close), 0);

    // Swipe-down-to-dismiss (mobile). Mirrors the bottom-sheet feel — drag the
    // popup down and release past the threshold to close. Below threshold,
    // snap back. Vertical-only; horizontal flicks fall through to scrolling.
    let _swipeStart = null;
    let _swipeDy = 0;
    dd.addEventListener('touchstart', (e) => {
      if (e.touches.length !== 1) return;
      _swipeStart = { x: e.touches[0].clientX, y: e.touches[0].clientY };
      _swipeDy = 0;
      dd.style.transition = '';
    }, { passive: true });
    dd.addEventListener('touchmove', (e) => {
      if (!_swipeStart || e.touches.length !== 1) return;
      const dx = e.touches[0].clientX - _swipeStart.x;
      const dy = e.touches[0].clientY - _swipeStart.y;
      if (Math.abs(dy) < Math.abs(dx)) { _swipeStart = null; return; }
      if (dy > 0) {
        _swipeDy = dy;
        dd.style.transform = 'translateY(' + dy + 'px)';
        dd.style.opacity = String(Math.max(0.3, 1 - dy / 240));
      }
    }, { passive: true });
    dd.addEventListener('touchend', () => {
      if (!_swipeStart) return;
      _swipeStart = null;
      if (_swipeDy > 60) {
        dd.style.transition = 'transform 0.15s ease, opacity 0.15s ease';
        dd.style.transform = 'translateY(120px)';
        dd.style.opacity = '0';
        setTimeout(() => dd.remove(), 160);
        document.removeEventListener('click', close);
      } else {
        dd.style.transition = 'transform 0.18s ease, opacity 0.18s ease';
        dd.style.transform = '';
        dd.style.opacity = '';
      }
    });
  }

  // ---- Document Library ----

  function libraryRelativeTime(isoString) {
    if (!isoString) return '';
    const now = Date.now();
    const then = new Date(isoString).getTime();
    const diffS = Math.floor((now - then) / 1000);
    if (diffS < 60) return 'just now';
    const diffM = Math.floor(diffS / 60);
    if (diffM < 60) return diffM + 'm ago';
    const diffH = Math.floor(diffM / 60);
    if (diffH < 24) return diffH + 'h ago';
    const diffD = Math.floor(diffH / 24);
    if (diffD === 1) return 'yesterday';
    if (diffD < 14) return diffD + 'd ago';
    const diffW = Math.floor(diffD / 7);
    if (diffW < 8) return diffW + 'w ago';
    return new Date(isoString).toLocaleDateString();
  }

  async function libraryFetch(append) {
    if (!append) _libraryOffset = 0;
    // Bump page size to the backend max (50) so fullscreen doesn't leave
    // empty space below the loaded rows — same idea as emailLibrary's
    // limit=100, but documents_library validates `le=50` so we have to
    // cap at that. Auto-fill loop below picks up any remaining gap.
    const params = new URLSearchParams({
      sort: _librarySort,
      offset: String(_libraryOffset),
      limit: '50',
    });
    if (_librarySearch) params.set('search', _librarySearch);
    if (_libraryActiveLanguage) params.set('language', _libraryActiveLanguage);
    if (_libraryArchivedView) params.set('archived', 'true');

    try {
      const res = await fetch(`${API_BASE}/api/documents/library?${params}`);
      if (!res.ok) throw new Error(res.statusText);
      const data = await res.json();

      if (append) {
        _libraryDocs = _libraryDocs.concat(data.documents);
      } else {
        _libraryDocs = data.documents;
        _docsVisibleLimit = 20;  // reset chunk on a fresh load / search / sort
      }
      _libraryTotal = data.total;
      _libraryLanguages = data.languages;
      _librarySessionCount = data.session_count;

      libraryRenderStats();
      libraryRenderLangChips();
      libraryRenderGrid();
      libraryRenderLoadMore();
    } catch (e) {
      console.error('Library fetch error:', e);
    }
  }

  function libraryRenderStats() {
    const el = document.getElementById('doclib-stats');
    if (!el) return;
    const totalAll = Object.values(_libraryLanguages).reduce((a, b) => a + b, 0);
    if (_librarySearch || _libraryActiveLanguage) {
      el.textContent = `${_libraryTotal} of ${totalAll} document${totalAll !== 1 ? 's' : ''}`;
    } else {
      el.textContent = `${totalAll} document${totalAll !== 1 ? 's' : ''}`;
    }
  }

  function libraryRenderLangChips() {
    const wrap = document.getElementById('doclib-chips');
    if (!wrap) return;
    // Remove only language chip buttons, keep sort/select elements
    wrap.querySelectorAll('.memory-cat-chip').forEach(c => c.remove());
    const totalAll = Object.values(_libraryLanguages).reduce((a, b) => a + b, 0);

    // Hide the "all (0)" chip + lang chips entirely when there are no docs.
    if (totalAll === 0) return;

    const allChip = document.createElement('button');
    allChip.className = 'memory-cat-chip' + (!_libraryActiveLanguage ? ' active' : '');
    allChip.textContent = `all (${totalAll})`;
    allChip.addEventListener('click', () => {
      if (_librarySelectMode) {
        _libraryDocs.forEach(d => _librarySelectedIds.add(d.id));
        libraryUpdateBulkCount();
        const selectAllEl = document.getElementById('doclib-select-all');
        if (selectAllEl) selectAllEl.checked = true;
        libraryRenderGrid();
        return;
      }
      _libraryActiveLanguage = null;
      libraryFetch(false);
    });
    wrap.appendChild(allChip);

    const sorted = Object.entries(_libraryLanguages).sort((a, b) => b[1] - a[1]);
    for (const [lang, count] of sorted) {
      const chip = document.createElement('button');
      chip.className = 'memory-cat-chip' + (_libraryActiveLanguage === lang ? ' active' : '');
      chip.textContent = `${lang} (${count})`;
      chip.addEventListener('click', () => {
        _libraryActiveLanguage = lang;
        libraryFetch(false);
      });
      wrap.appendChild(chip);
    }
  }

  function libraryRenderGrid() {
    const grid = document.getElementById('doclib-grid');
    if (!grid) return;
    grid.innerHTML = '';
    // Drop any previous inline load-more — regenerated below alongside the list.
    if (grid.parentElement) grid.parentElement.querySelectorAll(':scope > .doclib-inline-load-more').forEach(b => b.remove());

    if (_libraryDocs.length === 0) {
      if (_librarySearch || _libraryActiveLanguage) {
        grid.innerHTML = '<div class="doclib-empty">No documents match your search.</div>';
      } else {
        // #136: a proper button as the CTA, not accent-colored underlined
        // link text pretending to be one.
        const _impIco = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-left:5px;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>';
        grid.innerHTML =
          '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;padding:28px 16px;text-align:center;">' +
            '<span class="doclib-empty" style="padding:0;">No documents yet</span>' +
            '<button type="button" class="cal-btn cal-btn-primary" id="doclib-empty-import">Import' + _impIco + '</button>' +
            '<span style="opacity:0.55;font-size:11px;">or create one in a session</span>' +
          '</div>';
        grid.querySelector('#doclib-empty-import')?.addEventListener('click', (e) => {
          e.preventDefault();
          document.getElementById('doclib-import-file-btn')?.click();
        });
      }
      return;
    }
    _maybeCascadeGrid(grid, 'documents');

    // Reveal in 20-at-a-time chunks (matches the Chats tab). The legacy
    // server-pagination button is suppressed in libraryRenderLoadMore; this
    // inline button is the single control.
    const shown = _libraryDocs.slice(0, _docsVisibleLimit);
    for (const doc of shown) {
      grid.appendChild(libraryCreateCard(doc));
    }
    // Show a "Load more" while either more loaded docs remain to reveal, or
    // more exist on the server beyond what we've fetched.
    const shownCount = shown.length;
    if (shownCount < _libraryTotal) {
      const btn = document.createElement('button');
      btn.className = 'doclib-load-more doclib-inline-load-more';
      btn.id = 'doclib-docs-load-more';
      btn.textContent = `Load more (${shownCount} of ${_libraryTotal})`;
      btn.addEventListener('click', async () => {
        _docsVisibleLimit += 20;
        // Need more than we've fetched? pull the next server page first.
        if (_docsVisibleLimit > _libraryDocs.length && _libraryDocs.length < _libraryTotal) {
          _libraryOffset = _libraryDocs.length;
          await libraryFetch(true);  // appends + re-renders
        } else {
          libraryRenderGrid();
        }
      });
      grid.parentElement.appendChild(btn);
    }
  }

  // Infinite scroll for the library (mobile + desktop), covering EVERY tab —
  // Documents, Chats, Research, Archive all render a `.doclib-inline-load-more`
  // button (regenerated fresh each render). A capture-phase scroll listener
  // catches whichever element actually scrolls and, when the visible button
  // nears the viewport bottom, clicks it — reusing each tab's own load logic.
  // We mark a button once clicked so the SAME instance can't double-fire (the
  // next render makes a fresh, unmarked one), which is safe for both the sync
  // reveal tabs (Chats/Research) and the async fetch tabs (Documents/Archive).
  if (!_libScrollBound) {
    _libScrollBound = true;
    let _tick = false;
    const _maybeAutoLoad = () => {
      _tick = false;
      if (!_libraryOpen) return;
      for (const btn of document.querySelectorAll('.doclib-inline-load-more')) {
        if (btn.dataset.autoLoaded) continue;
        if (!btn.offsetParent) continue;   // inactive tab (hidden)
        if (btn.getBoundingClientRect().top > window.innerHeight + 600) continue;
        btn.dataset.autoLoaded = '1';
        btn.click();
        break;   // one load per scroll tick
      }
    };
    document.addEventListener('scroll', () => {
      if (_tick) return;
      _tick = true;
      requestAnimationFrame(_maybeAutoLoad);
    }, true);
  }

  function libraryCreateCard(doc) {
    const card = document.createElement('div');
    card.className = 'doclib-card memory-item ow-list-row';
    card.dataset.docId = doc.id;
    if (_librarySelectMode && _librarySelectedIds.has(doc.id)) {
      card.classList.add('selected');
    }

    // Checkbox for select mode
    if (_librarySelectMode) {
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.className = 'memory-select-cb';
      cb.checked = _librarySelectedIds.has(doc.id);
      cb.addEventListener('click', (e) => e.stopPropagation());
      cb.addEventListener('change', () => {
        libraryToggleSelectItem(doc.id);
        card.classList.toggle('selected', _librarySelectedIds.has(doc.id));
        const selectAllEl = document.getElementById('doclib-select-all');
        if (selectAllEl) selectAllEl.checked = _libraryDocs.every(d => _librarySelectedIds.has(d.id));
      });
      card.appendChild(cb);
    }

    // Content wrapper
    const content = document.createElement('div');
    content.style.cssText = 'flex:1;min-width:0;padding-top:4px;';

    // Title row with version badge
    const titleRow = document.createElement('div');
    titleRow.style.cssText = 'display:flex;align-items:center;gap:6px;width:100%;';
    const titleEl = document.createElement('span');
    titleEl.className = 'memory-item-title';
    titleEl.style.cssText = 'flex:0 1 auto;min-width:0;';
    // Language-specific icon next to the title (matches the document's type:
    // markdown/csv/python/html/etc.). Falls back to the generic document icon
    // when the language has no dedicated glyph.
    const _GEN_DOC_ICON = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px;opacity:0.4;flex-shrink:0;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>';
    const _langSvg = doc.language && doc.language !== 'text'
      ? langIcon(doc.language, 12, { style: 'vertical-align:-2px;margin-right:4px;opacity:0.55;flex-shrink:0;color:currentColor;' })
      : '';
    titleEl.innerHTML = (_langSvg || _GEN_DOC_ICON) + _hlSearch(doc.title || 'Untitled');
    titleRow.appendChild(titleEl);
    const verBadge = document.createElement('span');
    verBadge.style.cssText = 'font-size:9px;padding:1px 6px;border-radius:8px;background:color-mix(in srgb, var(--red) 15%, transparent);border:1px solid color-mix(in srgb, var(--red) 40%, transparent);color:var(--red);flex-shrink:0;';
    verBadge.textContent = 'v' + (doc.version_count || 1);
    titleRow.appendChild(verBadge);
    // Chevron pushed to the right end of the title row — collapsed
    // shows nothing, expanded reveals a downward chevron so the user
    // sees the card is open and can tap to close it.
    const chevron = document.createElement('span');
    chevron.className = 'doclib-card-chevron';
    chevron.style.marginLeft = 'auto';
    chevron.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>';
    titleRow.appendChild(chevron);
    content.appendChild(titleRow);

    // Meta line: session → [lang-icon language] → time
    const meta = document.createElement('div');
    meta.className = 'memory-item-meta';
    meta.style.cssText = 'font-size:10px;opacity:0.55;margin-top:2px;display:flex;align-items:center;gap:6px;flex-wrap:wrap;';
    const _esc = (s) => uiModule.esc(String(s || ''));
    const pieces = [];
    if (doc.session_name) pieces.push(`<span>${_esc(doc.session_name)}</span>`);
    if (doc.language && doc.language !== 'text') {
      const ic = langIcon(doc.language, 11, { style: 'vertical-align:-2px;flex-shrink:0;opacity:0.65;color:currentColor;' });
      pieces.push(`<span style="display:inline-flex;align-items:center;gap:3px;">${ic}${_esc(doc.language)}</span>`);
    }
    pieces.push(`<span>${_esc(libraryRelativeTime(doc.updated_at))}</span>`);
    meta.innerHTML = pieces.join('<span style="opacity:0.5;">\u00b7</span>');
    // Strip the per-language icon from the meta line \u2014 it now sits next to the
    // title above, so duplicating it here was redundant.
    content.appendChild(meta);
    card.appendChild(content);

    // Header element (kept for expand/preview compatibility)
    const header = document.createElement('div');
    header.className = 'doclib-card-header';
    header.style.display = 'none';

    // Action buttons — "..." menu
    const actionsWrap = document.createElement('div');
    actionsWrap.className = 'memory-item-actions';
    const menuWrap = document.createElement('span');
    menuWrap.className = 'doclib-card-menu-wrap';
    menuWrap.style.position = 'relative';
    const menuBtn = document.createElement('button');
    menuBtn.className = 'memory-item-btn';
    menuBtn.title = 'Actions';
    menuBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="12" cy="19" r="2"/></svg>';
    menuBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      // Mobile: the custom 5-item dropdown is too crowded — route through the
      // shared _showLibDropdown with a small set (Open, Clone) plus Select +
      // Cancel. Heavier actions (Archive, Delete, Export) live in bulk mode.
      if (window.innerWidth <= 768) {
        const items = [];
        if (doc.session_id) items.push({ label: 'Open', action: () => libraryOpenInSession(doc) });
        items.push({ label: 'Clone', action: () => libraryImportDocument(doc) });
        _showLibDropdown(menuBtn, items, { onSelect: () => {
          libraryEnterSelectMode();
          _librarySelectedIds.add(doc.id);
          libraryUpdateBulkCount();
          libraryRenderGrid();
        } });
        return;
      }
      const dropdown = menuWrap.querySelector('.doclib-card-dropdown') || document.body.querySelector('.doclib-card-dropdown[data-owner="' + CSS.escape(doc.id) + '"]');
      if (dropdown) {
        const isOpen = dropdown.style.display !== 'none' && dropdown.parentElement === document.body;
        if (isOpen) {
          dropdown.style.display = 'none';
          menuWrap.appendChild(dropdown);
        } else {
          // Position fixed on body to escape overflow clipping
          const rect = menuBtn.getBoundingClientRect();
          document.body.appendChild(dropdown);
          dropdown.dataset.owner = doc.id;
          dropdown.style.cssText = 'position:fixed;z-index:10000;min-width:0;width:max-content;padding:4px;background:var(--panel);border:1px solid var(--border);border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,0.3);backdrop-filter:blur(12px);font-size:12px;display:block;';
          dropdown.style.top = (rect.bottom + 4) + 'px';
          dropdown.style.left = 'auto';
          dropdown.style.right = (window.innerWidth - rect.right) + 'px';
          // Clamp to viewport
          requestAnimationFrame(() => {
            const mr = dropdown.getBoundingClientRect();
            if (mr.bottom > window.innerHeight - 8) dropdown.style.top = (rect.top - mr.height - 4) + 'px';
            if (mr.left < 8) { dropdown.style.left = '8px'; dropdown.style.right = 'auto'; }
          });
          // Close on outside click
          const close = (ev) => {
            if (!dropdown.contains(ev.target) && !menuWrap.contains(ev.target)) {
              dropdown.style.display = 'none';
              menuWrap.appendChild(dropdown);
              document.removeEventListener('click', close, true);
            }
          };
          setTimeout(() => document.addEventListener('click', close, true), 0);
        }
      }
    });
    menuWrap.appendChild(menuBtn);

    // Dropdown menu
    const dropdown = document.createElement('div');
    dropdown.className = 'doclib-card-dropdown';
    dropdown.style.cssText = 'display:none;position:absolute;top:100%;right:0;z-index:1000;min-width:0;width:max-content;padding:4px;background:var(--panel);border:1px solid var(--border);border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,0.3);backdrop-filter:blur(12px);font-size:12px;';

    const _di = (svg) => `<span class="dropdown-icon">${svg}</span>`;
    const _openIco = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>';

    // Open
    const openItem = document.createElement('button');
    openItem.className = 'dropdown-item-compact';
    openItem.style.cssText = 'background:none;border:none;width:100%;';
    openItem.innerHTML = _di(_openIco) + '<span>Open</span>';
    if (doc.session_id) {
      openItem.addEventListener('click', (e) => { e.stopPropagation(); dropdown.style.display = 'none'; libraryOpenInSession(doc); });
    } else {
      openItem.disabled = true;
      openItem.style.opacity = '0.35';
      openItem.title = 'Not linked to a session';
    }
    dropdown.appendChild(openItem);

    // Clone
    const _cloneIco = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
    const cloneItem = document.createElement('button');
    cloneItem.className = 'dropdown-item-compact';
    cloneItem.style.cssText = 'background:none;border:none;width:100%;';
    cloneItem.innerHTML = _di(_cloneIco) + '<span>Clone</span>';
    cloneItem.title = 'Clone to active session';
    cloneItem.addEventListener('click', (e) => { e.stopPropagation(); dropdown.style.display = 'none'; libraryImportDocument(doc); });
    dropdown.appendChild(cloneItem);

    // Export
    const _exportIco = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>';
    const exportItem = document.createElement('button');
    exportItem.className = 'dropdown-item-compact';
    exportItem.style.cssText = 'background:none;border:none;width:100%;';
    exportItem.innerHTML = _di(_exportIco) + '<span>Export</span>';
    exportItem.addEventListener('click', async (e) => {
      e.stopPropagation();
      dropdown.style.display = 'none';
      try {
        const res = await fetch(`${API_BASE}/api/document/${doc.id}`);
        if (!res.ok) throw new Error('Failed');
        const full = await res.json();
        const extMap = { javascript: '.js', python: '.py', html: '.html', css: '.css', markdown: '.md', json: '.json', yaml: '.yml', bash: '.sh', sql: '.sql', rust: '.rs', go: '.go', java: '.java', c: '.c', cpp: '.cpp', typescript: '.ts', ruby: '.rb', php: '.php', xml: '.xml', toml: '.toml', ini: '.ini' };
        const ext = extMap[full.language] || '.txt';
        const blob = new Blob([full.current_content || ''], { type: 'text/plain' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = (full.title || 'document') + ext;
        a.click();
        URL.revokeObjectURL(a.href);
      } catch { if (uiModule) uiModule.showError('Failed to export document'); }
    });
    dropdown.appendChild(exportItem);

    // Archive / Restore — soft-archive a doc out of the main list, or bring it back.
    const _archiveIco = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/><line x1="10" y1="12" x2="14" y2="12"/></svg>';
    const archiveItem = document.createElement('button');
    archiveItem.className = 'dropdown-item-compact';
    archiveItem.style.cssText = 'background:none;border:none;width:100%;';
    archiveItem.innerHTML = _di(_archiveIco) + `<span>${_libraryArchivedView ? 'Restore' : 'Archive'}</span>`;
    archiveItem.title = _libraryArchivedView ? 'Restore to active documents' : 'Archive (hide from the main list)';
    archiveItem.addEventListener('click', async (e) => {
      e.stopPropagation();
      dropdown.style.display = 'none';
      const toArchived = !_libraryArchivedView;
      try {
        const res = await fetch(`${API_BASE}/api/document/${doc.id}/archive?archived=${toArchived}`, { method: 'POST', credentials: 'same-origin' });
        if (!res.ok) throw new Error('failed');
        // Drop it from the current view (it no longer belongs here) and refresh.
        _libraryDocs = _libraryDocs.filter(d => d.id !== doc.id);
        _libraryTotal = Math.max(0, _libraryTotal - 1);
        libraryRenderGrid();
        if (uiModule) uiModule.showToast(toArchived ? 'Archived' : 'Restored');
      } catch { if (uiModule) uiModule.showError('Failed to ' + (toArchived ? 'archive' : 'restore')); }
    });
    dropdown.appendChild(archiveItem);

    // Delete
    const _deleteIco = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>';
    const deleteItem = document.createElement('button');
    deleteItem.className = 'dropdown-item-compact dropdown-item-danger';
    deleteItem.style.cssText = 'background:none;border:none;width:100%;';
    deleteItem.innerHTML = _di(_deleteIco) + '<span>Delete</span>';
    deleteItem.addEventListener('click', (e) => { e.stopPropagation(); dropdown.style.display = 'none'; libraryDeleteSingle(doc.id, card); });
    dropdown.appendChild(deleteItem);

    menuWrap.appendChild(dropdown);
    actionsWrap.appendChild(menuWrap);
    card.appendChild(actionsWrap);

    // Hidden header for expand/preview compatibility
    card.appendChild(header);

    // Inject library card hover styles once
    if (!document.getElementById('doclib-card-styles')) {
      const s = document.createElement('style');
      s.id = 'doclib-card-styles';
      s.textContent = `.doclib-card:hover .doclib-card-icon-btn{opacity:.4}.doclib-card-icon-btn:hover{opacity:1!important}.doclib-card-text-btn{background:none;border:1px solid var(--border);color:var(--fg-muted);font-size:10px;padding:3px 8px;border-radius:4px;cursor:pointer;transition:border-color .15s,color .15s}.doclib-card-text-btn:hover{border-color:var(--accent,var(--red));color:var(--accent,var(--red))}.doclib-card-text-btn-danger{border-color:var(--color-danger,#e06c75)!important;color:var(--color-danger,#e06c75)!important}.doclib-card-text-btn-danger:hover{border-color:#ff4d4d!important;color:#ff4d4d!important}.doclib-card-chevron{display:none;align-items:center;justify-content:center;align-self:center;opacity:0.6;transition:transform .15s ease;flex-shrink:0;height:14px;line-height:0}.doclib-card-expanded .doclib-card-chevron{display:inline-flex;transform:rotate(180deg)}.doclib-card-chevron svg{display:block}`;
      document.head.appendChild(s);
    }

    // Preview — hidden by default, shown on expand
    const preview = document.createElement('div');
    preview.className = 'doclib-card-preview';
    const pre = document.createElement('pre');
    const code = document.createElement('code');
    try {
      if (doc.language && doc.language !== 'text' && window.hljs && !_librarySearch) {
        code.innerHTML = window.hljs.highlight(doc.preview || '', { language: doc.language }).value;
      } else if (_librarySearch) {
        // While searching, highlight matched terms in the preview (plain
        // text) rather than syntax-highlighting — the match is what matters.
        code.innerHTML = _hlSearch(doc.preview || '');
      } else {
        code.textContent = doc.preview || '';
      }
    } catch {
      code.textContent = doc.preview || '';
    }
    pre.appendChild(code);
    preview.appendChild(pre);

    // Expanded-only action bar — inside preview
    const expandedActions = document.createElement('div');
    expandedActions.className = 'doclib-card-expanded-actions';

    const openBtn = document.createElement('button');
    openBtn.className = 'doclib-card-text-btn doclib-card-action-btn';
    openBtn.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><path d="M5 12h14M13 5l7 7-7 7"/></svg>Open';
    if (doc.session_id) {
      openBtn.title = 'Open in original session';
      openBtn.addEventListener('click', (e) => { e.stopPropagation(); libraryOpenInSession(doc); });
    } else {
      openBtn.disabled = true;
      openBtn.style.opacity = '0.35';
      openBtn.style.cursor = 'not-allowed';
      openBtn.title = 'This document is not linked to a session';
    }

    const cloneBtn = document.createElement('button');
    cloneBtn.className = 'doclib-card-text-btn doclib-card-action-btn';
    cloneBtn.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>Clone';
    cloneBtn.title = 'Clone — copy to active session';
    cloneBtn.addEventListener('click', (e) => { e.stopPropagation(); libraryImportDocument(doc); });

    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'doclib-card-text-btn doclib-card-action-btn doclib-card-text-btn-danger';
    deleteBtn.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>Delete';
    deleteBtn.addEventListener('click', (e) => { e.stopPropagation(); libraryDeleteSingle(doc.id, card); });

    // Archive sits next to Delete on the LEFT — same lineup as the chat
    // and research footers. Label flips to Restore inside the Archive view.
    const archiveBtn = document.createElement('button');
    archiveBtn.className = 'doclib-card-text-btn doclib-card-action-btn';
    archiveBtn.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/><line x1="10" y1="12" x2="14" y2="12"/></svg>' + (_libraryArchivedView ? 'Restore' : 'Archive');
    archiveBtn.title = _libraryArchivedView ? 'Restore to active documents' : 'Archive (hide from the main list)';
    archiveBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const toArchived = !_libraryArchivedView;
      try {
        const res = await fetch(`${API_BASE}/api/document/${doc.id}/archive?archived=${toArchived}`, { method: 'POST', credentials: 'same-origin' });
        if (!res.ok) throw new Error('failed');
        _libraryDocs = _libraryDocs.filter(d => d.id !== doc.id);
        _libraryTotal = Math.max(0, _libraryTotal - 1);
        libraryRenderGrid();
        if (uiModule) uiModule.showToast(toArchived ? 'Archived' : 'Restored');
      } catch { if (uiModule) uiModule.showError('Failed to ' + (toArchived ? 'archive' : 'restore')); }
    });

    const leftGroup = document.createElement('div');
    leftGroup.className = 'doclib-action-group';
    const btnRow = document.createElement('div');
    btnRow.className = 'doclib-action-btn-row';
    // Export lives in the ⋮ menu — keep the footer uncrowded with Clone + Open.
    btnRow.appendChild(cloneBtn);
    btnRow.appendChild(openBtn);
    leftGroup.appendChild(btnRow);
    // Delete furthest LEFT, then Archive; Open/Clone group on the RIGHT.
    // Nudge the Delete/Archive pair 8px left for alignment.
    deleteBtn.style.cssText += ';position:relative;left:-8px;';
    archiveBtn.style.cssText += ';position:relative;left:-8px;';
    expandedActions.appendChild(deleteBtn);
    expandedActions.appendChild(archiveBtn);
    expandedActions.appendChild(leftGroup);

    preview.appendChild(expandedActions);
    card.appendChild(preview);

    card.addEventListener('click', () => {
      if (card._suppressNextClick) { card._suppressNextClick = false; return; }
      if (_librarySelectMode) {
        const cb = card.querySelector('.memory-select-cb');
        if (cb) { cb.checked = !cb.checked; cb.dispatchEvent(new Event('change')); }
      } else {
        libraryExpandCard(card, doc);
      }
    });
    _attachLongPressMenu(card, '.memory-item-btn');
    return card;
  }

  async function libraryExpandCard(card, doc) {
    const grid = card.closest('.doclib-grid');
    const instant = card?.dataset?.spaceToggle === '1';

    // Already expanded — collapse
    if (card.classList.contains('doclib-card-expanded')) {
      _collapseExpandedCard(card);
      return;
    }

    // Collapse any other expanded card
    if (grid) {
      grid.querySelectorAll('.doclib-card-expanded').forEach(c => _collapseExpandedCard(c));
    }

    // Fade siblings out before the CSS display:none kicks in
    const siblings = grid ? [...grid.querySelectorAll('.doclib-card')].filter(c => c !== card) : [];
    // Force explicit starting opacity so the first transition works
    siblings.forEach(s => { s.style.opacity = '1'; });
    // Force reflow so the browser registers the starting value
    if (!instant) {
      if (siblings.length) siblings[0].offsetHeight;
      siblings.forEach(s => { s.style.transition = 'opacity 0.12s ease'; s.style.opacity = '0'; });
    }

    // Capture the full grid + toolbar height so the modal stays the same
    // size on desktop. On mobile the modal is full-height and we want the
    // grid to claim all available space — skip the lock there.
    const isMobile = window.innerWidth <= 768;
    const toolbar = grid ? grid.closest('.admin-card')?.querySelector('.memory-toolbar') : null;
    const toolbarH = toolbar ? toolbar.offsetHeight : 0;
    if (grid && !isMobile) {
      grid.style.minHeight = (grid.offsetHeight + toolbarH) + 'px';
      grid.style.maxHeight = (grid.offsetHeight + toolbarH) + 'px';
    }

    // Wait for fade-out, then expand
    if (!instant) await new Promise(r => setTimeout(r, 120));

    card.classList.add('doclib-card-expanded');
    if (grid) grid.scrollTop = 0;

    // Clean up sibling inline styles (CSS display:none takes over now)
    siblings.forEach(s => { s.style.transition = ''; s.style.opacity = ''; });

    // Load full content into preview area
    const preview = card.querySelector('.doclib-card-preview');
    if (!preview) return;

    const actionsBar = preview.querySelector('.doclib-card-expanded-actions');
    const existingPre = preview.querySelector('pre');

    try {
      const res = await fetch(`${API_BASE}/api/document/${doc.id}`);
      if (!res.ok) throw new Error('Failed');
      const full = await res.json();
      const content = full.current_content || '';
      const lang = full.language || doc.language || 'text';

      // PDF-backed docs have a marker comment in their markdown — show the
      // rendered PDF in an iframe instead of dumping markdown source.
      const isPdfDoc = /<!--\s*pdf_(?:form_)?source\s+upload_id="[^"]+"/.test(content);
      const existingFrame = preview.querySelector('.doclib-card-pdf-frame');

      if (isPdfDoc) {
        const frame = document.createElement('iframe');
        frame.className = 'doclib-card-pdf-frame';
        frame.src = `${API_BASE}/api/document/${doc.id}/render-pdf?t=${Date.now()}`;
        frame.style.cssText = 'width:100%;height:60vh;border:1px solid var(--border);border-radius:6px;background:var(--bg);opacity:0;transition:opacity 0.15s ease;';
        if (existingPre) existingPre.remove();
        if (existingFrame) existingFrame.remove();
        preview.insertBefore(frame, preview.firstChild);
        if (actionsBar && !preview.contains(actionsBar)) preview.appendChild(actionsBar);
        requestAnimationFrame(() => { frame.style.opacity = '1'; });
        return;
      }

      const pre = document.createElement('pre');
      const code = document.createElement('code');
      // Syntax highlighting is synchronous and O(n) — running it over a whole
      // large document froze the main thread on click (the "lag"). Only
      // highlight up to a cap; bigger docs render as plain text (still fully
      // shown) so the preview opens instantly. Markdown gains little from
      // highlighting anyway, so skip it there.
      const HL_CAP = 20000;
      try {
        if (lang && lang !== 'text' && lang !== 'markdown' && window.hljs && content.length <= HL_CAP) {
          code.innerHTML = window.hljs.highlight(content, { language: lang }).value;
        } else {
          code.textContent = content;
        }
      } catch {
        code.textContent = content;
      }
      pre.appendChild(code);

      // Swap content — fade in the full version
      if (existingPre) existingPre.remove();
      if (existingFrame) existingFrame.remove();
      pre.style.opacity = '0';
      preview.insertBefore(pre, preview.firstChild);
      if (actionsBar && !preview.contains(actionsBar)) preview.appendChild(actionsBar);
      requestAnimationFrame(() => {
        pre.style.transition = 'opacity 0.15s ease';
        pre.style.opacity = '1';
      });
    } catch (e) {
      // On error, keep existing preview if available
      if (!existingPre) {
        preview.innerHTML = '<div style="padding:8px;color:var(--color-error);font-size:10px;">Failed to load</div>';
      }
      if (actionsBar && !preview.contains(actionsBar)) preview.appendChild(actionsBar);
    }
  }

  function libraryRenderLoadMore() {
    // Documents now reveal in 20-at-a-time chunks via the inline "Load more"
    // rendered inside libraryRenderGrid (matching the Chats tab). The legacy
    // server-pagination button + auto-fill are retired to avoid a double
    // control and surprise auto-loading.
    const legacy = document.getElementById('doclib-load-more');
    if (legacy) legacy.style.display = 'none';
  }

  async function libraryOpenDocument(doc) {
    closeLibrary();
    // Orphaned doc (session deleted) — just open in editor without switching session
    if (!doc.session_id) {
      _loadDocument(doc.id);
      return;
    }
    const currentSessionId = sessionModule && sessionModule.getCurrentSessionId();
    if (doc.session_id !== currentSessionId) {
      await sessionModule.selectSession(doc.session_id);
    }
    _loadDocument(doc.id);
  }

  /** Open a document in its linked session */
  async function libraryOpenInSession(doc) {
    if (!doc.session_id) return;
    closeLibrary();

    // Step 1: switch session if needed and wait for it to load
    const currentSessionId = sessionModule && sessionModule.getCurrentSessionId();
    if (doc.session_id !== currentSessionId) {
      await sessionModule.selectSession(doc.session_id);
      // Give the session UI a moment to settle
      await new Promise(r => setTimeout(r, 150));
    }

    // Step 2: ensure doc is in tabs
    const docs = _getDocs();
    if (!docs.has(doc.id)) {
      const res = await fetch(`${API_BASE}/api/document/${doc.id}`);
      if (res.ok) {
        const full = await res.json();
        _addDocToTabs(full, doc.session_id);
      }
    }

    // Step 3: open panel (slide-in is handled by openPanel)
    if (!_isOpenFn()) _openPanel();

    _switchToDoc(doc.id);
    _syncDocIndicator();
  }

  /** Copy a document from the library into the current session */
  async function libraryImportDocument(doc) {
    let sessionId = sessionModule && sessionModule.getCurrentSessionId();
    if (!sessionId) {
      // Create a new session if none exists
      if (sessionModule && sessionModule.hasPendingChat && sessionModule.hasPendingChat()) {
        const ok = await sessionModule.materializePendingSession();
        if (ok) sessionId = sessionModule.getCurrentSessionId();
      }
      if (!sessionId) {
        // No pending chat either — trigger new session, preserving the current model
        const curModel = sessionModule.getCurrentModel ? sessionModule.getCurrentModel() : null;
        const sessions = sessionModule ? sessionModule.getSessions() : [];
        // Prefer the session matching the current model, otherwise fall back to first with a model
        const withModel = sessions.filter(s => s.endpoint_url && s.model);
        const match = (curModel && withModel.find(s => s.model === curModel)) || withModel[0];
        if (match) {
          sessionModule.createDirectChat(match.endpoint_url, match.model, match.endpoint_id);
          const ok = await sessionModule.materializePendingSession();
          if (ok) sessionId = sessionModule.getCurrentSessionId();
        }
      }
      if (!sessionId) {
        if (uiModule) uiModule.showError('Could not create a session');
        return;
      }
    }
    try {
      // Fetch full content of the source document
      const srcRes = await fetch(`${API_BASE}/api/document/${doc.id}`);
      if (!srcRes.ok) throw new Error('Failed to fetch document');
      const src = await srcRes.json();

      // Deduplicate title — append (2), (3), etc. if name already exists in session
      let baseTitle = src.title || doc.title || 'Untitled';
      const existingTitles = new Set();
      const docs = _getDocs();
      for (const [, d] of docs) {
        if (d.sessionId === sessionId && d.title) existingTitles.add(d.title);
      }
      if (existingTitles.has(baseTitle)) {
        // Strip existing (N) suffix to get the root name
        const root = baseTitle.replace(/\s*\(\d+\)$/, '');
        let n = 2;
        while (existingTitles.has(root + ' (' + n + ')')) n++;
        baseTitle = root + ' (' + n + ')';
      }

      // Create a new document copy in the current session
      const res = await fetch(`${API_BASE}/api/document`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          // Preserve the source's type; default to markdown when unknown
          // (the backend also sniffs, but this keeps the tab label correct).
          language: src.language || doc.language || 'markdown',
          content: src.current_content || '',
        }),
      });
      if (!res.ok) throw new Error('Failed to create document');
      const created = await res.json();
      closeLibrary();
      _addDocToTabs(created, sessionId);
      if (!_isOpenFn()) _openPanel();

      _switchToDoc(created.id);
      _syncDocIndicator();
      if (uiModule) uiModule.showToast('Document cloned to session');
    } catch (e) {
      console.error('Failed to import document:', e);
      if (uiModule) uiModule.showError('Failed to import document');
    }
  }

  // ---- Library bulk operations ----

  function libraryEnterSelectMode() {
    _librarySelectMode = true;
    _librarySelectedIds.clear();
    const bulkBar = document.getElementById('doclib-bulk-bar');
    const selectBtn = document.getElementById('doclib-select-btn');
    if (bulkBar) bulkBar.classList.remove('hidden');
    if (selectBtn) { selectBtn.classList.add('active'); selectBtn.textContent = 'Cancel'; }
    libraryUpdateBulkCount();
    libraryRenderGrid();
  }

  function libraryExitSelectMode() {
    _librarySelectMode = false;
    _librarySelectedIds.clear();
    const bulkBar = document.getElementById('doclib-bulk-bar');
    const selectBtn = document.getElementById('doclib-select-btn');
    const selectAll = document.getElementById('doclib-select-all');
    if (bulkBar) bulkBar.classList.add('hidden');
    if (selectBtn) { selectBtn.classList.remove('active'); selectBtn.textContent = 'Select'; }
    if (selectAll) selectAll.checked = false;
    libraryRenderGrid();
  }

  function libraryToggleSelectItem(id) {
    if (_librarySelectedIds.has(id)) {
      _librarySelectedIds.delete(id);
    } else {
      _librarySelectedIds.add(id);
    }
    libraryUpdateBulkCount();
  }

  function libraryToggleSelectAll() {
    const selectAllEl = document.getElementById('doclib-select-all');
    if (!selectAllEl) return;
    if (selectAllEl.checked) {
      _libraryDocs.forEach(d => _librarySelectedIds.add(d.id));
    } else {
      _librarySelectedIds.clear();
    }
    libraryUpdateBulkCount();
    libraryRenderGrid();
  }

  function libraryUpdateBulkCount() {
    const countEl = document.getElementById('doclib-selected-count');
    const actionsBtn = document.getElementById('doclib-bulk-actions');
    if (countEl) countEl.textContent = `${_librarySelectedIds.size} Selected`;
    if (actionsBtn) actionsBtn.style.color = _librarySelectedIds.size > 0 ? 'var(--fg)' : '';
    // Legacy per-action buttons no longer rendered — guard so the rest of the
    // function (if anything still references them) doesn't crash.
    const deleteBtn = document.getElementById('doclib-bulk-delete');
    const exportBtn = document.getElementById('doclib-bulk-export');
    const archiveBtn = document.getElementById('doclib-bulk-archive');
    const cloneBtn = document.getElementById('doclib-bulk-clone');
    if (deleteBtn) deleteBtn.disabled = _librarySelectedIds.size === 0;
    if (exportBtn) exportBtn.disabled = _librarySelectedIds.size === 0;
    if (cloneBtn) cloneBtn.disabled = _librarySelectedIds.size === 0;
    if (archiveBtn) {
      archiveBtn.disabled = _librarySelectedIds.size === 0;
      archiveBtn.textContent = _libraryArchivedView ? 'Restore' : 'Archive';
    }
  }

  async function libraryDeleteSingle(docId, card) {
    if (uiModule && uiModule.styledConfirm) {
      const ok = await uiModule.styledConfirm('Delete this document?', { confirmText: 'Delete', danger: true });
      if (!ok) return;
    } else if (!confirm('Delete this document?')) {
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/api/document/${docId}`, { method: 'DELETE', credentials: 'same-origin' });
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try { const j = await res.json(); if (j?.detail) detail = j.detail; } catch {}
        throw new Error(detail);
      }
      if (card) {
        card.classList.add('doclib-card-deleting');
        card.addEventListener('transitionend', () => card.remove(), { once: true });
        setTimeout(() => { if (card.parentElement) card.remove(); }, 400);
      }
      _libraryDocs = _libraryDocs.filter(d => d.id !== docId);
      _libraryTotal = Math.max(0, _libraryTotal - 1);
      libraryRenderStats();
      if (uiModule) uiModule.showToast('Document deleted');
    } catch (e) {
      if (uiModule) uiModule.showError(`Failed to delete document: ${e.message || e}`);
    }
  }

  async function libraryBulkDelete() {
    if (_librarySelectedIds.size === 0) return;
    const count = _librarySelectedIds.size;
    if (uiModule && uiModule.styledConfirm) {
      const ok = await uiModule.styledConfirm(
        `Delete ${count} document${count !== 1 ? 's' : ''}?`,
        { confirmText: 'Delete', danger: true }
      );
      if (!ok) return;
    } else if (!confirm(`Delete ${count} document${count !== 1 ? 's' : ''}?`)) {
      return;
    }

    let deleted = 0;
    let failed = 0;
    const deletedIds = [];
    for (const id of _librarySelectedIds) {
      try {
        const res = await fetch(`${API_BASE}/api/document/${id}`, { method: 'DELETE', credentials: 'same-origin' });
        if (res.ok) {
          deleted++;
          deletedIds.push(id);
        }
        else { failed++; console.warn('Delete failed for', id, 'status', res.status); }
      } catch (e) {
        failed++;
        console.error('Failed to delete document:', id, e);
      }
    }

    for (const id of deletedIds) {
      const card = document.querySelector(`.doclib-card[data-doc-id="${CSS.escape(String(id))}"]`);
      if (card) card.classList.add('doclib-card-deleting');
    }
    if (deletedIds.length) await new Promise(r => setTimeout(r, 320));
    libraryExitSelectMode();
    await libraryFetch(false);
    if (uiModule) {
      const msg = failed > 0
        ? `Deleted ${deleted} · ${failed} failed`
        : `Deleted ${deleted} document${deleted !== 1 ? 's' : ''}`;
      (failed > 0 ? uiModule.showError : uiModule.showToast)(msg);
    }
  }

  async function libraryBulkArchive() {
    if (_librarySelectedIds.size === 0) return;
    const toArchived = !_libraryArchivedView;
    const ids = [..._librarySelectedIds];
    let done = 0, failed = 0;
    for (const id of ids) {
      try {
        const res = await fetch(`${API_BASE}/api/document/${id}/archive?archived=${toArchived}`, { method: 'POST', credentials: 'same-origin' });
        if (res.ok) done++; else failed++;
      } catch { failed++; }
    }
    libraryExitSelectMode();
    await libraryFetch(false);
    if (uiModule) {
      const verb = toArchived ? 'Archived' : 'Restored';
      const msg = failed > 0 ? `${verb} ${done} · ${failed} failed` : `${verb} ${done} document${done !== 1 ? 's' : ''}`;
      (failed > 0 ? uiModule.showError : uiModule.showToast)(msg);
    }
  }

  // Bulk "Clone" — reuse libraryImportDocument for each selected doc.
  // It handles session resolution + a possible new-session creation once
  // (subsequent calls in the loop see the now-resolved session).
  async function libraryBulkClone() {
    if (_librarySelectedIds.size === 0) return;
    const ids = [..._librarySelectedIds];
    let done = 0, failed = 0;
    for (const id of ids) {
      const doc = _libraryDocs.find(d => d.id === id);
      if (!doc) { failed++; continue; }
      try {
        const ok = await libraryImportDocument(doc);
        if (ok === false) failed++; else done++;
      } catch { failed++; }
    }
    libraryExitSelectMode();
    if (uiModule) {
      const msg = failed > 0
        ? `Cloned ${done} · ${failed} failed`
        : `Cloned ${done} document${done !== 1 ? 's' : ''}`;
      (failed > 0 ? uiModule.showError : uiModule.showToast)(msg);
    }
  }

  async function libraryBulkExport() {
    if (_librarySelectedIds.size === 0) return;
    // More than 5 → one server-built .zip (mirrors the gallery's bulk export;
    // browsers also block a flood of individual downloads).
    if (_librarySelectedIds.size > 5) {
      const ids = [..._librarySelectedIds];
      try {
        if (uiModule) uiModule.showToast(`Zipping ${ids.length} documents…`);
        const res = await fetch(`${API_BASE}/api/documents/export-zip`, {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ids }),
        });
        if (!res.ok) throw new Error('zip failed');
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'documents.zip';
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 2000);
        if (uiModule) uiModule.showToast(`Exported ${ids.length} documents (zip)`);
      } catch (e) {
        if (uiModule) uiModule.showError('Failed to create zip');
      }
      return;
    }
    const extMap = {
      javascript: '.js', python: '.py', html: '.html', css: '.css',
      markdown: '.md', json: '.json', yaml: '.yml', bash: '.sh',
      sql: '.sql', rust: '.rs', go: '.go', java: '.java', c: '.c', cpp: '.cpp',
      typescript: '.ts', ruby: '.rb', php: '.php', text: '.txt',
      xml: '.xml', toml: '.toml', ini: '.ini',
    };

    const docs = await Promise.all([..._librarySelectedIds].map(async id => {
      try {
        const res = await fetch(`${API_BASE}/api/document/${id}`);
        if (!res.ok) return null;
        return await res.json();
      } catch (e) {
        console.error('Failed to export document:', id, e);
        return null;
      }
    }));
    for (const doc of docs) {
      if (!doc) continue;
      const ext = extMap[doc.language] || '.txt';
      const filename = (doc.title || 'document') + (doc.title && doc.title.includes('.') ? '' : ext);
      const blob = new Blob([doc.current_content || ''], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    }
    if (uiModule) uiModule.showToast(`Exported ${_librarySelectedIds.size} document${_librarySelectedIds.size !== 1 ? 's' : ''}`);
  }

  /** Lazy-load SheetJS for spreadsheet parsing */
  let _xlsxReady = null;
  function ensureXLSX() {
    if (_xlsxReady) return _xlsxReady;
    if (window.XLSX) return (_xlsxReady = Promise.resolve());
    _xlsxReady = new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = '/static/lib/xlsx.full.min.js';
      s.onload = resolve;
      s.onerror = () => reject(new Error('Failed to load XLSX library'));
      document.head.appendChild(s);
    });
    return _xlsxReady;
  }

  let _mammothReady = null;
  function ensureMammoth() {
    if (_mammothReady) return _mammothReady;
    if (window.mammoth) return (_mammothReady = Promise.resolve());
    _mammothReady = new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = '/static/lib/mammoth.browser.min.js';
      s.onload = resolve;
      s.onerror = () => reject(new Error('Failed to load DOCX library'));
      document.head.appendChild(s);
    });
    return _mammothReady;
  }

  /** Convert HTML from mammoth to clean markdown */
  function htmlToMarkdown(html) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    let md = '';
    function walk(node) {
      if (node.nodeType === 3) { md += node.textContent; return; }
      if (node.nodeType !== 1) return;
      const tag = node.tagName.toLowerCase();
      if (tag === 'h1') { md += '\n# '; walkChildren(node); md += '\n'; }
      else if (tag === 'h2') { md += '\n## '; walkChildren(node); md += '\n'; }
      else if (tag === 'h3') { md += '\n### '; walkChildren(node); md += '\n'; }
      else if (tag === 'h4') { md += '\n#### '; walkChildren(node); md += '\n'; }
      else if (tag === 'strong' || tag === 'b') { md += '**'; walkChildren(node); md += '**'; }
      else if (tag === 'em' || tag === 'i') { md += '*'; walkChildren(node); md += '*'; }
      else if (tag === 'a') { md += '['; walkChildren(node); md += `](${node.href || ''})`; }
      else if (tag === 'br') { md += '\n'; }
      else if (tag === 'p') { md += '\n'; walkChildren(node); md += '\n'; }
      else if (tag === 'ul' || tag === 'ol') { md += '\n'; walkChildren(node); }
      else if (tag === 'li') {
        const parent = node.parentElement?.tagName?.toLowerCase();
        if (parent === 'ol') {
          const idx = Array.from(node.parentElement.children).indexOf(node) + 1;
          md += `${idx}. `;
        } else { md += '- '; }
        walkChildren(node);
        md += '\n';
      }
      else if (tag === 'table') { md += '\n'; convertTable(node); md += '\n'; }
      else if (tag === 'img') {
        // Skip embedded base64 images — they produce huge unreadable blobs
        const src = node.src || '';
        if (!src.startsWith('data:')) {
          md += `![${node.alt || ''}](${src})`;
        } else if (node.alt) {
          md += `*[image: ${node.alt}]*`;
        }
      }
      else { walkChildren(node); }
    }
    function walkChildren(node) { for (const child of node.childNodes) walk(child); }
    function convertTable(table) {
      const rows = table.querySelectorAll('tr');
      rows.forEach((tr, i) => {
        const cells = tr.querySelectorAll('th, td');
        md += '| ' + Array.from(cells).map(c => c.textContent.trim()).join(' | ') + ' |\n';
        if (i === 0) md += '| ' + Array.from(cells).map(() => '---').join(' | ') + ' |\n';
      });
    }
    walkChildren(doc.body);
    return md.replace(/\n{3,}/g, '\n\n').trim();
  }

  /** Read file contents — handles text, spreadsheet, and DOCX formats */
  async function readFileContent(file) {
    const name = file.name.toLowerCase();
    const isSpreadsheet = name.endsWith('.xlsx') || name.endsWith('.xls') || name.endsWith('.ods');
    const isDocx = name.endsWith('.docx');

    if (isSpreadsheet) {
      await ensureXLSX();
      const buf = await file.arrayBuffer();
      const wb = window.XLSX.read(buf, { type: 'array' });
      // Convert each sheet to CSV, join with a header per sheet
      const parts = [];
      for (const sheetName of wb.SheetNames) {
        if (wb.SheetNames.length > 1) parts.push(`# Sheet: ${sheetName}`);
        parts.push(window.XLSX.utils.sheet_to_csv(wb.Sheets[sheetName]));
      }
      return parts.join('\n\n');
    }

    if (isDocx) {
      await ensureMammoth();
      const buf = await file.arrayBuffer();
      const result = await window.mammoth.convertToHtml({ arrayBuffer: buf });
      return htmlToMarkdown(result.value);
    }

    // Plain text
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(reader.error);
      reader.readAsText(file);
    });
  }

  /** Import files from disk into the document library */
  async function libraryImportFiles(fileList) {
    const EXT_TO_LANG = {
      '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
      '.html': 'html', '.htm': 'html', '.css': 'css', '.md': 'markdown',
      '.json': 'json', '.yml': 'yaml', '.yaml': 'yaml', '.sh': 'bash',
      '.bash': 'bash', '.sql': 'sql', '.rs': 'rust', '.go': 'go',
      '.java': 'java', '.c': 'c', '.cpp': 'cpp', '.h': 'c', '.hpp': 'cpp',
      '.rb': 'ruby', '.php': 'php', '.xml': 'xml',
      '.toml': 'toml', '.ini': 'ini', '.txt': '', '.log': '',
      '.cfg': 'ini', '.conf': 'ini', '.env': '', '.jsx': 'javascript',
      '.tsx': 'typescript', '.vue': 'html', '.svelte': 'html',
      '.scss': 'css', '.sass': 'css', '.less': 'css',
      '.csv': 'csv', '.tsv': 'csv',
      '.xlsx': 'csv', '.xls': 'csv', '.ods': 'csv',
      '.docx': 'markdown', '.doc': 'markdown',
    };

    let imported = 0;
    let failed = 0;
    let _firstErr = '';

    // Library imports aren't tied to a chat — the backend now accepts a
    // session-less "library" document, so no session_id is sent.
    for (const file of fileList) {
      try {
        const name = file.name;
        const dotIdx = name.lastIndexOf('.');
        const ext = dotIdx >= 0 ? name.slice(dotIdx).toLowerCase() : '';
        const baseTitle = dotIdx > 0 ? name.slice(0, dotIdx) : name;
        const language = EXT_TO_LANG[ext] !== undefined ? EXT_TO_LANG[ext] : null;

        const isSpreadsheet = ['.xlsx', '.xls', '.ods'].includes(ext);
        const isPdf = ext === '.pdf';

        if (isPdf) {
          // Backend handles save + AcroForm detection in one shot — picks the
          // right doc kind so fillable forms get clickable inputs in the PDF
          // view, and plain PDFs get the static page-image viewer.
          const fd = new FormData();
          fd.append('file', file);
          const res = await fetch(`${API_BASE}/api/documents/import-pdf`, {
            method: 'POST',
            body: fd,
          });
          if (!res.ok) {
            let _e = `HTTP ${res.status}`;
            try { const _j = await res.json(); _e = _j.detail || _j.error || _e; } catch {}
            throw new Error('PDF import failed: ' + _e);
          }
          imported++;
          continue;
        }

        if (isSpreadsheet) {
          // Multi-sheet: create one document per sheet
          await ensureXLSX();
          const buf = await file.arrayBuffer();
          const wb = window.XLSX.read(buf, { type: 'array' });
          for (const sheetName of wb.SheetNames) {
            const csv = window.XLSX.utils.sheet_to_csv(wb.Sheets[sheetName]);
            if (!csv.trim()) continue;
            const sheetTitle = wb.SheetNames.length > 1
              ? `${baseTitle} - ${sheetName}` : baseTitle;
            const res = await fetch(`${API_BASE}/api/document`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ title: sheetTitle, language: 'csv', content: csv }),
            });
            if (!res.ok) throw new Error('Server error');
          }
          imported++;
        } else {
          const content = await readFileContent(file);
          const res = await fetch(`${API_BASE}/api/document`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: baseTitle, language, content }),
          });
          if (!res.ok) throw new Error('Server error');
          imported++;
        }
      } catch (e) {
        console.error('Failed to import file:', file.name, e);
        if (!_firstErr) _firstErr = (e && e.message) || String(e);
        failed++;
      }
    }

    const msg = `Imported ${imported} file${imported !== 1 ? 's' : ''}` +
      (failed ? `, ${failed} failed${_firstErr ? ' — ' + _firstErr : ''}` : '');
    if (failed && uiModule) uiModule.showError(msg);
    else if (uiModule) uiModule.showToast(msg);
    await libraryFetch(false);
  }

  export function openLibrary(opts) {
    if (_libraryOpen) {
      // Recover from stuck state: the swipe-to-dismiss in ui.js adds .hidden
      // to the modal without calling closeLibrary, so _libraryOpen can stay
      // true even though the modal is gone or invisible. Detect and reset.
      const existing = document.getElementById('doclib-modal');
      if (!existing || existing.classList.contains('hidden')) {
        if (existing) existing.remove();
        _libraryOpen = false;
      } else {
        return;
      }
    }
    _libraryOpen = true;
    _libraryImportMode = !!(opts && opts.import);
    _librarySelectMode = false;
    _librarySelectedIds.clear();
    _librarySearch = '';
    _libraryActiveLanguage = null;
    _librarySort = 'recent';
    _libraryOffset = 0;
    _libraryDocs = [];

    // Create modal
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.id = 'doclib-modal';
    modal.innerHTML = `
      <div class="modal-content doclib-modal-content" style="width:min(640px, 92vw);max-height:85vh;background:var(--bg);">
        <div class="modal-header">
          <h4><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px;"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/><line x1="8" y1="7" x2="16" y2="7"/><line x1="8" y1="11" x2="14" y2="11"/></svg>Documents</h4>
          <button class="close-btn" id="doclib-close">\u2716</button>
        </div>
        <div class="lib-tabs" id="doclib-lib-tabs" style="padding:0 10px;">
          <button class="lib-tab" data-doclib-tab="chats"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>Chats</button>
          <button class="lib-tab active" data-doclib-tab="documents"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="13" y2="17"/></svg>Documents</button>
          <button class="lib-tab" data-doclib-tab="research"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:-1px;margin-right:3px;"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg>Research</button>
          <button class="lib-tab" data-doclib-tab="applicant" title="Tailored resumes &amp; cover letters generated for your job applications, with a built-in review step before anything is sent."><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/><path d="M9 12h6"/><path d="M9 16h4"/></svg>Applications</button>
          <button class="lib-tab" data-doclib-tab="archive"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/><line x1="10" y1="12" x2="14" y2="12"/></svg>Archive</button>
        </div>
        <div class="modal-body" style="display:flex;flex-direction:column;gap:10px;overflow:hidden;">
          <div id="doclib-panel-chats" data-doclib-panel="chats" class="admin-card" style="display:none;flex:1;flex-direction:column;overflow:hidden;">
            <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:2px;">
              <h2 style="margin:0;padding:0;line-height:1;">Chats <span id="doclib-chats-stats" class="memory-count" style="font-size:0.6em;opacity:0.6;font-weight:normal"></span></h2>
            </div>
            <p class="memory-desc doclib-desc">All active chat sessions. Click to open.</p>
            <div class="memory-toolbar">
              <div class="memory-category-filters">
                <select class="memory-sort-select" id="doclib-chats-sort">
                  <option value="recent">Recent</option>
                  <option value="oldest">Oldest</option>
                  <option value="most-messages">Most messages</option>
                  <option value="alpha">A\u2013Z</option>
                </select>
                <button class="memory-toolbar-btn" id="doclib-chats-select-btn">Select</button>
                <button class="memory-toolbar-btn" id="doclib-chats-tidy-btn" title="AI tidy: delete junk sessions and organize into folders"><svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" style="vertical-align:-1px;margin-right:2px;"><path d="M12 0L14.59 8.41L23 12L14.59 15.59L12 24L9.41 15.59L1 12L9.41 8.41Z"/></svg> Tidy</button>
              </div>
              <input type="text" id="doclib-chats-search" placeholder="Search chats\u2026" class="memory-search-input" />
              <div id="doclib-chats-chips" class="doclib-lang-chips"></div>
            </div>
            <div id="doclib-chats-bulk" class="memory-bulk-bar hidden" style="margin-bottom:5px;">
              <label class="memory-bulk-check-all" style="position:relative;top:0px;left:-1px;"><input type="checkbox" id="doclib-chats-select-all" style="position:relative;top:0px;"> All</label>
              <span id="doclib-chats-selected-count">0 Selected</span>
              <button class="memory-toolbar-btn" id="doclib-chats-bulk-archive" style="position:relative;top:-3px;left:2px;"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/><line x1="10" y1="12" x2="14" y2="12"/></svg>Archive</button>
              <button class="memory-toolbar-btn danger" id="doclib-chats-bulk-delete" style="position:relative;left:2px;"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>Delete</button>
              <button class="memory-toolbar-btn" id="doclib-chats-bulk-cancel" title="Cancel (Esc)" style="margin-left:4px;padding:3px 6px;position:relative;left:2px;"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
            </div>
            <div id="doclib-chats-grid" class="doclib-grid"></div>
          </div>
          <div id="doclib-panel-archive" data-doclib-panel="archive" class="admin-card" style="display:none;flex:1;flex-direction:column;overflow:hidden;">
            <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:2px;">
              <h2 style="margin:0;padding:0;line-height:1;position:relative;top:2px;">Archive <span id="doclib-arc-stats" class="memory-count" style="font-size:0.6em;opacity:0.6;font-weight:normal"></span></h2>
            </div>
            <p class="memory-desc doclib-desc" style="position:relative;top:0.5px;">Archived sessions. Restore to make active again.</p>
            <div class="memory-toolbar">
              <div class="memory-category-filters">
                <select class="memory-sort-select" id="doclib-arc-sort">
                  <option value="recent">Recent</option>
                  <option value="oldest">Oldest</option>
                  <option value="most-messages">Most messages</option>
                  <option value="alpha">A\u2013Z</option>
                </select>
                <button class="memory-toolbar-btn" id="doclib-arc-select-btn">Select</button>
              </div>
              <input type="text" id="doclib-arc-search" placeholder="Search archive\u2026" class="memory-search-input" />
              <div id="doclib-arc-chips" class="doclib-lang-chips"></div>
            </div>
            <div id="doclib-arc-bulk" class="memory-bulk-bar hidden" style="margin-bottom:5px;">
              <label class="memory-bulk-check-all" style="position:relative;top:0px;left:1px;"><input type="checkbox" id="doclib-arc-select-all"> All</label>
              <span id="doclib-arc-selected-count">0 Selected</span>
              <button class="memory-toolbar-btn" id="doclib-arc-bulk-restore" style="position:relative;top:-3px;"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>Restore</button>
              <button class="memory-toolbar-btn danger" id="doclib-arc-bulk-delete"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>Delete</button>
              <button class="memory-toolbar-btn" id="doclib-arc-bulk-cancel" title="Cancel (Esc)" style="margin-left:4px;padding:3px 6px;"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
            </div>
            <div id="doclib-arc-grid" class="doclib-grid"></div>
          </div>
          <div id="doclib-panel-research" data-doclib-panel="research" class="admin-card" style="display:none;flex:1;flex-direction:column;overflow:hidden;">
            <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:2px;margin-top:10px;">
              <h2 style="margin:0;padding:0;line-height:1;">Research <span id="doclib-research-stats" class="memory-count" style="font-size:0.6em;opacity:0.6;font-weight:normal"></span></h2>
            </div>
            <p class="memory-desc doclib-desc" style="position:relative;top:-1px;">Completed deep research reports. Click to view.</p>
            <div class="memory-toolbar">
              <div class="memory-category-filters">
                <select class="memory-sort-select" id="doclib-research-sort">
                  <option value="recent">Recent</option>
                  <option value="oldest">Oldest</option>
                  <option value="most-sources">Most sources</option>
                  <option value="alpha">A\u2013Z</option>
                </select>
                <button class="memory-toolbar-btn" id="doclib-research-select-btn">Select</button>
                <button class="memory-toolbar-btn" id="doclib-research-tidy-btn" title="Tidy: delete research with no sources or empty reports">Tidy</button>
              </div>
              <input type="text" id="doclib-research-search" placeholder="Search research\u2026" class="memory-search-input" />
            </div>
            <div id="doclib-research-bulk" class="memory-bulk-bar hidden" style="margin-bottom:5px;">
              <label class="memory-bulk-check-all" style="position:relative;top:0px;left:1px;"><input type="checkbox" id="doclib-research-select-all"> All</label>
              <span id="doclib-research-selected-count">0 Selected</span>
              <button class="memory-toolbar-btn" id="doclib-research-bulk-archive" style="position:relative;top:-2px;"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/><line x1="10" y1="12" x2="14" y2="12"/></svg>Archive</button>
              <button class="memory-toolbar-btn danger" id="doclib-research-bulk-delete" style="position:relative;top:-2px;"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>Delete</button>
              <button class="memory-toolbar-btn" id="doclib-research-bulk-cancel" title="Cancel (Esc)" style="margin-left:4px;padding:3px 6px;position:relative;top:-2px;"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
            </div>
            <div id="doclib-research-grid" class="doclib-grid"></div>
          </div>
          <div id="doclib-panel-applicant" data-doclib-panel="applicant" class="admin-card" style="display:none;flex:1;flex-direction:column;overflow:hidden;">
            <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:2px;">
              <h2 style="margin:0;padding:0;line-height:1;">Applications <span id="doclib-applicant-stats" class="memory-count" style="font-size:0.6em;opacity:0.6;font-weight:normal"></span></h2>
              <button class="memory-toolbar-btn" id="doclib-applicant-refresh" title="Reload the latest tailored resumes and cover letters." style="margin-left:auto;"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg> Refresh</button>
            </div>
            <p class="memory-desc doclib-desc">Resumes and cover letters I tailor for your job applications. Open one to review my suggested changes, ask for tweaks, then approve it before it's used.</p>
            <div id="doclib-applicant-grid" class="doclib-grid"></div>
          </div>
          <div data-doclib-panel="documents" class="admin-card" style="flex:1;display:flex;flex-direction:column;overflow:hidden;">
            <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:2px;">
              <h2 style="margin:0;padding:0;line-height:1;">Documents <span id="doclib-stats" class="memory-count" style="font-size:0.6em;opacity:0.6;font-weight:normal"></span></h2>
              <button class="memory-toolbar-btn" id="doclib-import-file-btn" title="Import files from disk" style="margin-left:auto;"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:2px;"><polyline points="7 10 12 5 17 10"/><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="21" x2="19" y2="21"/></svg> Import</button>
              <button class="memory-toolbar-btn" id="doclib-create-btn" title="Create new blank document"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg> Create</button>
            </div>
            <p class="memory-desc doclib-desc">Open documents in a session, clone to a new or import new files.</p>
            <div class="memory-toolbar">
              <div class="memory-category-filters">
                <select class="memory-sort-select" id="doclib-sort">
                  <option value="recent">Recent</option>
                  <option value="oldest">Oldest</option>
                  <option value="edits">Most edits</option>
                  <option value="alpha">A\u2013Z</option>
                </select>
                <button class="memory-toolbar-btn" id="doclib-select-btn" title="Select documents">Select</button>
                <button class="memory-toolbar-btn" id="doclib-tidy-btn" title="Tidy: remove empty / junk / duplicate documents">Tidy</button>
              </div>
              <input type="text" id="doclib-search" placeholder="Search titles &amp; content\u2026" class="memory-search-input" />
              <div id="doclib-chips" class="doclib-lang-chips"></div>
            </div>
            <input type="file" id="doclib-file-input" multiple style="display:none" />
            <div id="doclib-bulk-bar" class="memory-bulk-bar hidden" style="margin-bottom:5px;">
              <label class="memory-bulk-check-all" style="position:relative;top:0px;left:1px;"><input type="checkbox" id="doclib-select-all" /> All</label>
              <span id="doclib-selected-count">0 Selected</span>
              <button id="doclib-bulk-actions" class="memory-toolbar-btn" style="position:relative;top:-2px;margin-left:auto;"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>Actions <span style="opacity:0.55;font-size:9px;">&#9660;</span></button>
              <button id="doclib-bulk-cancel" class="memory-toolbar-btn" title="Cancel (Esc)" style="margin-left:4px;margin-right:4px;padding:3px 6px;position:relative;top:-2px;"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
            </div>
            <div class="doclib-grid" id="doclib-grid"></div>
            <button class="doclib-load-more" id="doclib-load-more" style="display:none">Load more</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(modal);

    // Make modal draggable (same logic as other modals)
    {
      const content = modal.querySelector('.modal-content');
      const header = modal.querySelector('.modal-header');
      if (content && header) {
        // Restore saved position / fullscreen state
        try {
          const saved = JSON.parse(localStorage.getItem('doclib-pos'));
          if (saved && saved.fullscreen) {
            localStorage.removeItem('doclib-pos');
          } else if (saved && saved.left && saved.top) {
            content.style.position = 'fixed';
            content.style.left = saved.left;
            content.style.top = saved.top;
            content.style.margin = '0';
            // Clamp to viewport in case window was resized
            requestAnimationFrame(() => {
              const r = content.getBoundingClientRect();
              if (r.right > window.innerWidth) content.style.left = Math.max(0, window.innerWidth - r.width - 8) + 'px';
              if (r.bottom > window.innerHeight) content.style.top = Math.max(0, window.innerHeight - r.height - 8) + 'px';
              if (r.left < 0) content.style.left = '8px';
              if (r.top < 0) content.style.top = '8px';
            });
          }
        } catch {}
        // Replaced ~150 lines of inline drag/snap/dock with one helper call.
        // Library intentionally disables top-edge fullscreen snap: that layout
        // breaks dense icon/tool rows. Side docking still works.
        const FS_CLASS = 'doclib-fullscreen';
        const enterFullscreen = () => {
          if (modal.classList.contains(FS_CLASS)) return;
          modal.classList.add(FS_CLASS);
          content.style.position = 'fixed';
          content.style.left = '0';
          content.style.top = '0';
          content.style.right = '0';
          content.style.bottom = '0';
          content.style.width = '100vw';
          content.style.maxWidth = '100vw';
          content.style.height = '100vh';
          content.style.maxHeight = '100vh';
          content.style.borderRadius = '0';
          content.style.margin = '0';
          content.style.transform = 'none';
          try { localStorage.setItem('doclib-pos', JSON.stringify({ fullscreen: true })); } catch {}
        };
        const exitFullscreen = (cx, cy) => {
          if (!modal.classList.contains(FS_CLASS)) return;
          modal.classList.remove(FS_CLASS);
          content.style.width = '';
          content.style.maxWidth = '';
          content.style.height = '';
          content.style.maxHeight = '';
          content.style.borderRadius = '';
          content.style.right = '';
          content.style.bottom = '';
          const r0 = content.getBoundingClientRect();
          const w = r0.width || Math.min(900, window.innerWidth * 0.92);
          content.style.left = Math.max(8, cx - w / 2) + 'px';
          content.style.top = Math.max(8, cy - 20) + 'px';
        };
        makeWindowDraggable(modal, {
          content,
          header,
          fsClass: FS_CLASS,
          skipSelector: '.modal-close',
          onEnterFullscreen: enterFullscreen,
          onExitFullscreen: exitFullscreen,
          enableFullscreen: false,
          onDragEnd: () => {
            try { localStorage.setItem('doclib-pos', JSON.stringify({ left: content.style.left, top: content.style.top })); } catch {}
          },
        });
      }
    }

    // Wire events
    document.getElementById('doclib-close').addEventListener('click', closeLibrary);

    // Tab switching — Chats / Documents / Archive / Research
    let _activeLibTab = (opts && opts.tab) || 'documents';
    const _tabBtns = modal.querySelectorAll('[data-doclib-tab]');
    const _tabPanels = modal.querySelectorAll('[data-doclib-panel]');

    // Client-side pagination for tabs whose API returns everything at once
    // (chats/archive/research). Render only this many initially; the
    // load-more button reveals more in chunks.
    const _LIB_PAGE_SIZE = 20;
    let _chatsVisibleLimit = _LIB_PAGE_SIZE;
    let _arcVisibleLimit = _LIB_PAGE_SIZE;
    let _researchVisibleLimit = _LIB_PAGE_SIZE;

    function _appendInlineLoadMore(grid, totalCount, currentLimit, onClick) {
      if (!grid || !grid.parentElement) return;
      // Drop the previous instance (if any) — we re-render the list from
      // scratch each pass, so the button is regenerated alongside it.
      grid.parentElement.querySelectorAll(':scope > .doclib-inline-load-more').forEach(b => b.remove());
      if (totalCount <= currentLimit) return;
      const btn = document.createElement('button');
      btn.className = 'doclib-load-more doclib-inline-load-more';
      btn.textContent = `Load more (${currentLimit} of ${totalCount})`;
      btn.addEventListener('click', onClick);
      grid.parentElement.appendChild(btn);
    }

    function _switchLibTab(tab) {
      _activeLibTab = tab;
      _tabBtns.forEach(b => b.classList.toggle('active', b.dataset.doclibTab === tab));
      _tabPanels.forEach(p => {
        if (p.dataset.doclibPanel === tab) {
          p.style.display = 'flex';
        } else {
          p.style.display = 'none';
        }
      });
      if (tab === 'chats') _renderLibChats();
      else if (tab === 'archive') _renderLibArchive();
      else if (tab === 'research') _renderLibResearch();
      else if (tab === 'applicant') _renderLibApplicant();
    }

    _tabBtns.forEach(btn => {
      btn.addEventListener('click', () => _switchLibTab(btn.dataset.doclibTab));
    });

    // Manual refresh for the Applications tab (the engine generates these
    // asynchronously, so a reload button is handy after new roles are tailored).
    {
      const _appRefresh = modal.querySelector('#doclib-applicant-refresh');
      if (_appRefresh) _appRefresh.addEventListener('click', () => _renderLibApplicant());
    }

    // ════════════════════════════════════════════════════════════════════
    // Applications tab — the engine-backed resume / cover-letter library and
    // the change-and-review loop. Talks to the workspace proxy at
    // /api/applicant/documents/* (which forwards to the application engine).
    // Fully self-contained: reuses the shared library card/grid styles and the
    // ui.js toast/error helpers, so it matches the rest of the Library without
    // touching the other tabs. Plain language throughout; no internal jargon.
    // ════════════════════════════════════════════════════════════════════
    const _APPLICANT_BASE = `${API_BASE}/api/applicant/documents`;
    // Last application id the user looked up, so Refresh re-runs the same query.
    // Seeded from the deep-link (opts.appId) so the Portal "Review" affordance
    // opens the materials directly — no typing an application id (D1).
    let _applicantLastAppId = (opts && opts.appId) ? String(opts.appId) : '';
    // Last job-search (campaign) id whose resume-variant library was viewed, so the
    // variants lookup can be deep-linked + re-run on refresh (FR-RESUME-6 / FR-UI-6).
    let _variantLastCampaign = (opts && opts.campaignId) ? String(opts.campaignId) : '';

    // Friendly label for an engine document/variant "type" value.
    function _applicantTypeLabel(type) {
      const t = (type || '').toLowerCase();
      if (t === 'resume_variant' || t === 'resume') return 'Resume';
      if (t === 'cover_letter') return 'Cover letter';
      if (t === 'screening_answer') return 'Screening answer';
      if (t === 'deferred_essay') return 'Application essay';
      return (type || 'Document').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    }

    // Plain-language "why this variant" line (dark-engine audit item 53): the
    // per-variant JD keyword coverage the engine already computes and stores
    // (``ResumeFitScoring.coverage``/``missing_terms``, on the wire as
    // ``fit_scores: {coverage, missing_terms}``) turned into "Covers 82% of the
    // posting's language; missing: Kubernetes, SOC 2". Real data only — a
    // variant that has not been JD-matched yet has no ``coverage`` number, and
    // this returns '' (render nothing) rather than fabricate one.
    function _applicantFitScoreText(fitScores) {
      const scores = (fitScores && typeof fitScores === 'object') ? fitScores : {};
      const coverage = Number(scores.coverage);
      if (!Number.isFinite(coverage)) return '';
      const pct = Math.round(Math.max(0, Math.min(1, coverage)) * 100);
      const missing = Array.isArray(scores.missing_terms) ? scores.missing_terms.filter(Boolean) : [];
      let text = `Covers ${pct}% of the posting's language`;
      if (missing.length) text += `; missing: ${missing.slice(0, 8).join(', ')}`;
      return text;
    }

    // Degraded-draft warning (dark-engine audit item 40): ``MaterialService``
    // silently falls back to a deterministic template when the writing model's
    // tier ladder is exhausted — the engine now flags that (``degraded`` +
    // ``degraded_reason`` on documents; ``degraded`` inside ``fit_scores`` for
    // résumé variants), but until now the review surface presented the fallback
    // draft exactly like a real AI-tailored one. Reuses the SAME warning tone as
    // the scheduler stall line in applicantDebug.js (``var(--orange, #ffb86c)``)
    // rather than inventing a new color. Returns null (render nothing) when the
    // draft is not degraded.
    function _applicantDegradedBadge(reason) {
      if (!reason) return null;
      const badge = document.createElement('div');
      badge.className = 'doclib-applicant-degraded';
      badge.style.cssText = 'font-size:11px;padding:4px 8px;border-radius:6px;' +
        'border:1px solid var(--orange, #ffb86c);color:var(--orange, #ffb86c);' +
        'opacity:0.95;display:flex;align-items:center;gap:5px;';
      badge.title = reason;
      badge.innerHTML =
        '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
          'stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;">' +
          '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>' +
          '<line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>' +
        '<span>Fallback draft — model was unavailable, review closely</span>';
      return badge;
    }

    // Ancestry breadcrumb (dark-engine audit item 50): the engine's
    // ``MaterialService.lineage`` walk, root-first, turned into a readable trail
    // like "Original -> Tailored for <job> -> this version" so a user can see how
    // a tailored resume relates to the ones it was forked from. ``lineage`` on the
    // wire is a list of ``{variant_id, is_root, targeted_jd_signature, approved}``
    // ending with the variant itself; returns '' when there is no ancestry to show
    // (a lone root variant) rather than a one-word breadcrumb.
    function _applicantLineageBreadcrumb(lineage, esc) {
      const chain = Array.isArray(lineage) ? lineage : [];
      if (chain.length < 2) return '';
      const labels = chain.map((node, idx) => {
        if (idx === chain.length - 1) return 'this version';
        if (node && node.is_root) return 'Original';
        const sig = node && node.targeted_jd_signature;
        return sig ? `Tailored for ${sig}` : 'Tailored version';
      });
      return labels.map(esc).join(' → ');
    }

    // Compact, first-person "What I drew on" panel — surfaces the learned items
    // (saved preferences / playbooks / a prior application) that shaped a draft so
    // the assistant's learning is visible and the user can trust where the
    // phrasing came from. Purely descriptive: it does not change what was written,
    // and the draft stays fully editable in the review loop below. Returns null
    // (so the caller renders nothing) when there is no provenance to show.
    function _applicantProvenancePanel(provenance) {
      const items = Array.isArray(provenance) ? provenance : [];
      // Only items with a human-readable label are worth showing; ref ids stay
      // internal (traceability), never shown raw to the user.
      const labels = items
        .map(p => (p && typeof p.label === 'string') ? p.label.trim() : '')
        .filter(Boolean);
      if (!labels.length) return null;

      const panel = document.createElement('div');
      panel.className = 'memory-item';
      panel.style.cssText = 'font-size:11px;border:1px solid var(--border);border-radius:6px;padding:6px 8px;opacity:0.9;display:flex;flex-direction:column;gap:4px;';

      const head = document.createElement('div');
      head.style.cssText = 'font-weight:600;opacity:0.8;display:flex;align-items:center;gap:5px;';
      head.innerHTML =
        '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;opacity:0.7;"><path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7c.5.4.8 1 .8 1.6v.7h6.4v-.7c0-.6.3-1.2.8-1.6A7 7 0 0 0 12 2z"/></svg>' +
        '<span>What I drew on</span>';
      head.title = 'The things I have learned about you that shaped this draft. This is just for transparency — you can still change anything below.';
      panel.appendChild(head);

      const list = document.createElement('ul');
      list.style.cssText = 'margin:0;padding-left:16px;display:flex;flex-direction:column;gap:2px;';
      labels.forEach(label => {
        const li = document.createElement('li');
        li.style.cssText = 'opacity:0.85;';
        li.textContent = label;
        list.appendChild(li);
      });
      panel.appendChild(list);
      return panel;
    }

    // "A few facts to double-check" (P1-13). The assistant may rewrite a draft to
    // read its strongest, and the engine's balanced truth policy SURFACES any
    // fact-class specifics (a skill, employer, credential, date or number) that
    // aren't in the profile yet rather than blocking them — nothing is sent until
    // the user approves. This loads those flagged facts for the open document and
    // renders each with a one-tap "yes, that's true — add to my profile" (persists
    // it via the same confirm-conflict endpoint onboarding uses, so it stops being
    // flagged and can be reused) or "Remove" (a subtract turn that takes it out of
    // this draft). Best-effort: a failed/empty read renders nothing and never
    // blocks the review card below, mirroring the research-provenance panel.
    async function _loadApplicantFlaggedFacts(item, appId, slot, panel, card, results) {
      slot.innerHTML = '';
      let data;
      try {
        const res = await fetch(`${_APPLICANT_BASE}/${encodeURIComponent(item.id)}/flagged-facts`, { credentials: 'same-origin' });
        if (!res.ok) return;
        data = await res.json();
      } catch { return; }
      const flagged = (data && Array.isArray(data.flagged))
        ? data.flagged.filter(f => typeof f === 'string' && f.trim())
        : [];
      if (!flagged.length) return;   // nothing to double-check → render nothing
      const campaignId = (data && data.campaign_id) ? String(data.campaign_id) : '';
      _renderApplicantFlaggedFacts(item, appId, slot, flagged, campaignId, panel, card, results);
    }

    // Build the flagged-facts panel: a warm-toned card listing each fact with the
    // confirm ("add to my profile") and remove ("take it out of this draft")
    // actions. Reuses the workspace design system (`.memory-item`, `.cal-btn`-tier
    // `.doclib-card-text-btn`, the same `var(--orange)` caution tone the degraded
    // badge uses). Fact labels are set via textContent (never innerHTML), so the
    // model-derived tokens can never inject markup.
    function _renderApplicantFlaggedFacts(item, appId, slot, flagged, campaignId, panel, card, results) {
      slot.innerHTML = '';
      const wrap = document.createElement('div');
      wrap.className = 'memory-item doclib-applicant-flagged';
      wrap.style.cssText = 'font-size:12px;border:1px solid var(--orange, #ffb86c);border-radius:6px;padding:8px;display:flex;flex-direction:column;gap:8px;';

      const head = document.createElement('div');
      head.style.cssText = 'font-weight:600;display:flex;align-items:center;gap:5px;color:var(--orange, #ffb86c);';
      head.innerHTML =
        '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
          'stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;">' +
          '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>' +
          '<line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>' +
        '<span>A few facts to double-check</span>';
      head.title = "These specifics appear in this draft but aren't in your profile yet. Confirm the true ones so I can use them again, or remove them. Nothing is sent until you approve.";
      wrap.appendChild(head);

      const intro = document.createElement('div');
      intro.style.cssText = 'opacity:0.8;';
      intro.textContent = "I wrote this to read its strongest. These details aren't in your profile yet — please confirm they're true, or remove them from this draft:";
      wrap.appendChild(intro);

      const list = document.createElement('div');
      list.style.cssText = 'display:flex;flex-direction:column;gap:6px;';
      wrap.appendChild(list);

      flagged.forEach(fact => {
        const row = document.createElement('div');
        row.className = 'doclib-applicant-flagged-row';
        row.style.cssText = 'display:flex;align-items:center;gap:6px;flex-wrap:wrap;';

        const label = document.createElement('span');
        label.style.cssText = 'flex:1;min-width:120px;font-weight:600;';
        label.textContent = fact;   // textContent, not innerHTML — no markup injection
        row.appendChild(label);

        const addBtn = document.createElement('button');
        addBtn.className = 'doclib-card-text-btn doclib-card-action-btn odec-confirm';
        addBtn.textContent = "Yes, that's true — add to my profile";
        addBtn.title = 'Save this as a real detail about you so I can use it again and it stops being flagged.';

        const removeBtn = document.createElement('button');
        removeBtn.className = 'doclib-card-text-btn doclib-card-action-btn doclib-card-text-btn-danger';
        removeBtn.textContent = 'Remove';
        removeBtn.title = 'Take this detail out of this draft.';

        addBtn.addEventListener('click', async () => {
          if (!campaignId) {
            if (uiModule) uiModule.showError("I couldn't tell which profile to add this to.");
            return;
          }
          addBtn.disabled = true; removeBtn.disabled = true;
          const orig = addBtn.textContent; addBtn.textContent = 'Adding…';
          try {
            // Persist through the SAME confirm-conflict endpoint the onboarding
            // Q&A-conflicts flow uses (routes/applicant_setup_routes.py). Once it is
            // in the attribute cloud the fabrication check no longer flags it.
            const res = await fetch(`${API_BASE}/api/applicant/setup/onboarding/${encodeURIComponent(campaignId)}/confirm-conflict`, {
              method: 'POST', credentials: 'same-origin',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ attribute: fact, value: fact }),
            });
            if (!res.ok) throw new Error(await _applicantErrText(res));
            if (uiModule) uiModule.showToast('Added to your profile');
            row.remove();
            if (!list.children.length) slot.innerHTML = '';   // collapse when done
          } catch (err) {
            addBtn.disabled = false; removeBtn.disabled = false; addBtn.textContent = orig;
            if (uiModule) uiModule.showError(err.message || String(err));
          }
        });

        removeBtn.addEventListener('click', async () => {
          addBtn.disabled = true; removeBtn.disabled = true;
          removeBtn.textContent = 'Removing…';
          try {
            // A subtract turn takes the phrasing out of the draft, reusing the same
            // review turn loop (kind:'subtract') the "ask for a change" box drives.
            const res = await fetch(`${_APPLICANT_BASE}/${encodeURIComponent(item.id)}/turn`, {
              method: 'POST', credentials: 'same-origin',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ kind: 'subtract', instruction: fact }),
            });
            if (!res.ok) throw new Error(await _applicantErrText(res));
            const next = await res.json();
            if (uiModule) uiModule.showToast('Removed from this draft');
            // Re-render the whole review from the new session so the redline +
            // the remaining flagged facts reflect the edit (mirrors the send box).
            _renderApplicantReview(item, appId, panel, next, card, results);
          } catch (err) {
            addBtn.disabled = false; removeBtn.disabled = false; removeBtn.textContent = 'Remove';
            if (uiModule) uiModule.showError(err.message || String(err));
          }
        });

        row.appendChild(addBtn);
        row.appendChild(removeBtn);
        list.appendChild(row);
      });

      slot.appendChild(wrap);
    }

    // Pull a readable message out of the proxy's error JSON ({error,message,...}).
    async function _applicantErrText(res) {
      try {
        const j = await res.json();
        return (j && (j.message || j.detail)) || ("That didn't go through (error " + res.status + '). Try again shortly.');
      } catch { return "That didn't go through (error " + res.status + '). Try again shortly.'; }
    }

    // The Applications panel: a small "look up an application" form plus a
    // results area. We intentionally key off the application id because the
    // engine lists generated materials per application (there is no global
    // dump), and that id is shown wherever an application is tracked.
    function _renderLibApplicant() {
      const grid = document.getElementById('doclib-applicant-grid');
      const stats = document.getElementById('doclib-applicant-stats');
      if (!grid) return;
      grid.innerHTML = '';

      const wrap = document.createElement('div');
      wrap.className = 'doclib-applicant-lookup';
      wrap.style.cssText = 'display:flex;flex-direction:column;gap:10px;';
      wrap.innerHTML =
        '<div class="memory-toolbar" style="gap:6px;">' +
          '<input type="text" id="doclib-applicant-appid" class="memory-search-input" ' +
            'placeholder="Application ID…" ' +
            'title="Paste the ID of the application whose resume and cover letter you want to review." ' +
            'style="flex:1;min-width:160px;" />' +
          '<button class="memory-toolbar-btn" id="doclib-applicant-lookup-btn" ' +
            'title="Show the tailored materials generated for this application.">' +
            '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>Show documents</button>' +
        '</div>' +
        '<div id="doclib-applicant-results"></div>' +
        // Resume-variant library: the lineage of tailored resumes tried for a job
        // search, with fit scores + approval state (FR-RESUME-6 / FR-UI-6).
        '<div class="memory-desc doclib-desc" style="margin-top:6px;border-top:1px solid var(--color-border,rgba(128,128,128,0.2));padding-top:8px;">' +
          'Resume versions — the different takes on your resume I’ve tried for a job search, and how they relate.</div>' +
        '<div class="memory-toolbar" style="gap:6px;">' +
          '<input type="text" id="doclib-variant-campaign" class="memory-search-input" ' +
            'placeholder="Job-search ID…" ' +
            'title="Paste the ID of the job search whose resume versions you want to see." ' +
            'style="flex:1;min-width:160px;" />' +
          '<button class="memory-toolbar-btn" id="doclib-variant-lookup-btn" ' +
            'title="Show the resume versions tried for this job search.">' +
            '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>Show versions</button>' +
        '</div>' +
        '<div id="doclib-variant-results"></div>';
      grid.appendChild(wrap);

      const input = wrap.querySelector('#doclib-applicant-appid');
      const btn = wrap.querySelector('#doclib-applicant-lookup-btn');
      const results = wrap.querySelector('#doclib-applicant-results');
      if (_applicantLastAppId) input.value = _applicantLastAppId;

      const _go = () => {
        const id = (input.value || '').trim();
        if (!id) { if (uiModule) uiModule.showError('Enter an application ID to see its materials.'); return; }
        _applicantLastAppId = id;
        _loadApplicantMaterials(id, results);
      };
      btn.addEventListener('click', _go);
      // lens 01 #15: guard against firing on an IME composition-commit Enter
      // (CJK / dead-key input), matching the Vault/Chat fix pattern.
      input.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter' || e.isComposing || e.keyCode === 229) return;
        e.preventDefault(); _go();
      });

      // Variant-library lookup (mirrors the application lookup above).
      const vInput = wrap.querySelector('#doclib-variant-campaign');
      const vBtn = wrap.querySelector('#doclib-variant-lookup-btn');
      const vResults = wrap.querySelector('#doclib-variant-results');
      if (_variantLastCampaign) vInput.value = _variantLastCampaign;
      const _goVariants = () => {
        const id = (vInput.value || '').trim();
        if (!id) { if (uiModule) uiModule.showError('Enter a job-search ID to see its resume versions.'); return; }
        _variantLastCampaign = id;
        _loadVariantLibrary(id, vResults);
      };
      vBtn.addEventListener('click', _goVariants);
      // lens 01 #15: same IME-composition guard as the application-id lookup above.
      vInput.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter' || e.isComposing || e.keyCode === 229) return;
        e.preventDefault(); _goVariants();
      });
      if (_variantLastCampaign) _loadVariantLibrary(_variantLastCampaign, vResults);

      // On-demand generation (FR-RESUME-10 / FR-ANSWER-1): draft a cover letter or a
      // screening answer for an application; the draft lands in the review list above
      // and goes through the same review-before-use gate. Reuses the job-search +
      // application IDs already entered on this panel; the truthful ground-truth text
      // is built server-side from the profile (the UI never handles the résumé blob).
      const genWrap = document.createElement('div');
      genWrap.style.cssText = 'border-top:1px solid var(--color-border,rgba(128,128,128,0.2));padding-top:8px;';
      genWrap.innerHTML =
        '<div class="memory-desc doclib-desc">I’ll draft a document for this application — it comes to you for review before it’s ever used.</div>' +
        '<div class="memory-toolbar" style="gap:6px;flex-wrap:wrap;">' +
          '<button class="memory-toolbar-btn" id="doclib-gen-cover-btn" title="Write a cover letter for the application ID above.">Draft cover letter</button>' +
          '<button class="memory-toolbar-btn" id="doclib-gen-answer-btn" title="Answer a screening question for the application ID above.">Draft screening answer</button>' +
          '<button class="memory-toolbar-btn" id="doclib-gen-fill-btn" title="Fill in the blanks of your OWN cover-letter template — no AI writing, just merge fields.">Fill a template</button>' +
        '</div>' +
        '<div id="doclib-gen-status" class="doclib-empty" style="display:none;padding:8px;"></div>' +
        '<div id="doclib-fill-panel" style="display:none;flex-direction:column;gap:6px;border-top:1px solid var(--color-border,rgba(128,128,128,0.2));padding-top:8px;margin-top:4px;">' +
          '<div class="memory-desc doclib-desc">Paste your own template with <code>{{merge fields}}</code> (e.g. <code>{{company}}</code>) and give the values below — filled deterministically, no AI involved.</div>' +
          '<textarea class="memory-search-input" id="doclib-fill-template" rows="4" ' +
            'placeholder="Dear {{company}}, I am excited to apply for the {{role}} position..."></textarea>' +
          '<textarea class="memory-search-input" id="doclib-fill-context" rows="3" ' +
            'placeholder="One field per line, e.g.&#10;company: Acme Corp&#10;role: Software Engineer"></textarea>' +
          '<div class="memory-toolbar" style="gap:6px;">' +
            '<button class="memory-toolbar-btn" id="doclib-fill-go-btn">Fill template</button>' +
          '</div>' +
          '<textarea class="memory-search-input" id="doclib-fill-output" rows="4" readonly ' +
            'placeholder="Your filled letter will appear here." style="display:none;"></textarea>' +
          '<div class="memory-toolbar" style="gap:6px;">' +
            '<button class="memory-toolbar-btn" id="doclib-fill-copy-btn" style="display:none;">Copy to clipboard</button>' +
          '</div>' +
        '</div>';
      wrap.appendChild(genWrap);

      const genStatus = genWrap.querySelector('#doclib-gen-status');
      const _setGen = (msg) => { genStatus.style.display = 'block'; genStatus.textContent = msg; };
      const _genIds = () => ({
        campaign_id: (vInput.value || '').trim(),
        application_id: (input.value || '').trim(),
      });
      const _needIds = (ids) => {
        if (!ids.campaign_id || !ids.application_id) {
          if (uiModule) uiModule.showError('Enter a job-search ID and an application ID above first.');
          return false;
        }
        return true;
      };
      // lens 01 #6: both draft actions below fired a POST with no in-flight
      // guard, so an impatient double-click drafted two cover letters / two
      // answers (two engine generations, two review items). Disable the
      // button for the duration of its own request, matching every other
      // button in this file (see the Approve/Download/Promote buttons below).
      const coverBtn = genWrap.querySelector('#doclib-gen-cover-btn');
      const coverBtnLabel = coverBtn.textContent;
      coverBtn.addEventListener('click', async () => {
        const ids = _genIds();
        if (!_needIds(ids)) return;
        if (coverBtn.disabled) return;
        coverBtn.disabled = true;
        coverBtn.textContent = 'Writing…';
        _setGen('Writing a cover letter…');
        try {
          const res = await fetch(`${_APPLICANT_BASE}/cover-letter`, {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...ids, role_requires: true }),
          });
          if (!res.ok) { _setGen(await _applicantErrText(res)); return; }
          const data = await res.json();
          if (data && data.generated === false) {
            _setGen('No cover letter was needed for this role.');
          } else {
            _setGen('Cover letter drafted — see the review list above.');
            _applicantLastAppId = ids.application_id;
            _loadApplicantMaterials(ids.application_id, results);
          }
        } catch { _setGen('I couldn’t connect just now. Try again shortly.'); }
        finally { coverBtn.disabled = false; coverBtn.textContent = coverBtnLabel; }
      });
      const answerBtn = genWrap.querySelector('#doclib-gen-answer-btn');
      const answerBtnLabel = answerBtn.textContent;
      answerBtn.addEventListener('click', async () => {
        const ids = _genIds();
        if (!_needIds(ids)) return;
        if (answerBtn.disabled) return;
        // lens 01 #10: this used to be a bare window.prompt() — no multiline,
        // no paste comfort, off-theme, blocks the main thread. Lift the same
        // styledPrompt the digest's Pass flow already uses (falling back to
        // window.prompt only if the kit helper is somehow unavailable).
        const question = ((
          uiModule && uiModule.styledPrompt
            ? await uiModule.styledPrompt('What screening question should I answer?', {
                title: 'Draft a screening answer',
                placeholder: 'Paste the exact screening question here',
                confirmText: 'Draft answer',
                maxLength: 2000,
              })
            : window.prompt('What screening question should I answer?')
        ) || '').trim();
        if (!question) return;
        answerBtn.disabled = true;
        answerBtn.textContent = 'Drafting…';
        _setGen('Drafting an answer…');
        try {
          const res = await fetch(`${_APPLICANT_BASE}/screening-answer`, {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...ids, question }),
          });
          if (!res.ok) { _setGen(await _applicantErrText(res)); return; }
          _setGen('Answer drafted — see the review list above.');
          _applicantLastAppId = ids.application_id;
          _loadApplicantMaterials(ids.application_id, results);
        } catch { _setGen('I couldn’t connect just now. Try again shortly.'); }
        finally { answerBtn.disabled = false; answerBtn.textContent = answerBtnLabel; }
      });

      // Template merge-fill (dark-engine audit item 41): deterministic {{field}}
      // substitution for a user's OWN saved cover-letter template, no LLM call —
      // a complementary path to "Draft cover letter" above for someone who
      // already has wording they like and just wants it filled in for THIS
      // application. Toggles a small inline panel rather than a modal, matching
      // the rest of this lookup form.
      const fillPanel = genWrap.querySelector('#doclib-fill-panel');
      const fillTemplate = genWrap.querySelector('#doclib-fill-template');
      const fillContext = genWrap.querySelector('#doclib-fill-context');
      const fillOutput = genWrap.querySelector('#doclib-fill-output');
      const fillCopyBtn = genWrap.querySelector('#doclib-fill-copy-btn');
      genWrap.querySelector('#doclib-gen-fill-btn').addEventListener('click', () => {
        const showing = fillPanel.style.display !== 'none';
        fillPanel.style.display = showing ? 'none' : 'flex';
      });
      // Parses "key: value" lines (one field per line) into a plain context object;
      // blank lines and lines without a colon are skipped rather than erroring, so
      // a stray blank line doesn't block the fill.
      const _parseFillContext = (raw) => {
        const out = {};
        (raw || '').split('\n').forEach((line) => {
          const idx = line.indexOf(':');
          if (idx < 0) return;
          const key = line.slice(0, idx).trim();
          const value = line.slice(idx + 1).trim();
          if (key) out[key] = value;
        });
        return out;
      };
      genWrap.querySelector('#doclib-fill-go-btn').addEventListener('click', async () => {
        const template = (fillTemplate.value || '').trim();
        if (!template) {
          if (uiModule) uiModule.showError('Paste your cover-letter template first.');
          return;
        }
        const context = _parseFillContext(fillContext.value);
        _setGen('Filling in your template…');
        try {
          const res = await fetch(`${_APPLICANT_BASE}/cover-letter/fill`, {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ template, context }),
          });
          if (!res.ok) { _setGen(await _applicantErrText(res)); return; }
          const data = await res.json();
          fillOutput.value = (data && data.filled) || '';
          fillOutput.style.display = 'block';
          fillCopyBtn.style.display = 'inline-block';
          _setGen('Template filled below — nothing was sent to the review list.');
        } catch { _setGen('I couldn’t connect just now. Try again shortly.'); }
      });
      fillCopyBtn.addEventListener('click', async () => {
        try {
          if (uiModule && uiModule.copyToClipboard) await uiModule.copyToClipboard(fillOutput.value || '');
          else await navigator.clipboard.writeText(fillOutput.value || '');
          if (uiModule) uiModule.showToast('Copied to clipboard');
        } catch { if (uiModule) uiModule.showError('Failed to copy'); }
      });

      // Confirm the engine is reachable up front, and give a clear status line.
      results.innerHTML = '';
      const note = document.createElement('div');
      note.className = 'doclib-empty';
      note.style.cssText = 'padding:14px;';
      note.textContent = 'Checking the connection…';
      results.appendChild(note);
      fetch(`${_APPLICANT_BASE}/library`, { credentials: 'same-origin' })
        .then(async (res) => {
          if (!res.ok) { note.textContent = await _applicantErrText(res); return; }
          if (stats) stats.textContent = 'connected';
          note.textContent = _applicantLastAppId
            ? 'Loading…'
            : 'Enter an application ID above to see its tailored resume and cover letter.';
          if (_applicantLastAppId) _loadApplicantMaterials(_applicantLastAppId, results);
        })
        .catch(e => { console.error('Failed to load:', e); note.textContent = 'I couldn’t connect just now. Try again shortly.'; });
    }

    // Fetch + render the resume-variant library (lineage / fit / approval) for a
    // job search. Lifted from the admin Variants view so users see the same shape,
    // owner-scoped, in the white-labeled library (FR-RESUME-6 / FR-UI-6).
    async function _loadVariantLibrary(campaignId, container) {
      if (!container) return;
      const esc = (s) => (uiModule ? uiModule.esc(String(s ?? '')) : String(s ?? ''));
      container.innerHTML = '<div class="doclib-empty" style="padding:12px;">Loading resume versions…</div>';
      let data;
      try {
        const res = await fetch(`${_APPLICANT_BASE}/variants/${encodeURIComponent(campaignId)}`,
          { credentials: 'same-origin' });
        if (!res.ok) {
          container.innerHTML = `<div class="doclib-empty" style="padding:12px;">${esc(await _applicantErrText(res))}</div>`;
          return;
        }
        data = await res.json();
      } catch {
        container.innerHTML = '<div class="doclib-empty" style="padding:12px;">I couldn’t connect just now. Try again shortly.</div>';
        return;
      }
      const variants = (data && data.variants) || [];
      if (!variants.length) {
        container.innerHTML = '<div class="doclib-empty" style="padding:12px;">I haven’t tried any resume versions for this job search yet.</div>';
        return;
      }
      container.innerHTML = variants.map((v) => {
        const rawId = v.variant_id || v.id || '';
        const id = rawId || 'Variant';
        // "Why this variant" (dark-engine audit item 53): the engine's real
        // JD-keyword coverage for this tailored resume, in plain language.
        // 'not scored' when this variant has not been JD-matched yet.
        const scoreText = _applicantFitScoreText(v.fit_scores) || 'not scored';
        const approved = v.approved === true ? 'approved' : 'needs review';
        const depth = v.lineage_depth ? ` · ${esc(v.lineage_depth)} edits deep` : '';
        const from = v.parent_id ? ` · from ${esc(v.parent_id)}` : '';
        // Ancestry breadcrumb (dark-engine audit item 50): "Original -> Tailored
        // for Acme -> this version" so the relationship between tailored resumes
        // is readable, not just a raw parent id + depth count. Hidden entirely
        // for a lone root variant (nothing to trace).
        const breadcrumb = _applicantLineageBreadcrumb(v.lineage, esc);
        const breadcrumbHtml = breadcrumb
          ? `<div class="memory-desc" style="opacity:0.65;margin-top:2px;font-size:11px;" ` +
              `title="How this tailored resume was derived, oldest first.">${breadcrumb}</div>`
          : '';
        // Degraded-draft warning (dark-engine audit item 40): the engine flags a
        // résumé variant that fell back to a deterministic template (the writing
        // model's tier ladder was exhausted) via ``degraded`` — same warning tone
        // as the card-level badge in ``_applicantDegradedBadge`` above, in the
        // string-template shape this list already uses.
        const degradedHtml = v.degraded
          ? `<div style="font-size:11px;margin-top:4px;padding:3px 8px;border-radius:6px;` +
              `border:1px solid var(--orange, #ffb86c);color:var(--orange, #ffb86c);` +
              `display:inline-block;" title="This tailored resume used a basic template ` +
              `because the writing model was unavailable — review it closely.">` +
              `Fallback draft — model was unavailable</div>`
          : '';
        // lens 01 #65: these rows used to be inert — no way to read the
        // variant or open it from here. Make the card itself clickable and
        // keyboard-activatable; the open action reuses the SAME
        // download-the-compiled-PDF fetch the materials-list variant card's
        // "Download PDF" button already uses (wired below, once the cards
        // are in the DOM), just opened inline instead of force-downloaded so
        // it reads as "view" rather than "save".
        return `<div class="admin-card doclib-variant-card" data-variant-id="${esc(rawId)}" ` +
          `role="${rawId ? 'button' : 'group'}" tabindex="${rawId ? '0' : '-1'}" ` +
          `style="margin-top:6px;${rawId ? 'cursor:pointer;' : ''}" ` +
          `title="${rawId ? 'Open this resume version’s PDF.' : ''}">` +
          `<div style="font-weight:600;">${esc(v.is_root ? 'Base resume' : id)}</div>` +
          `<div class="memory-desc" style="opacity:0.7;margin-top:2px;">` +
            `${esc(scoreText)} · ${esc(approved)}${depth}${from}</div>` +
          breadcrumbHtml +
          degradedHtml +
        `</div>`;
      }).join('');

      // Wire up the open action once the cards are in the DOM (attributes
      // alone don't get you keyboard Enter/Space activation or a click
      // handler). Deep-links into the same PDF the materials-view "Download
      // PDF" button serves for a resume variant (`_applicantCard` below) —
      // the one existing "open" action a bare variant id already supports.
      container.querySelectorAll('.doclib-variant-card[data-variant-id]').forEach((el) => {
        const vid = el.getAttribute('data-variant-id');
        if (!vid) return;
        const _openVariant = async () => {
          try {
            const res = await fetch(`${_APPLICANT_BASE}/variants/${encodeURIComponent(vid)}/download`, { credentials: 'same-origin' });
            if (!res.ok) throw new Error(await _applicantErrText(res));
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            window.open(url, '_blank', 'noopener');
            setTimeout(() => URL.revokeObjectURL(url), 60000);
          } catch (err) {
            if (uiModule) uiModule.showError((err && err.message) || String(err));
          }
        };
        el.addEventListener('click', _openVariant);
        el.addEventListener('keydown', (e) => {
          if (e.key !== 'Enter' && e.key !== ' ') return;
          e.preventDefault();
          _openVariant();
        });
      });
    }

    // Résumé <-> job-posting keyword match explainer (product-gaps backlog
    // #23): "Match score: 78/100 — you cover React, Python, AWS; consider
    // adding: Kubernetes, GraphQL". Advisory only — a plain-language line under
    // the materials header, never blocking the review/approve flow below it.
    // Fetched separately from the materials list (its own small proxy read,
    // engine `GET /api/documents/jd-match/{application_id}`) so a slow/failed
    // score lookup never delays the materials themselves; failures are a
    // silent no-op (the line just doesn't appear) rather than an error toast.
    async function _loadJdMatch(appId, container) {
      if (!container) return;
      let data;
      try {
        const res = await fetch(`${_APPLICANT_BASE}/jd-match/${encodeURIComponent(appId)}`, { credentials: 'same-origin' });
        if (!res.ok) return;
        data = await res.json();
      } catch { return; }
      if (!data || typeof data.score !== 'number') return;
      const matched = Array.isArray(data.matched) ? data.matched : [];
      const missing = Array.isArray(data.missing) ? data.missing : [];
      if (!matched.length && !missing.length) return; // nothing to report yet

      const line = document.createElement('div');
      line.className = 'doclib-applicant-jdmatch';
      line.style.cssText = 'font-size:12px;opacity:0.85;padding:0 0 8px;display:flex;align-items:center;gap:6px;flex-wrap:wrap;';

      // Reuses the SAME compact pill styling as the "All approved" / "Needs
      // review" gate badge above (border + var(--border), no new visual system).
      const scoreChip = document.createElement('span');
      scoreChip.className = 'doclib-applicant-jdmatch-score';
      scoreChip.style.cssText = 'font-size:11px;padding:2px 8px;border-radius:10px;border:1px solid var(--border);font-weight:600;flex-shrink:0;';
      scoreChip.title = 'How many of the posting’s keywords already show up in your resume — an estimate, not a hard requirement.';
      scoreChip.textContent = `Match score: ${data.score}/100`;
      line.appendChild(scoreChip);

      const bits = [];
      if (matched.length) bits.push(`you cover ${matched.slice(0, 6).join(', ')}`);
      if (bits.length) {
        const detail = document.createElement('span');
        detail.textContent = bits.join('; ');
        line.appendChild(detail);
      }
      // Missing-terms panel (P1-8): each missing keyword is a SUGGESTION chip.
      // Tapping one only pre-fills the "Ask for a change" box in the open review
      // panel below — the change still goes through the normal request-change →
      // redline → approve path, so nothing is ever auto-inserted (the engine's
      // truthfulness guard also vets the resulting draft server-side).
      if (missing.length) {
        const suggestWrap = document.createElement('span');
        suggestWrap.className = 'doclib-applicant-jdmatch-missing';
        suggestWrap.style.cssText = 'display:inline-flex;align-items:center;gap:4px;flex-wrap:wrap;';
        const lbl = document.createElement('span');
        lbl.textContent = 'consider adding:';
        suggestWrap.appendChild(lbl);
        missing.slice(0, 6).forEach((term) => {
          const chip = document.createElement('button');
          chip.type = 'button';
          chip.className = 'doclib-card-text-btn doclib-applicant-suggest-term';
          chip.style.cssText = 'font-size:11px;padding:1px 8px;';
          chip.textContent = `+ ${term}`;
          chip.title = `Suggest working “${term}” into the document under review — nothing is added until you request the change and approve the result.`;
          chip.addEventListener('click', () => _suggestMissingTerm(container, term));
          suggestWrap.appendChild(chip);
        });
        line.appendChild(suggestWrap);
      }
      container.appendChild(line);
    }

    // Pre-fill the open review panel's "Ask for a change" box with a suggested
    // keyword addition (P1-8). Deliberately NOT a direct write to the document:
    // the suggestion only lands in the instruction box; the user still presses
    // "Request change" (an ordinary redline turn, truthfulness-gated on the
    // engine) and then approves the redline — the existing approve path.
    function _suggestMissingTerm(slot, term) {
      const results = slot && slot.parentElement;
      // Only act on an UNAMBIGUOUS target: with several review panels open the
      // first-in-DOM box could belong to a different document than the user
      // means — ask them to narrow it down instead of guessing.
      const boxes = results ? results.querySelectorAll('.doclib-applicant-instruction') : [];
      if (!boxes.length) {
        if (uiModule) uiModule.showToast('Open Review on a document below first, then tap a keyword to suggest it.');
        return;
      }
      if (boxes.length > 1) {
        if (uiModule) uiModule.showToast('More than one review panel is open — close the others (or type the suggestion into the one you mean) so the keyword lands on the right document.');
        return;
      }
      const box = boxes[0];
      const suggestion = `Work in “${term}” where my real experience genuinely supports it.`;
      const existing = (box.value || '').trim();
      if (!existing.includes(suggestion)) {
        box.value = existing ? `${existing}\n${suggestion}` : suggestion;
      }
      // Fire the input listener so the review panel's draft store keeps the
      // suggestion across re-renders, exactly like typed text.
      box.dispatchEvent(new Event('input', { bubbles: true }));
      box.focus();
      if (uiModule) uiModule.showToast('Suggestion added — press “Request change”, then approve the result.');
    }

    // Company-research provenance (dark-engine audit #76): when the agent hit a
    // genuine company/role knowledge gap while preparing this application's
    // materials, it escalated to the capped deep-research tool and folded a
    // report into the writing — surfaced here so the reviewer sees WHICH
    // research informed what they're about to approve, instead of trusting it
    // blindly. Fetched separately from the redline itself (its own small read,
    // engine `GET /api/admin/research-provenance/{id}`) so a slow/failed lookup
    // never delays the review; degrades to nothing when research was never used
    // for this application (the common case) or its checkpoint has already been
    // cleared (a since-submitted application).
    async function _loadResearchProvenance(appId, container) {
      if (!container) return;
      let data;
      try {
        const res = await fetch(`${_APPLICANT_BASE}/research-provenance/${encodeURIComponent(appId)}`, { credentials: 'same-origin' });
        if (!res.ok) return;
        data = await res.json();
      } catch { return; }
      if (!data || !data.used) return;

      const box = document.createElement('div');
      box.className = 'doclib-applicant-research';
      box.style.cssText = 'font-size:12px;border:1px solid var(--border);border-radius:6px;padding:8px;display:flex;flex-direction:column;gap:4px;';

      const badge = document.createElement('span');
      badge.style.cssText = 'font-size:11px;padding:2px 8px;border-radius:10px;border:1px solid var(--border);font-weight:600;align-self:flex-start;';
      badge.title = 'I looked up the company before writing this — it informed the wording below.';
      badge.textContent = data.company ? `Company research used — ${data.company}` : 'Company research used';
      box.appendChild(badge);

      if (data.summary_excerpt) {
        const excerpt = document.createElement('div');
        excerpt.style.cssText = 'opacity:0.8;';
        excerpt.textContent = data.summary_excerpt;
        box.appendChild(excerpt);
      }

      const sources = Array.isArray(data.sources) ? data.sources : [];
      if (sources.length) {
        const list = document.createElement('ul');
        list.style.cssText = 'margin:0;padding-left:16px;';
        sources.forEach((s) => {
          const label = s && (s.title || s.url);
          if (!label) return;
          const li = document.createElement('li');
          if (s.url) {
            const a = document.createElement('a');
            a.href = s.url;
            a.target = '_blank';
            a.rel = 'noopener noreferrer';
            a.textContent = s.title || s.url;
            li.appendChild(a);
          } else {
            li.textContent = label;
          }
          list.appendChild(li);
        });
        box.appendChild(list);
      }
      container.appendChild(box);
    }

    // Fetch + render the materials for one application id.
    async function _loadApplicantMaterials(appId, results) {
      if (!results) return;
      results.innerHTML = '';
      try {
        const _sp = spinnerModule.createWhirlpool ? spinnerModule.createWhirlpool(22) : null;
        if (_sp) { _sp.element.style.cssText = 'margin:18px auto;display:block;'; results.appendChild(_sp.element); }
        else results.appendChild(spinnerModule.createLoadingRow('Loading…'));
      } catch { results.innerHTML = '<div class="doclib-empty">Loading…</div>'; }

      let data;
      try {
        const res = await fetch(`${_APPLICANT_BASE}/applications/${encodeURIComponent(appId)}`, { credentials: 'same-origin' });
        if (!res.ok) { results.innerHTML = `<div class="doclib-empty" style="padding:14px;">${_esc(await _applicantErrText(res))}</div>`; return; }
        data = await res.json();
      } catch {
        results.innerHTML = '<div class="doclib-empty" style="padding:14px;">I couldn’t connect just now. Try again shortly.</div>';
        return;
      }

      const items = (data && Array.isArray(data.items)) ? data.items : [];
      results.innerHTML = '';

      const head = document.createElement('div');
      head.style.cssText = 'display:flex;align-items:center;gap:8px;margin:2px 0 8px;';
      // A non-existent/empty application must NOT read as fully-approved: the
      // engine returns an empty 200 for a bogus id, making `data.all_approved`
      // vacuously true for 0 items. Only show the "All approved" badge when
      // there is at least one material; the honest empty-state copy below
      // covers the truly-empty case.
      const gateOk = items.length > 0 && !!(data && data.all_approved);
      // Kill the "All approved" dead end (Top-25 #13): once every material for
      // this application has cleared review there is nowhere left to go on this
      // surface — the actual next step is the submit decision, which lives in
      // the Portal (final_approval / request_final_approval rows render there;
      // see applicantPortal.js `_renderFinal`). Reuse the SAME cross-lane seam
      // applicantChat.js's own "Open Pending" CTA uses
      // (`window.applicantPortalModule.openApplicantPortal()`, falling back to a
      // synthetic click on the `#rail-portal` launcher) rather than inventing a
      // new one.
      head.innerHTML =
        `<span class="memory-count" style="opacity:0.7;">${items.length} item${items.length === 1 ? '' : 's'}</span>` +
        `<span class="doclib-applicant-gate" title="${gateOk ? 'All materials for this application have been approved.' : 'Some materials still need your approval before this application can be sent.'}" ` +
          `style="font-size:11px;padding:2px 8px;border-radius:10px;border:1px solid var(--border);opacity:0.85;">` +
          `${gateOk ? 'All approved' : 'Needs review'}</span>` +
        (gateOk
          ? `<button type="button" class="cal-btn cal-btn-primary doclib-applicant-continue-submit" ` +
              `style="margin-left:auto;font-size:11px;padding:2px 10px;" ` +
              `title="Everything is approved — head to the submit step in your Pending home base">Continue to submit &rarr;</button>`
          // dark-engine audit item 2: a one-click "check what's missing and rebuild
          // it" action, since until now the engine's ensure-submittable auto-heal
          // (which this button calls) had no working caller anywhere in the product.
          : (items.length
              ? `<button type="button" class="cal-btn doclib-applicant-fix-documents" ` +
                  `style="margin-left:auto;font-size:11px;padding:2px 10px;" ` +
                  `title="Check this application's documents and rebuild anything missing">Fix documents</button>`
              : ''));
      results.appendChild(head);

      // Advisory keyword-match line (#23) — a fixed slot placed right under the
      // header so the async fetch (which resolves after this synchronous render
      // pass) fills in *in place* rather than appending after the material
      // cards below once it eventually completes.
      const jdMatchSlot = document.createElement('div');
      jdMatchSlot.className = 'doclib-applicant-jdmatch-slot';
      results.appendChild(jdMatchSlot);
      if (items.length) _loadJdMatch(appId, jdMatchSlot);

      if (gateOk) {
        const continueBtn = head.querySelector('.doclib-applicant-continue-submit');
        if (continueBtn) {
          continueBtn.addEventListener('click', () => {
            try {
              if (window.applicantPortalModule && typeof window.applicantPortalModule.openApplicantPortal === 'function') {
                window.applicantPortalModule.openApplicantPortal();
                return;
              }
            } catch { /* fall through */ }
            const rail = document.getElementById('rail-portal');
            if (rail) rail.click();
          });
        }
      } else {
        // "Fix documents": run the engine's ensure-submittable auto-heal for this
        // application, then refresh the card so any rebuilt/cleared material shows
        // up immediately (dark-engine audit item 2).
        const fixBtn = head.querySelector('.doclib-applicant-fix-documents');
        if (fixBtn) {
          fixBtn.addEventListener('click', async () => {
            fixBtn.disabled = true;
            const origLabel = fixBtn.textContent;
            fixBtn.textContent = 'Checking…';
            try {
              await ensureSubmittable(appId);
              if (uiModule) uiModule.showToast('All documents are ready to submit');
              await _loadApplicantMaterials(appId, results);
              return; // the card just re-rendered from scratch
            } catch (e) {
              const detail = e && e.body && e.body.detail;
              const msg = (typeof detail === 'string' && detail)
                || (e && e.message && e.message !== '[object Object]' && e.message)
                || 'Some documents still need your review before this can be submitted.';
              if (uiModule) uiModule.showToast(msg);
            }
            fixBtn.disabled = false;
            fixBtn.textContent = origLabel;
          });
        }
      }

      if (!items.length) {
        const empty = document.createElement('div');
        empty.className = 'doclib-empty';
        empty.style.cssText = 'padding:14px;';
        empty.textContent = "No tailored documents for this application yet. They appear here once I've drafted them.";
        results.appendChild(empty);
        return;
      }

      const list = document.createElement('div');
      list.className = 'doclib-grid';
      items.forEach(item => list.appendChild(_applicantCard(item, appId, results)));
      results.appendChild(list);
    }

    // lens 01 #40: Approve/Decline in the redline review panel used to just
    // call _loadApplicantMaterials, which tears the whole list down and
    // rebuilds it from scratch — scroll jumps to the top and the item the
    // reviewer was just looking at collapses back to its closed state. A
    // real in-place update of one row isn't structurally available here (the
    // approve/decline endpoints don't hand back enough to patch a card, and
    // the header's "All approved" gate/JD-match line depend on the FULL
    // list), so this reloads the list but preserves the reviewer's scroll
    // position and, best-effort, reopens the same item's review panel
    // afterwards so it doesn't read as having silently discarded their spot.
    async function _reloadApplicantMaterialsPreservingContext(appId, results, openItemId) {
      const scrollHost = (results && results.querySelector('.doclib-grid')) || results;
      const scrollTop = scrollHost ? scrollHost.scrollTop : 0;
      await _loadApplicantMaterials(appId, results);
      const newScrollHost = (results && results.querySelector('.doclib-grid')) || results;
      if (newScrollHost) newScrollHost.scrollTop = scrollTop;
      if (!openItemId || !results) return;
      const newCard = results.querySelector(`[data-item-id="${CSS.escape(String(openItemId))}"]`);
      const reopenBtn = newCard && newCard.querySelector('.doclib-applicant-review-toggle');
      if (reopenBtn) reopenBtn.click();
    }

    // One material card: title, approval state, content preview, and the
    // actions (open the review loop / quick-approve a resume variant).
    function _applicantCard(item, appId, results) {
      const card = document.createElement('div');
      card.className = 'doclib-card memory-item';
      // lens 01 #40: lets a full-list reload after Approve/Decline find this
      // SAME item's card again and restore what the reviewer was looking at.
      card.dataset.itemId = String(item.id);
      card.style.cssText = 'display:flex;flex-direction:column;gap:6px;';
      const approved = !!item.approved;
      const isVariant = (item.type || '').toLowerCase() === 'resume_variant';
      const content = (item.content || '').toString();
      const preview = content.length > 600 ? content.slice(0, 600) + '…' : content;

      const header = document.createElement('div');
      header.style.cssText = 'display:flex;align-items:center;gap:8px;';
      header.innerHTML =
        `<strong style="flex:1;">${_esc(_applicantTypeLabel(item.type))}</strong>` +
        `<span class="doclib-applicant-state" style="font-size:11px;padding:2px 8px;border-radius:10px;border:1px solid var(--border);opacity:0.85;" ` +
          `title="${approved ? 'Approved and ready to use.' : 'Not approved yet — review it before it is sent.'}">` +
          `${approved ? 'Approved' : 'Draft'}</span>`;
      card.appendChild(header);

      // Degraded-draft warning (dark-engine audit item 40) — placed right under
      // the header, above the preview, so it is the first thing a reviewer sees
      // on a fallback-template draft rather than approving it blind.
      const degradedBadge = _applicantDegradedBadge(item.degraded ? (item.degraded_reason || 'This draft used a fallback template.') : '');
      if (degradedBadge) card.appendChild(degradedBadge);

      if (preview) {
        const body = document.createElement('div');
        body.className = 'doclib-card-preview-text';
        body.style.cssText = 'font-size:12px;white-space:pre-wrap;opacity:0.8;max-height:120px;overflow:auto;border:1px solid var(--border);border-radius:6px;padding:8px;';
        body.textContent = preview;
        card.appendChild(body);
      }

      // "What I drew on" — the learned items (your saved preferences / playbooks /
      // a prior application) that shaped this draft. Transparency only; nothing
      // here changes what was written, and the draft is still fully editable
      // below. Hidden entirely when the assistant drew on nothing learned.
      const drewOn = _applicantProvenancePanel(item.provenance);
      if (drewOn) card.appendChild(drewOn);

      // "Why this variant" — the engine's JD-keyword coverage for this specific
      // tailored resume (dark-engine audit item 53). Advisory evidence for the
      // approve/download/promote decisions below; hidden entirely when this
      // variant has not been JD-matched yet (no fabricated percentage).
      if (isVariant) {
        const fitText = _applicantFitScoreText(item.fit_scores);
        if (fitText) {
          const fit = document.createElement('div');
          fit.className = 'doclib-card-fitscore';
          fit.style.cssText = 'font-size:11px;opacity:0.85;';
          fit.title = "How much of the job posting's language this tailored resume already covers, and the highest-signal terms it's still missing.";
          fit.textContent = fitText;
          card.appendChild(fit);
        }
      }

      const actions = document.createElement('div');
      actions.className = 'doclib-card-expanded-actions';
      actions.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;';

      // Resume variants approve through their own engine endpoint; everything
      // else goes through the full document review loop.
      if (isVariant) {
        const approveBtn = document.createElement('button');
        approveBtn.className = 'doclib-card-text-btn doclib-card-action-btn';
        approveBtn.textContent = approved ? 'Approved' : 'Approve resume';
        approveBtn.title = 'Approve this tailored resume so it can be used for this application.';
        approveBtn.disabled = approved;
        approveBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          approveBtn.disabled = true;
          approveBtn.textContent = 'Approving…';
          try {
            const res = await fetch(`${_APPLICANT_BASE}/variants/${encodeURIComponent(item.id)}/approve`, { method: 'POST', credentials: 'same-origin' });
            if (!res.ok) throw new Error(await _applicantErrText(res));
            if (uiModule) uiModule.showToast('Resume approved');
            _loadApplicantMaterials(appId, results);
          } catch (err) {
            approveBtn.disabled = false;
            approveBtn.textContent = 'Approve resume';
            if (uiModule) uiModule.showError(err.message || String(err));
          }
        });
        actions.appendChild(approveBtn);

        const downloadBtn = document.createElement('button');
        downloadBtn.className = 'doclib-card-text-btn doclib-card-action-btn';
        downloadBtn.textContent = 'Download PDF';
        downloadBtn.title = 'Save the compiled resume PDF for this variant.';
        downloadBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          downloadBtn.disabled = true;
          const original = downloadBtn.textContent;
          downloadBtn.textContent = 'Downloading…';
          try {
            const res = await fetch(`${_APPLICANT_BASE}/variants/${encodeURIComponent(item.id)}/download`, { credentials: 'same-origin' });
            if (!res.ok) throw new Error(await _applicantErrText(res));
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `resume-${item.id}.pdf`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
          } catch (err) {
            if (uiModule) uiModule.showError(err.message || String(err));
          } finally {
            downloadBtn.disabled = false;
            downloadBtn.textContent = original;
          }
        });
        actions.appendChild(downloadBtn);

        const promoteBtn = document.createElement('button');
        promoteBtn.className = 'doclib-card-text-btn doclib-card-action-btn';
        promoteBtn.textContent = 'Promote to base résumé';
        promoteBtn.title = 'Make this tailored resume the new starting point future resumes are built from.';
        promoteBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const ok = confirm('Make this resume the new base? Future tailored resumes will be built starting from this version instead of your original base résumé.');
          if (!ok) return;
          promoteBtn.disabled = true;
          const original = promoteBtn.textContent;
          promoteBtn.textContent = 'Promoting…';
          try {
            const res = await fetch(`${_APPLICANT_BASE}/variants/${encodeURIComponent(item.id)}/promote`, { method: 'POST', credentials: 'same-origin' });
            if (!res.ok) throw new Error(await _applicantErrText(res));
            if (uiModule) uiModule.showToast('This resume is now your base for future tailoring');
            _loadApplicantMaterials(appId, results);
          } catch (err) {
            promoteBtn.disabled = false;
            promoteBtn.textContent = original;
            if (uiModule) uiModule.showError(err.message || String(err));
          }
        });
        actions.appendChild(promoteBtn);
      } else {
        const reviewBtn = document.createElement('button');
        reviewBtn.className = 'doclib-card-text-btn doclib-card-action-btn doclib-applicant-review-toggle';
        reviewBtn.textContent = 'Review and edit';
        reviewBtn.title = 'Open this document, see the suggested changes, ask for tweaks, then approve it.';
        reviewBtn.addEventListener('click', (e) => { e.stopPropagation(); _openApplicantReview(item, appId, card, results); });
        actions.appendChild(reviewBtn);
      }
      card.appendChild(actions);

      // Inline review panel mounts here when opened.
      const panel = document.createElement('div');
      panel.className = 'doclib-applicant-review';
      panel.style.display = 'none';
      card.appendChild(panel);
      return card;
    }

    // Lens 04 #54: the "ask for a change" free-text instruction previously
    // lived only in the DOM textarea, so any re-render of the review surface
    // (a fresh turn's response re-rendering the panel, or a full materials
    // reload closing and reopening it) silently discarded whatever the user
    // had typed but not yet sent. Keyed by document id (module-level, mirrors
    // the persistence of other per-item Library state such as
    // `_librarySelectedIds`/`_chatsSelected` above), so the draft survives
    // both re-render paths and is restored whenever this item's review panel
    // is (re)built, then cleared once the instruction is actually submitted.
    const _reviewInstructionDrafts = new Map();

    // Open the interactive review session for a non-variant document and render
    // the redline + change box + approve / decline controls inline in the card.
    async function _openApplicantReview(item, appId, card, results) {
      const panel = card.querySelector('.doclib-applicant-review');
      if (!panel) return;
      if (panel.style.display !== 'none') {
        panel.style.display = 'none'; panel.innerHTML = '';
        // Restore the collapsed list-card height cap.
        card.style.maxHeight = ''; card.style.flexShrink = '';
        return;
      }
      panel.style.display = 'block';
      // List cards are capped at max-height:200px with overflow:visible for a uniform
      // list; the taller open review panel spilled out of that cap and overlapped the
      // neighbouring card. Lift the cap (and don't let flex squeeze it) so the open
      // card grows to fit the panel and the grid scrolls instead of overlapping.
      card.style.maxHeight = 'none'; card.style.flexShrink = '0';
      panel.innerHTML = '<div style="opacity:0.5;font-size:12px;padding:8px 2px;">Opening review…</div>';

      let session;
      try {
        const res = await fetch(`${_APPLICANT_BASE}/${encodeURIComponent(item.id)}/review`, { method: 'POST', credentials: 'same-origin' });
        if (!res.ok) throw new Error(await _applicantErrText(res));
        session = await res.json();
      } catch (err) {
        panel.innerHTML = `<div class="doclib-empty" style="padding:10px;">${_esc(err.message || String(err))}</div>`;
        return;
      }
      _renderApplicantReview(item, appId, panel, session, card, results);
    }

    // Render one review session state: the redline (additions / removals), the
    // turn history, a plain-language "ask for a change" box, and Approve /
    // Decline. Re-renders itself after each turn.
    function _renderApplicantReview(item, appId, panel, session, card, results) {
      panel.innerHTML = '';
      panel.style.cssText = 'display:block;margin-top:8px;border-top:1px solid var(--border);padding-top:8px;display:flex;flex-direction:column;gap:8px;';

      // Trust header (D1): make it unmistakable that review is safe — nothing is
      // sent until the user approves below.
      const header = document.createElement('div');
      header.style.cssText = 'font-size:12px;font-weight:600;opacity:0.85;';
      header.textContent = 'Nothing is submitted until you approve.';
      panel.appendChild(header);

      // Company-research provenance (dark-engine audit #76): best-effort, own
      // fetch so a slow/failed lookup never blocks the redline below.
      const researchSlot = document.createElement('div');
      panel.appendChild(researchSlot);
      _loadResearchProvenance(appId, researchSlot);

      // "A few facts to double-check" (P1-13): fact-class specifics the assistant
      // used that aren't in the profile yet, each with a one-tap confirm ("add to
      // my profile") / remove choice. Best-effort own fetch (renders nothing on a
      // clean draft or an engine error), so it never blocks the redline below.
      const flaggedSlot = document.createElement('div');
      panel.appendChild(flaggedSlot);
      _loadApplicantFlaggedFacts(item, appId, flaggedSlot, panel, card, results);

      // Redline: the engine returns a redline_state describing what changed
      // versus the base. The engine's side-by-side highlighted redline
      // (rendered_html: additions AND deletions vs base) is the PRIMARY
      // rendering; we only fall back to the green/red bullet list when no
      // rendered_html is returned, then to a neutral note. (D1)
      const rl = session && session.redline_state;
      const redline = document.createElement('div');
      redline.className = 'doclib-applicant-redline';
      redline.style.cssText = 'font-size:12px;border:1px solid var(--border);border-radius:6px;padding:8px;max-height:200px;overflow:auto;';
      const renderedHtml = rl && (rl.rendered_html || rl.html);
      const additions = rl && Array.isArray(rl.additions) ? rl.additions : [];
      const subtractions = rl && Array.isArray(rl.subtractions) ? rl.subtractions : (rl && Array.isArray(rl.removals) ? rl.removals : []);
      if (renderedHtml) {
        // PRIMARY: the engine-rendered side-by-side highlighted redline (both
        // additions and deletions vs the base). This HTML incorporates
        // scraped/model-derived content (posting text, LLM output), so it is
        // NOT trusted verbatim (lens 04 #69 — XSS sink): run it through the
        // same allowlist sanitizer markdown.js already uses for the other
        // engine/model-derived HTML fragment it renders (`<details>`/`<a>`
        // blocks) rather than assigning it to innerHTML raw.
        redline.innerHTML = markdownModule.sanitizeAllowedHtml(renderedHtml);
      } else if (additions.length || subtractions.length) {
        // FALLBACK: plain add/remove lists when the engine returns no rendered
        // redline HTML.
        const add = additions.map(a => `<li style="color:var(--color-success,#4caf50);">+ ${_esc(String(a))}</li>`).join('');
        const sub = subtractions.map(s => `<li style="color:var(--color-danger,#e06c75);">− ${_esc(String(s))}</li>`).join('');
        redline.innerHTML = `<div style="opacity:0.6;margin-bottom:4px;">Suggested changes — lines with + are text I'd add, − is text I'd remove</div><ul style="margin:0;padding-left:16px;list-style:none;">${add}${sub}</ul>`;
      } else {
        redline.innerHTML = '<div style="opacity:0.6;">No tracked changes to show — you can still ask for edits below.</div>';
      }
      panel.appendChild(redline);

      // lens 01 #63: the redline is the primary review artifact (the actual
      // resume diff the reviewer is deciding on) but was hard-capped at
      // 200px with no way to see more. Add a show-more/show-less toggle;
      // only surface it once the content actually overflows the compact cap
      // (checked after the browser has laid the node out).
      const redlineToggle = document.createElement('button');
      redlineToggle.type = 'button';
      redlineToggle.className = 'doclib-card-text-btn';
      redlineToggle.style.cssText = 'align-self:flex-start;font-size:11px;padding:2px 8px;display:none;';
      const _syncRedlineToggle = () => {
        const expanded = redline.style.maxHeight === 'none';
        const overflowing = redline.scrollHeight > redline.clientHeight;
        redlineToggle.style.display = (overflowing || expanded) ? 'inline-block' : 'none';
        redlineToggle.textContent = expanded ? 'Show less' : 'Show more';
        redlineToggle.title = expanded
          ? 'Collapse the changes back to a compact view.'
          : 'Expand to see the full set of changes.';
      };
      redlineToggle.addEventListener('click', () => {
        redline.style.maxHeight = redline.style.maxHeight === 'none' ? '200px' : 'none';
        _syncRedlineToggle();
      });
      panel.appendChild(redlineToggle);
      // Defer to the next frame so layout has settled after the innerHTML
      // assignment above (scrollHeight/clientHeight need a real layout pass).
      if (typeof requestAnimationFrame === 'function') requestAnimationFrame(_syncRedlineToggle);
      else _syncRedlineToggle();

      // "Compare to original" (dark-engine audit item 22): the review session's
      // own redline_state only ever carries the latest content, never a real
      // additions/subtractions diff, so this is the one path that renders an
      // actual highlighted redline once a turn has been applied. Only offered
      // for résumé variants (the engine route's typed for a variant_id) and
      // only once we have both an original snapshot (the content the card
      // showed before review opened) and a current one that differs from it.
      const isVariant = (item.type || '').toLowerCase() === 'resume_variant';
      const originalContent = (item.content || '').toString();
      const currentContent = (rl && typeof rl.content === 'string') ? rl.content : '';
      if (isVariant && originalContent && currentContent && currentContent !== originalContent) {
        const compareBtn = document.createElement('button');
        compareBtn.className = 'doclib-card-text-btn doclib-card-action-btn';
        compareBtn.textContent = 'Compare to original';
        compareBtn.title = 'See exactly what changed vs. the original version.';
        compareBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          compareBtn.disabled = true;
          const original = compareBtn.textContent;
          compareBtn.textContent = 'Comparing…';
          try {
            const res = await fetch(`${_APPLICANT_BASE}/redline`, {
              method: 'POST',
              credentials: 'same-origin',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                variant_id: item.id,
                base_source: originalContent,
                new_source: currentContent,
              }),
            });
            if (!res.ok) throw new Error(await _applicantErrText(res));
            const diff = await res.json();
            const renderedHtml2 = diff && (diff.rendered_html || diff.html);
            const additions2 = diff && Array.isArray(diff.additions) ? diff.additions : [];
            const subtractions2 = diff && Array.isArray(diff.subtractions) ? diff.subtractions : [];
            if (renderedHtml2) {
              // Same untrusted-HTML sink as the primary redline above —
              // sanitize before injecting (lens 04 #69).
              redline.innerHTML = markdownModule.sanitizeAllowedHtml(renderedHtml2);
            } else if (additions2.length || subtractions2.length) {
              const add2 = additions2.map(a => `<li style="color:var(--color-success,#4caf50);">+ ${_esc(String(a))}</li>`).join('');
              const sub2 = subtractions2.map(s => `<li style="color:var(--color-danger,#e06c75);">− ${_esc(String(s))}</li>`).join('');
              redline.innerHTML = `<div style="opacity:0.6;margin-bottom:4px;">Changes vs. the original</div><ul style="margin:0;padding-left:16px;list-style:none;">${add2}${sub2}</ul>`;
            } else {
              redline.innerHTML = '<div style="opacity:0.6;">No differences found.</div>';
            }
            // The swapped-in content may now be shorter/longer than before —
            // re-check whether the show-more toggle is still needed (#63).
            if (typeof requestAnimationFrame === 'function') requestAnimationFrame(_syncRedlineToggle);
            else _syncRedlineToggle();
          } catch (err) {
            if (uiModule) uiModule.showError(err.message || String(err));
          } finally {
            compareBtn.disabled = false;
            compareBtn.textContent = original;
          }
        });
        panel.appendChild(compareBtn);
      }

      // Turn history (what was asked + the engine's response), if any.
      const turns = session && Array.isArray(session.turns) ? session.turns : [];
      if (turns.length) {
        const hist = document.createElement('div');
        hist.style.cssText = 'display:flex;flex-direction:column;gap:6px;';
        turns.forEach(t => {
          const row = document.createElement('div');
          row.style.cssText = 'font-size:12px;border-left:2px solid var(--border);padding-left:8px;';
          const ask = _esc(t.instruction || t.kind || '');
          const resp = _esc(t.ai_response || '');
          row.innerHTML = (ask ? `<div><strong>You asked:</strong> ${ask}</div>` : '') +
                          (resp ? `<div style="opacity:0.8;">${resp}</div>` : '');
          hist.appendChild(row);
        });
        panel.appendChild(hist);
      }

      // "Ask for a change" box — drives the engine turn loop. The kind selector
      // lets the user explicitly ADD text, SUBTRACT (remove) text, or just
      // describe a free-text change. The spec stresses the loop must be able to
      // subtract text, so "Remove text" is a first-class choice here.
      const ask = document.createElement('div');
      ask.style.cssText = 'display:flex;gap:6px;align-items:flex-start;flex-wrap:wrap;';
      ask.innerHTML =
        '<select class="memory-search-input doclib-applicant-kind" ' +
          'title="Pick how to change it — give me exact text to add or remove, or describe the change and I’ll work it in." ' +
          'style="flex:0 0 auto;width:auto;min-height:38px;">' +
          '<option value="free_text">Describe a change</option>' +
          '<option value="add">Add text</option>' +
          '<option value="subtract">Remove text</option>' +
        '</select>' +
        '<textarea class="memory-search-input doclib-applicant-instruction" rows="2" ' +
          'placeholder="Ask for a change, e.g. “shorten the summary” or “mention my Python experience”" ' +
          'title="Describe the change in plain language. I’ll revise the document and show the result here." ' +
          'style="flex:1;resize:vertical;min-height:38px;"></textarea>' +
        '<button class="doclib-card-text-btn doclib-applicant-send" title="Ask me to make this change — I’ll show the updated draft here.">Request change</button>';
      panel.appendChild(ask);

      const instruction = ask.querySelector('.doclib-applicant-instruction');
      const kindSel = ask.querySelector('.doclib-applicant-kind');
      const sendBtn = ask.querySelector('.doclib-applicant-send');
      // Keep the prompt aligned with the selected kind so the user knows what to
      // type (the text to add, or the text/phrasing to remove).
      const _kindPlaceholder = {
        free_text: 'Ask for a change, e.g. “shorten the summary” or “mention my Python experience”',
        add: 'Text to add, e.g. “Led a team of 5 engineers.”',
        subtract: 'Text or phrasing to remove, e.g. “the second bullet about internships”',
      };

      // Lens 04 #54: restore any not-yet-sent instruction the user typed
      // before this panel was re-rendered (a turn's response re-render, or a
      // full materials reload that closes and reopens the review), instead of
      // always starting the box blank.
      const _draftKey = String(item.id);
      const _draft = _reviewInstructionDrafts.get(_draftKey);
      if (_draft && _draft.text) {
        instruction.value = _draft.text;
        kindSel.value = _draft.kind || 'free_text';
      }
      instruction.placeholder = _kindPlaceholder[kindSel.value] || _kindPlaceholder.free_text;

      // Persist the draft on every keystroke/kind change so it survives the
      // next re-render; clear it once there is nothing typed.
      const _saveDraft = () => {
        const text = instruction.value || '';
        if (text.trim()) {
          _reviewInstructionDrafts.set(_draftKey, { kind: kindSel.value, text });
        } else {
          _reviewInstructionDrafts.delete(_draftKey);
        }
      };
      instruction.addEventListener('input', _saveDraft);
      kindSel.addEventListener('change', () => {
        instruction.placeholder = _kindPlaceholder[kindSel.value] || _kindPlaceholder.free_text;
        _saveDraft();
      });
      sendBtn.addEventListener('click', async () => {
        const text = (instruction.value || '').trim();
        const kind = kindSel.value || 'free_text';
        if (!text) {
          if (uiModule) {
            uiModule.showError(
              kind === 'add' ? 'Type the text to add first.'
                : kind === 'subtract' ? 'Say what to remove first.'
                : 'Describe the change you want first.'
            );
          }
          return;
        }
        sendBtn.disabled = true;
        sendBtn.textContent = 'Making the change…';
        try {
          const res = await fetch(`${_APPLICANT_BASE}/${encodeURIComponent(item.id)}/turn`, {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ kind, instruction: text }),
          });
          if (!res.ok) throw new Error(await _applicantErrText(res));
          const next = await res.json();
          // The instruction was submitted and applied — clear the draft so a
          // stale request doesn't reappear in the next render.
          _reviewInstructionDrafts.delete(_draftKey);
          if (uiModule) uiModule.showToast('Change applied');
          _renderApplicantReview(item, appId, panel, next, card, results);
        } catch (err) {
          sendBtn.disabled = false;
          sendBtn.textContent = 'Request change';
          if (uiModule) uiModule.showError(err.message || String(err));
        }
      });

      // Approve / Decline — the redline decision row composes the Decision kit's
      // .odec-row action zone; Approve is the binding CTA (.odec-confirm) and Decline
      // the secondary choice (.odec-opt), mirroring appkitDecision.js's own naming.
      const decide = document.createElement('div');
      decide.className = 'odec-row';
      decide.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;';
      const approveBtn = document.createElement('button');
      approveBtn.className = 'doclib-card-text-btn doclib-card-action-btn odec-confirm';
      approveBtn.textContent = 'Approve';
      approveBtn.title = 'Approve this document — I’ll use it for the application.';
      approveBtn.addEventListener('click', async () => {
        approveBtn.disabled = true;
        approveBtn.textContent = 'Approving…';
        try {
          const res = await fetch(`${_APPLICANT_BASE}/${encodeURIComponent(item.id)}/approve`, { method: 'POST', credentials: 'same-origin' });
          if (!res.ok) throw new Error(await _applicantErrText(res));
          _reviewInstructionDrafts.delete(_draftKey);
          if (uiModule) uiModule.showToast('Document approved');
          _reloadApplicantMaterialsPreservingContext(appId, results, item.id);
        } catch (err) {
          approveBtn.disabled = false;
          approveBtn.textContent = 'Approve';
          if (uiModule) uiModule.showError(err.message || String(err));
        }
      });
      const declineBtn = document.createElement('button');
      declineBtn.className = 'doclib-card-text-btn doclib-card-action-btn doclib-card-text-btn-danger odec-opt';
      declineBtn.textContent = 'Decline';
      declineBtn.title = 'Decline this draft — it stays unapproved and won’t be sent.';
      declineBtn.addEventListener('click', async () => {
        declineBtn.disabled = true;
        declineBtn.textContent = 'Declining…';
        try {
          const res = await fetch(`${_APPLICANT_BASE}/${encodeURIComponent(item.id)}/decline`, { method: 'POST', credentials: 'same-origin' });
          if (!res.ok) throw new Error(await _applicantErrText(res));
          _reviewInstructionDrafts.delete(_draftKey);
          if (uiModule) uiModule.showToast('Document declined');
          _reloadApplicantMaterialsPreservingContext(appId, results, item.id);
        } catch (err) {
          declineBtn.disabled = false;
          declineBtn.textContent = 'Decline';
          if (uiModule) uiModule.showError(err.message || String(err));
        }
      });
      decide.appendChild(approveBtn);
      decide.appendChild(declineBtn);
      panel.appendChild(decide);
    }

    // ── Chats tab state ──
    let _chatsSessions = [];
    let _chatsSearch = '';
    let _chatsSort = 'recent';
    let _chatsSelectMode = false;
    const _chatsSelected = new Set();
    let _chatsModelFilter = '';

    function _renderLibChats() {
      const grid = document.getElementById('doclib-chats-grid');
      if (!grid) return;
      grid.innerHTML = '';
      grid.appendChild(spinnerModule.createLoadingRow('Loading…'));
      fetch(API_BASE + '/api/sessions', { credentials: 'same-origin' }).then(r => r.json()).then(data => {
        const raw = Array.isArray(data) ? data : (data.sessions || []);
        _chatsSessions = raw.filter(s => !s.archived);
        _renderChatsGrid();
        _renderChatsChips();
      }).catch(e => { console.error('Failed to load library:', e); grid.innerHTML = '<div class="doclib-empty">Failed to load</div>'; });
    }

    // Tap a chat row to expand inline: fetches the recent messages and
    // renders them as a preview with an "Open chat" button. Tap again to
    // collapse. Mirrors the documents-tab expand pattern.
    async function _toggleChatPreview(card, session) {
      const preview = card.querySelector('.doclib-chat-preview');
      if (!preview) return;
      const isOpen = card.classList.contains('doclib-card-expanded');
      // Collapse any other open preview in this grid first
      const grid = card.closest('.doclib-grid');
      if (grid) {
        grid.querySelectorAll('.doclib-card-expanded').forEach(c => {
          if (c !== card) {
            c.classList.remove('doclib-card-expanded');
            const p = c.querySelector('.doclib-chat-preview');
            if (p) { p.style.display = 'none'; p.innerHTML = ''; }
          }
        });
      }
      if (isOpen) {
        card.classList.remove('doclib-card-expanded');
        preview.style.display = 'none';
        preview.innerHTML = '';
        return;
      }
      card.classList.add('doclib-card-expanded');
      preview.style.display = 'block';
      preview.innerHTML = '<div style="opacity:0.4;font-size:11px;padding:8px 4px;">Loading…</div>';
      try {
        const res = await fetch(`${API_BASE}/api/history/${session.id}`, { credentials: 'same-origin' });
        if (!res.ok) throw new Error('Failed');
        const data = await res.json();
        const history = Array.isArray(data) ? data : (data.history || []);
        const recent = history.filter(m => m.role === 'user' || m.role === 'assistant').slice(-5);
        const sessionModel = (session.model || '').split('/').pop();
        const msgsHtml = recent.length
          ? recent.map(m => {
              const isUser = m.role === 'user';
              const raw = m.content || '';
              const truncated = raw.length > 600 ? raw.slice(0, 600) + '…' : raw;
              // Strip thinking blocks (internal model state) and render with
              // the same markdown pipeline the chat uses.
              const cleaned = truncated
                .replace(/<think>[\s\S]*?<\/think>/g, '')
                .replace(/<think>[\s\S]*$/, '')
                .trim();
              let body;
              try {
                body = markdownModule.mdToHtml(cleaned);
              } catch { body = _esc(cleaned); }
              // Per-message model can override the session default (e.g.
              // when comparing models in the same chat).
              const msgModel = (m.metadata && (m.metadata.model || m.metadata.model_name)) || '';
              const modelTag = !isUser && (msgModel || sessionModel)
                ? `<span class="doclib-chat-msg-model">${_esc(msgModel || sessionModel)}</span>`
                : '';
              return `<div class="doclib-chat-bubble-row ${isUser ? 'user' : 'assistant'}">
                <div class="doclib-chat-bubble">
                  ${modelTag}
                  <div class="doclib-chat-bubble-body">${body}</div>
                </div>
              </div>`;
            }).join('')
          : '<div style="opacity:0.4;font-size:11px;padding:6px 4px;">No messages yet</div>';
        const isArchive = !!session.archived;
        // Archived chats get a Restore button (unarchive); active chats get the
        // Archive button. Matches the research + document archive previews.
        const archiveHtml = isArchive
          ? '<button class="doclib-chat-restore-btn">' +
              '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 14 4 9 9 4"/><path d="M4 9h11a5 5 0 0 1 5 5v0a5 5 0 0 1-5 5H9"/></svg>' +
              'Restore' +
            '</button>'
          : '<button class="doclib-chat-archive-btn">' +
              '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/><line x1="10" y1="12" x2="14" y2="12"/></svg>' +
              'Archive' +
            '</button>';
        // Copy sits next to Archive on the left side of the action row.
        // Uses the same border-only secondary-action style — distinct from
        // the danger Delete (red) and the primary Open (right-aligned).
        // Copy is hidden in the Archive (keep the footer to Delete + Restore +
        // Open there). It still shows for active chats.
        const copyHtml = isArchive ? '' : '<button class="doclib-chat-copy-btn">' +
              '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>' +
              'Copy' +
            '</button>';
        const deleteHtml = '<button class="doclib-chat-delete-btn">' +
              '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>' +
              'Delete' +
            '</button>';
        preview.innerHTML =
          '<div class="doclib-chat-preview-messages">' + msgsHtml + '</div>' +
          '<div class="doclib-chat-preview-actions">' +
            deleteHtml +
            archiveHtml +
            copyHtml +
            '<button class="doclib-chat-open-btn">' +
              '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 5l7 7-7 7"/></svg>' +
              'Open' +
            '</button>' +
          '</div>';
        const openBtn = preview.querySelector('.doclib-chat-open-btn');
        if (openBtn) openBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          if (window.sessionModule) window.sessionModule.selectSession(session.id);
          closeLibrary();
          // Also collapse the wide sidebar so the picked chat sits
          // fullscreen — same gesture as picking a session in the
          // sidebar itself on mobile. Skip on desktop where the user
          // expects the sidebar to stay where they left it.
          if (window.innerWidth <= 768) {
            const sb = document.getElementById('sidebar');
            if (sb) {
              sb.classList.add('hidden');
              try { window.syncRailSide && window.syncRailSide(); } catch (_) {}
            }
          }
        });
        const archiveBtn = preview.querySelector('.doclib-chat-archive-btn');
        if (archiveBtn) archiveBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          await fetch(API_BASE + '/api/session/' + session.id + '/archive', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
          });
          _renderLibChats();
        });
        const restoreBtn = preview.querySelector('.doclib-chat-restore-btn');
        if (restoreBtn) restoreBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          await fetch(API_BASE + '/api/session/' + session.id + '/unarchive', { method: 'POST' });
          _renderLibArchive();
        });
        const copyBtn = preview.querySelector('.doclib-chat-copy-btn');
        if (copyBtn) copyBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          _copyChatById(session.id);
        });
        const deleteBtn = preview.querySelector('.doclib-chat-delete-btn');
        if (deleteBtn) deleteBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          if (!await window.styledConfirm('Delete this chat?', { confirmText: 'Delete', danger: true })) return;
          await fetch(API_BASE + '/api/session/' + session.id, { method: 'DELETE' });
          card.style.maxHeight = `${Math.max(card.getBoundingClientRect().height, card.scrollHeight)}px`;
          card.classList.add('memory-tidy-removing');
          await new Promise(r => setTimeout(r, 520));
          if (isArchive) _renderLibArchive(); else _renderLibChats();
        });
      } catch (e) {
        preview.innerHTML = '<div style="opacity:0.5;font-size:11px;padding:6px 4px;color:var(--color-error);">Failed to load preview</div>';
      }
    }

    function _renderChatsGrid() {
      const grid = document.getElementById('doclib-chats-grid');
      if (!grid) return;
      const _csb = document.getElementById('doclib-chats-select-btn');
      if (_csb) { _csb.classList.toggle('active', _chatsSelectMode); _csb.textContent = _chatsSelectMode ? 'Cancel' : 'Select'; }
      let filtered = _chatsSessions.slice();
      if (_chatsSearch) {
        const q = _chatsSearch.toLowerCase();
        filtered = filtered.filter(s => (s.name || '').toLowerCase().includes(q) || (s.model || '').toLowerCase().includes(q));
      }
      if (_chatsModelFilter) filtered = filtered.filter(s => s.folder === _chatsModelFilter);
      if (_chatsSort === 'oldest') filtered.sort((a, b) => (a.updated_at || '') > (b.updated_at || '') ? 1 : -1);
      else if (_chatsSort === 'most-messages') filtered.sort((a, b) => (b.message_count || 0) - (a.message_count || 0));
      else if (_chatsSort === 'alpha') filtered.sort((a, b) => (a.name || '').localeCompare(b.name || ''));
      else filtered.sort((a, b) => (b.updated_at || '') > (a.updated_at || '') ? 1 : -1);

      const stats = document.getElementById('doclib-chats-stats');
      if (stats) stats.textContent = filtered.length + ' chat' + (filtered.length !== 1 ? 's' : '');

      if (!filtered.length) {
        // Sad-mouth smiley (downturn curve) for "nothing here yet".
        const _sadIco = '<span style="vertical-align:-3px;margin-left:6px;">' + uiModule.emptyStateIcon('sad') + '</span>';
        grid.innerHTML = '<div class="doclib-empty">No chats' + _sadIco + '</div>';
        _appendInlineLoadMore(grid, 0, _chatsVisibleLimit, () => {});
        return;
      }
      const total = filtered.length;
      const visible = filtered.slice(0, _chatsVisibleLimit);
      grid.innerHTML = '';
      _maybeCascadeGrid(grid, 'chats');
      for (const s of visible) {
        const card = document.createElement('div');
        card.className = 'memory-item doclib-chat-row ow-list-row';
        card.style.cursor = 'pointer';
        card.dataset.sid = s.id;
        const model = (s.model || '').split('/').pop();
        const cbHtml = _chatsSelectMode ? '<input type="checkbox" class="memory-select-cb"' + (_chatsSelected.has(s.id) ? ' checked' : '') + '>' : '';
        const chatIconSvg = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px;opacity:0.4;flex-shrink:0;"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';
        const chevronSvg = '<span class="doclib-card-chevron"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg></span>';
        // Msg count badge inside the title, dimmer than the name so it
        // reads as metadata at a glance. Hidden when count is 0 so
        // brand-new "New Chat" rows don't show "\u00b7 0 msgs".
        const _chatMsgs = s.message_count || 0;
        const msgCountHtml = _chatMsgs > 0
          ? '<span style="opacity:0.45;font-weight:normal;font-size:0.9em;margin-left:6px;">\u00b7 ' + _chatMsgs + ' msg' + (_chatMsgs === 1 ? '' : 's') + '</span>'
          : '';
        card.innerHTML =
          '<div class="doclib-chat-header" style="display:flex;align-items:center;width:100%;gap:6px;">' +
            cbHtml +
            '<div style="flex:1;min-width:0;">' +
              '<div class="memory-item-title">' + chatIconSvg + _esc(s.name || 'Untitled') + msgCountHtml + '</div>' +
              '<div class="memory-item-meta" style="font-size:10px;opacity:0.4;margin-top:2px;">' + [model, _relTime(s.updated_at)].filter(Boolean).join(' \u00b7 ') + '</div>' +
            '</div>' +
            chevronSvg +
            '<div class="memory-item-actions"><button class="memory-item-btn _chat-menu" title="Actions"><svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="12" cy="19" r="2"/></svg></button></div>' +
          '</div>' +
          '<div class="doclib-chat-preview" style="display:none;"></div>';
        const cb = card.querySelector('.memory-select-cb');
        if (cb) { cb.addEventListener('click', e => e.stopPropagation()); cb.addEventListener('change', () => { if (cb.checked) _chatsSelected.add(s.id); else _chatsSelected.delete(s.id); _updateChatsCount(); }); }
        card.querySelector('._chat-menu').addEventListener('click', (e) => { e.stopPropagation(); _showLibDropdown(e.currentTarget, [
          { label: 'Open', action: () => { if (window.sessionModule) window.sessionModule.selectSession(s.id); } },
          { label: 'Copy', action: () => _copyChatById(s.id) },
          { label: 'Archive', action: async () => { await fetch(API_BASE + '/api/session/' + s.id + '/archive', { method: 'POST', headers: {'Content-Type':'application/json'} }); _renderLibChats(); } },
          { label: 'Delete', action: async () => {
            await fetch(API_BASE + '/api/session/' + s.id, { method: 'DELETE' });
            card.style.maxHeight = `${Math.max(card.getBoundingClientRect().height, card.scrollHeight)}px`;
            card.classList.add('memory-tidy-removing');
            await new Promise(r => setTimeout(r, 520));
            _renderLibChats();
          }, danger: true },
        ], { onSelect: () => {
          _chatsSelectMode = true;
          _chatsSelected.add(s.id);
          document.getElementById('doclib-chats-bulk')?.classList.remove('hidden');
          _renderChatsGrid();
        } }); });
        card.addEventListener('click', (e) => {
          if (card._suppressNextClick) { card._suppressNextClick = false; return; }
          if (_chatsSelectMode) { const c = card.querySelector('.memory-select-cb'); if (c) { c.checked = !c.checked; if (c.checked) _chatsSelected.add(s.id); else _chatsSelected.delete(s.id); _updateChatsCount(); } return; }
          if (e.target.closest('._chat-menu') || e.target.closest('.memory-select-cb') || e.target.closest('.doclib-chat-open-btn')) return;
          _toggleChatPreview(card, s);
        });
        _attachLongPressMenu(card, '._chat-menu');
        grid.appendChild(card);
      }
      _appendInlineLoadMore(grid, total, _chatsVisibleLimit, () => {
        _chatsVisibleLimit += _LIB_PAGE_SIZE;
        _renderChatsGrid();
      });
    }

    function _renderChatsChips() {
      const el = document.getElementById('doclib-chats-chips');
      if (!el) return;
      const counts = {};
      _chatsSessions.forEach(s => { const f = s.folder; if (f) counts[f] = (counts[f] || 0) + 1; });
      const folders = Object.keys(counts).sort();
      if (folders.length < 1) { el.innerHTML = ''; return; }
      el.innerHTML = '';
      const mk = (label, val, count) => { const c = document.createElement('button'); c.className = 'memory-cat-chip' + (_chatsModelFilter === val ? ' active' : ''); c.textContent = label + ' (' + count + ')'; c.addEventListener('click', () => { _chatsModelFilter = _chatsModelFilter === val ? '' : val; _renderChatsGrid(); _renderChatsChips(); }); el.appendChild(c); };
      mk('all', '', _chatsSessions.length);
      folders.forEach(f => mk(f, f, counts[f]));
    }

    function _updateChatsCount() { const el = document.getElementById('doclib-chats-selected-count'); if (el) el.textContent = _chatsSelected.size + ' Selected'; }

    // Chats event listeners
    document.getElementById('doclib-chats-sort').addEventListener('change', (e) => { _chatsSort = e.target.value; _renderChatsGrid(); });
    document.getElementById('doclib-chats-search').addEventListener('input', (e) => { _chatsSearch = e.target.value.trim(); _renderChatsGrid(); });
    document.getElementById('doclib-chats-select-btn').addEventListener('click', () => { _chatsSelectMode = !_chatsSelectMode; _chatsSelected.clear(); document.getElementById('doclib-chats-bulk').classList.toggle('hidden', !_chatsSelectMode); _renderChatsGrid(); });
    document.getElementById('doclib-chats-bulk-cancel')?.addEventListener('click', () => {
      _chatsSelectMode = false; _chatsSelected.clear();
      document.getElementById('doclib-chats-bulk').classList.add('hidden');
      _renderChatsGrid();
    });
    function _chatsToggleAll() {
      const allCb = document.getElementById('doclib-chats-select-all');
      const newState = _chatsSelected.size < _chatsSessions.length;
      if (allCb) allCb.checked = newState;
      document.querySelectorAll('#doclib-chats-grid .memory-select-cb').forEach(cb => { cb.checked = newState; });
      _chatsSessions.forEach(s => { if (newState) _chatsSelected.add(s.id); else _chatsSelected.delete(s.id); });
      _updateChatsCount();
    }
    document.getElementById('doclib-chats-select-all').addEventListener('change', _chatsToggleAll);
    document.getElementById('doclib-chats-bulk').addEventListener('click', (e) => {
      if (e.target.closest('button') || e.target.closest('input')) return;
      _chatsToggleAll();
    });
    document.getElementById('doclib-chats-bulk-archive').addEventListener('click', async () => {
      const count = _chatsSelected.size;
      if (!count) return;
      const grid = document.getElementById('doclib-chats-grid');
      if (grid) {
        grid.querySelectorAll('.doclib-card').forEach(card => {
          const sid = card.dataset.sid || card.dataset.sessionId;
          if (sid && _chatsSelected.has(sid)) {
            card.style.transition = 'opacity 0.25s, transform 0.25s';
            card.style.opacity = '0';
            card.style.transform = 'scale(0.95)';
          }
        });
      }
      await new Promise(r => setTimeout(r, 250));
      const ids = [..._chatsSelected];
      const results = await Promise.all(
        ids.map(sid => fetch(API_BASE + '/api/session/' + sid + '/archive', { method: 'POST', headers: {'Content-Type':'application/json'} })
          .then(r => ({ sid, ok: r.ok }))
          .catch(() => ({ sid, ok: false }))
        )
      );
      const failed = results.filter(r => !r.ok).map(r => r.sid);
      if (failed.length && grid) {
        grid.querySelectorAll('.doclib-card').forEach(card => {
          const sid = card.dataset.sid || card.dataset.sessionId;
          if (sid && failed.includes(sid)) {
            card.style.opacity = '';
            card.style.transform = '';
          }
        });
        if (window.uiModule) window.uiModule.showError(`Failed to archive ${failed.length} of ${ids.length} chat${ids.length > 1 ? 's' : ''}`);
      }
      _chatsSelected.clear();
      _chatsSelectMode = false;
      document.getElementById('doclib-chats-bulk').classList.add('hidden');
      _renderLibChats();
    });
    document.getElementById('doclib-chats-bulk-delete').addEventListener('click', async () => {
      const count = _chatsSelected.size;
      if (!count) return;
      if (!await window.styledConfirm(`Delete ${count} chat${count > 1 ? 's' : ''}? This cannot be undone.`, { confirmText: 'Delete', danger: true })) return;
      // Fade out selected cards
      const grid = document.getElementById('doclib-chats-grid');
      if (grid) {
        grid.querySelectorAll('.doclib-card').forEach(card => {
          const sid = card.dataset.sid || card.dataset.sessionId;
          if (sid && _chatsSelected.has(sid)) {
            card.style.transition = 'opacity 0.25s, transform 0.25s';
            card.style.opacity = '0';
            card.style.transform = 'scale(0.95)';
          }
        });
      }
      // Delete after animation. v2 review HIGH-8: inspect each response
      // so cards that the server rejected get restored (instead of
      // staying faded out forever) and the user sees an aggregate
      // error toast.
      await new Promise(r => setTimeout(r, 250));
      const ids = [..._chatsSelected];
      const results = await Promise.all(
        ids.map(sid => fetch(API_BASE + '/api/session/' + sid, { method: 'DELETE' })
          .then(r => ({ sid, ok: r.ok }))
          .catch(() => ({ sid, ok: false }))
        )
      );
      const failed = results.filter(r => !r.ok).map(r => r.sid);
      if (failed.length && grid) {
        // Restore faded cards for the rows the server refused.
        grid.querySelectorAll('.doclib-card').forEach(card => {
          const sid = card.dataset.sid || card.dataset.sessionId;
          if (sid && failed.includes(sid)) {
            card.style.opacity = '';
            card.style.transform = '';
          }
        });
        if (window.uiModule) window.uiModule.showError(`Failed to delete ${failed.length} of ${ids.length} chat${ids.length > 1 ? 's' : ''}`);
      }
      _chatsSelected.clear();
      _chatsSelectMode = false;
      document.getElementById('doclib-chats-bulk').classList.add('hidden');
      _renderLibChats();
    });

    // Tidy button — AI cleanup + organize into folders
    document.getElementById('doclib-chats-tidy-btn').addEventListener('click', async () => {
      const tidyBtn = document.getElementById('doclib-chats-tidy-btn');
      const origHTML = tidyBtn.innerHTML;
      tidyBtn.disabled = true;
      tidyBtn.classList.add('spinning');
      tidyBtn.textContent = '';
      // Silent whirlpool, nudged up to line up with the surrounding button
      // text in the Chats header. The previous version checked
      // `window.spinnerModule` (never bound) and always fell through to a
      // plain "Tidying..." label.
      const sp = spinnerModule.create('', 'clean', 'whirlpool');
      const el = sp.createElement();
      el.style.position = 'relative';
      el.style.top = '1px';
      tidyBtn.appendChild(el);
      sp.start();
      try {
        const res = await fetch(API_BASE + '/api/sessions/auto-sort', { method: 'POST', credentials: 'same-origin' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Tidy failed');
        if (data.status === 'ok') {
          if (window.uiModule) window.uiModule.showToast('Sorted ' + data.updated + ' sessions into ' + data.folders.length + ' folders');
          if (window.sessionModule) await window.sessionModule.loadSessions();
          _renderLibChats();
        } else {
          if (window.uiModule) window.uiModule.showToast(data.reason || 'Nothing to tidy');
        }
      } catch (e) {
        if (window.uiModule) window.uiModule.showError('Tidy: ' + e.message);
      } finally {
        tidyBtn.disabled = false;
        tidyBtn.classList.remove('spinning');
        tidyBtn.innerHTML = origHTML;
      }
    });

    // ── Archive tab state ──
    let _arcSessions = [];
    let _arcDocs = [];        // archived documents
    let _arcResearch = [];    // archived research reports
    let _arcSearch = '';
    let _arcSort = 'recent';
    let _arcSelectMode = false;
    const _arcSelected = new Set();
    let _arcModelFilter = '';
    let _arcTypeFilter = '';   // '', 'chats', 'documents', 'research'

    function _renderLibArchive() {
      const grid = document.getElementById('doclib-arc-grid');
      if (!grid) return;
      grid.innerHTML = '';
      grid.appendChild(spinnerModule.createLoadingRow('Loading…'));
      // Archive tab is the home for ALL archived items — chats, documents, and
      // research — each rendered with its own icon. Load the three in parallel.
      Promise.all([
        fetch(API_BASE + '/api/sessions/archived?limit=100&sort=recent', { credentials: 'same-origin' }).then(r => r.json()).catch(() => ({})),
        fetch(API_BASE + '/api/documents/library?archived=true&limit=50', { credentials: 'same-origin' }).then(r => r.json()).catch(() => ({})),
        fetch('/api/research/library?archived=true', { credentials: 'same-origin' }).then(r => r.json()).catch(() => ({})),
      ]).then(([s, d, r]) => {
        // These are all archived by definition — flag them so the expanded
        // chat preview hides its (redundant) "Archive" button.
        _arcSessions = (s.sessions || []).map(x => ({ ...x, archived: true }));
        _arcDocs = d.documents || [];
        _arcResearch = (r.research || []).map(x => ({ ...x, archived: true }));
        _renderArcGrid();
        _renderArcChips();
      }).catch(e => { console.error('Failed to load library:', e); grid.innerHTML = '<div class="doclib-empty">Failed to load</div>'; });
    }

    // Inline expand/collapse for an archived DOCUMENT card (chat-style). Loads
    // the doc content into the card's .doclib-chat-preview. Lag-safe: caps the
    // shown text and skips highlighting (archived previews are read-only peeks).
    async function _toggleArcDocPreview(card, d) {
      const preview = card.querySelector('.doclib-chat-preview');
      if (!preview) return;
      const grid = card.closest('.doclib-grid');
      if (grid) {
        grid.querySelectorAll('.doclib-card-expanded').forEach(c => {
          if (c !== card) {
            c.classList.remove('doclib-card-expanded');
            const p = c.querySelector('.doclib-chat-preview');
            if (p) { p.style.display = 'none'; p.innerHTML = ''; }
          }
        });
      }
      if (card.classList.contains('doclib-card-expanded')) {
        card.classList.remove('doclib-card-expanded');
        preview.style.display = 'none'; preview.innerHTML = '';
        return;
      }
      card.classList.add('doclib-card-expanded');
      preview.style.display = 'block';
      preview.innerHTML = '<div style="opacity:0.4;font-size:11px;padding:8px 4px;">Loading…</div>';
      try {
        const res = await fetch(`${API_BASE}/api/document/${d.id}`, { credentials: 'same-origin' });
        if (!res.ok) throw new Error('failed');
        const full = await res.json();
        const content = (full.current_content || '').slice(0, 20000);
        const pre = document.createElement('pre');
        pre.style.cssText = 'white-space:pre-wrap;word-break:break-word;font-size:11px;margin:6px 4px;max-height:50vh;overflow:auto;';
        pre.textContent = content || '(empty document)';
        preview.innerHTML = '';
        preview.appendChild(pre);

        // Footer — uses the same visible .doclib-chat-preview-actions style as
        // the chat/research previews (the .doclib-card-expanded-actions class is
        // display:none unless inside a .doclib-card, which these archive rows
        // are not). Delete + Restore, matching the others.
        const actions = document.createElement('div');
        actions.className = 'doclib-chat-preview-actions';
        actions.innerHTML =
          '<button class="doclib-chat-delete-btn"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>Delete</button>' +
          '<button class="doclib-chat-restore-btn"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 14 4 9 9 4"/><path d="M4 9h11a5 5 0 0 1 5 5v0a5 5 0 0 1-5 5H9"/></svg>Restore</button>' +
          '<button class="doclib-chat-open-btn"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 5l7 7-7 7"/></svg>Open</button>';
        actions.querySelector('.doclib-chat-delete-btn').addEventListener('click', async (ev) => {
          ev.stopPropagation();
          if (!await window.styledConfirm('Delete this document?', { confirmText: 'Delete', danger: true })) return;
          await fetch(`${API_BASE}/api/document/${d.id}`, { method: 'DELETE', credentials: 'same-origin' });
          _renderLibArchive();
        });
        actions.querySelector('.doclib-chat-restore-btn').addEventListener('click', async (ev) => {
          ev.stopPropagation();
          await fetch(`${API_BASE}/api/document/${d.id}/archive?archived=false`, { method: 'POST', credentials: 'same-origin' });
          _renderLibArchive();
        });
        // Open = clone the doc into the active session and surface it in the editor.
        actions.querySelector('.doclib-chat-open-btn').addEventListener('click', (ev) => {
          ev.stopPropagation();
          libraryImportDocument(d);
        });
        preview.appendChild(actions);
      } catch {
        preview.innerHTML = '<div style="opacity:0.4;font-size:11px;padding:8px 4px;">Failed to load preview</div>';
      }
    }

    function _renderArcGrid() {
      const grid = document.getElementById('doclib-arc-grid');
      if (!grid) return;
      const _asb = document.getElementById('doclib-arc-select-btn');
      if (_asb) { _asb.classList.toggle('active', _arcSelectMode); _asb.textContent = _arcSelectMode ? 'Cancel' : 'Select'; }
      let filtered = _arcSessions.slice();
      if (_arcSearch) {
        const q = _arcSearch.toLowerCase();
        filtered = filtered.filter(s => (s.name || '').toLowerCase().includes(q) || (s.model || '').toLowerCase().includes(q));
      }
      if (_arcModelFilter) filtered = filtered.filter(s => (s.model || '').split('/').pop() === _arcModelFilter);
      if (_arcSort === 'oldest') filtered.sort((a, b) => (a.updated_at || '') > (b.updated_at || '') ? 1 : -1);
      else if (_arcSort === 'most-messages') filtered.sort((a, b) => (b.message_count || 0) - (a.message_count || 0));
      else if (_arcSort === 'alpha') filtered.sort((a, b) => (a.name || '').localeCompare(b.name || ''));
      else filtered.sort((a, b) => (b.updated_at || '') > (a.updated_at || '') ? 1 : -1);

      // Archived documents + research also live here — filter them by the same search.
      const _aq = (_arcSearch || '').toLowerCase();
      let filtDocs = _aq ? _arcDocs.filter(d => (d.title || '').toLowerCase().includes(_aq)) : _arcDocs;
      let filtResearch = _aq ? _arcResearch.filter(r => (r.query || '').toLowerCase().includes(_aq)) : _arcResearch;

      // Type filter chips (Chats / Documents / Research) zero out the others.
      const _showChats = !_arcTypeFilter || _arcTypeFilter === 'chats';
      const _showDocs = !_arcTypeFilter || _arcTypeFilter === 'documents';
      const _showResearch = !_arcTypeFilter || _arcTypeFilter === 'research';
      if (!_showChats) filtered = [];
      if (!_showDocs) filtDocs = [];
      if (!_showResearch) filtResearch = [];

      const stats = document.getElementById('doclib-arc-stats');
      if (stats) stats.textContent = (filtered.length + filtDocs.length + filtResearch.length) + ' archived';

      if (!filtered.length && !filtDocs.length && !filtResearch.length) {
        // Neutral / no-smile face for "nothing archived here".
        const _neutralIco = '<span style="vertical-align:-3px;margin-left:6px;">' + uiModule.emptyStateIcon('neutral') + '</span>';
        grid.innerHTML = '<div class="doclib-empty">No archived items' + _neutralIco + '</div>';
        _appendInlineLoadMore(grid, 0, _arcVisibleLimit, () => {});
        return;
      }
      const total = filtered.length;
      const visible = filtered.slice(0, _arcVisibleLimit);
      grid.innerHTML = '';
      _maybeCascadeGrid(grid, 'archive');
      for (const s of visible) {
        const card = document.createElement('div');
        card.className = 'memory-item doclib-chat-row ow-list-row';
        card.style.cursor = 'pointer';
        card.dataset.sid = s.id;
        card.dataset.arckey = 'chats:' + s.id;
        const model = (s.model || '').split('/').pop();
        const cbHtml = _arcSelectMode ? '<input type="checkbox" class="memory-select-cb" data-arckey="chats:' + s.id + '"' + (_arcSelected.has('chats:' + s.id) ? ' checked' : '') + '>' : '';
        const arcIconSvg = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px;opacity:0.5;flex-shrink:0;"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';
        card.innerHTML =
          '<div class="doclib-chat-header" style="display:flex;align-items:center;width:100%;gap:6px;">' +
            cbHtml +
            '<div style="flex:1;min-width:0;">' +
              '<div class="memory-item-title">' + arcIconSvg + _esc(s.name || 'Untitled') + '</div>' +
              '<div class="memory-item-meta" style="font-size:10px;opacity:0.4;margin-top:2px;">' + [model, _relTime(s.updated_at)].filter(Boolean).join(' \u00b7 ') + '</div>' +
            '</div>' +
            '<div class="memory-item-actions"><button class="memory-item-btn _arc-menu" title="Actions"><svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="12" cy="19" r="2"/></svg></button></div>' +
          '</div>' +
          '<div class="doclib-chat-preview" style="display:none;"></div>';
        const cb = card.querySelector('.memory-select-cb');
        if (cb) { cb.addEventListener('click', e => e.stopPropagation()); cb.addEventListener('change', () => { if (cb.checked) _arcSelected.add('chats:' + s.id); else _arcSelected.delete('chats:' + s.id); _updateArcCount(); }); }
        card.querySelector('._arc-menu').addEventListener('click', (e) => { e.stopPropagation(); _showLibDropdown(e.currentTarget, [
          { label: 'Open', action: () => { if (window.sessionModule) window.sessionModule.selectSession(s.id); } },
          { label: 'Copy', action: () => _copyChatById(s.id) },
          { label: 'Restore', action: async () => { await fetch(API_BASE + '/api/session/' + s.id + '/unarchive', { method: 'POST' }); _renderLibArchive(); } },
          { label: 'Delete', action: async () => { await fetch(API_BASE + '/api/session/' + s.id, { method: 'DELETE' }); _renderLibArchive(); }, danger: true },
        ], { onSelect: () => {
          _arcSelectMode = true;
          _arcSelected.add('chats:' + s.id);
          document.getElementById('doclib-arc-bulk')?.classList.remove('hidden');
          _renderArcGrid();
        } }); });
        card.addEventListener('click', (e) => {
          if (card._suppressNextClick) { card._suppressNextClick = false; return; }
          if (_arcSelectMode) { const c = card.querySelector('.memory-select-cb'); if (c) { c.checked = !c.checked; if (c.checked) _arcSelected.add('chats:' + s.id); else _arcSelected.delete('chats:' + s.id); _updateArcCount(); } return; }
          if (e.target.closest('._arc-menu') || e.target.closest('.memory-select-cb') || e.target.closest('.doclib-chat-open-btn')) return;
          _toggleChatPreview(card, s);
        });
        _attachLongPressMenu(card, '._arc-menu');
        grid.appendChild(card);
      }
      // Archived DOCUMENTS — document icon, Restore / Delete.
      const _arcDocIco = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px;opacity:0.5;flex-shrink:0;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>';
      for (const d of filtDocs) {
        const card = document.createElement('div');
        card.className = 'memory-item doclib-chat-row ow-list-row';
        card.style.cursor = 'pointer';
        card.dataset.arckey = 'documents:' + d.id;
        const _dcb = _arcSelectMode ? '<input type="checkbox" class="memory-select-cb" data-arckey="documents:' + d.id + '"' + (_arcSelected.has('documents:' + d.id) ? ' checked' : '') + '>' : '';
        card.innerHTML =
          '<div class="doclib-chat-header" style="display:flex;align-items:center;width:100%;gap:6px;">' +
            _dcb +
            '<div style="flex:1;min-width:0;">' +
              '<div class="memory-item-title">' + _arcDocIco + _esc(d.title || 'Untitled') + '</div>' +
              '<div class="memory-item-meta" style="font-size:10px;opacity:0.4;margin-top:2px;">' + ['Document', (d.language || 'text'), _relTime(d.updated_at)].filter(Boolean).join(' · ') + '</div>' +
            '</div>' +
            '<div class="memory-item-actions"><button class="memory-item-btn _arc-doc-menu" title="Actions"><svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="12" cy="19" r="2"/></svg></button></div>' +
          '</div>' +
          '<div class="doclib-chat-preview" style="display:none;"></div>';
        const _dcbEl = card.querySelector('.memory-select-cb');
        if (_dcbEl) { _dcbEl.addEventListener('click', e => e.stopPropagation()); _dcbEl.addEventListener('change', () => { if (_dcbEl.checked) _arcSelected.add('documents:' + d.id); else _arcSelected.delete('documents:' + d.id); _updateArcCount(); }); }
        card.addEventListener('click', (e) => {
          if (e.target.closest('._arc-doc-menu') || e.target.closest('.memory-select-cb')) return;
          if (_arcSelectMode) { const c = card.querySelector('.memory-select-cb'); if (c) { c.checked = !c.checked; if (c.checked) _arcSelected.add('documents:' + d.id); else _arcSelected.delete('documents:' + d.id); _updateArcCount(); } return; }
          _toggleArcDocPreview(card, d);
        });
        card.querySelector('._arc-doc-menu').addEventListener('click', (e) => { e.stopPropagation(); _showLibDropdown(e.currentTarget, [
          { label: 'Restore', action: async () => { await fetch(API_BASE + '/api/document/' + d.id + '/archive?archived=false', { method: 'POST', credentials: 'same-origin' }); _renderLibArchive(); } },
          { label: 'Delete', danger: true, action: async () => { if (!await window.styledConfirm('Delete this document?', { confirmText: 'Delete', danger: true })) return; await fetch(API_BASE + '/api/document/' + d.id, { method: 'DELETE', credentials: 'same-origin' }); _renderLibArchive(); } },
        ], { onSelect: () => {
          _arcSelectMode = true;
          _arcSelected.add('documents:' + d.id);
          document.getElementById('doclib-arc-bulk')?.classList.remove('hidden');
          _renderArcGrid();
        } }); });
        _attachLongPressMenu(card, '._arc-doc-menu');
        grid.appendChild(card);
      }
      // Archived RESEARCH — magnifier icon, Open / Restore / Delete.
      const _arcResIco = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px;opacity:0.5;flex-shrink:0;"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg>';
      for (const r of filtResearch) {
        const card = document.createElement('div');
        card.className = 'memory-item doclib-chat-row ow-list-row';
        card.style.cursor = 'pointer';
        card.dataset.arckey = 'research:' + r.id;
        const _rcb = _arcSelectMode ? '<input type="checkbox" class="memory-select-cb" data-arckey="research:' + r.id + '"' + (_arcSelected.has('research:' + r.id) ? ' checked' : '') + '>' : '';
        card.innerHTML =
          '<div class="doclib-chat-header" style="display:flex;align-items:center;width:100%;gap:6px;">' +
            _rcb +
            '<div style="flex:1;min-width:0;">' +
              '<div class="memory-item-title">' + _arcResIco + _esc(r.query || 'Research') + '</div>' +
              '<div class="memory-item-meta" style="font-size:10px;opacity:0.4;margin-top:2px;">' + ['Research', (r.source_count ? r.source_count + ' sources' : ''), _relTime(r.completed_at ? new Date(r.completed_at * 1000).toISOString() : '')].filter(Boolean).join(' · ') + '</div>' +
            '</div>' +
            '<div class="memory-item-actions"><button class="memory-item-btn _arc-res-menu" title="Actions"><svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="12" cy="19" r="2"/></svg></button></div>' +
          '</div>' +
          '<div class="doclib-chat-preview" style="display:none;"></div>';
        const _rcbEl = card.querySelector('.memory-select-cb');
        if (_rcbEl) { _rcbEl.addEventListener('click', e => e.stopPropagation()); _rcbEl.addEventListener('change', () => { if (_rcbEl.checked) _arcSelected.add('research:' + r.id); else _arcSelected.delete('research:' + r.id); _updateArcCount(); }); }
        card.addEventListener('click', (e) => {
          if (e.target.closest('._arc-res-menu') || e.target.closest('.memory-select-cb')) return;
          if (_arcSelectMode) { const c = card.querySelector('.memory-select-cb'); if (c) { c.checked = !c.checked; if (c.checked) _arcSelected.add('research:' + r.id); else _arcSelected.delete('research:' + r.id); _updateArcCount(); } return; }
          _toggleResearchPreview(card, r);
        });
        card.querySelector('._arc-res-menu').addEventListener('click', (e) => { e.stopPropagation(); _showLibDropdown(e.currentTarget, [
          { label: 'Open', action: () => { const a = document.createElement('a'); a.href = '/api/research/report/' + r.id; a.target = '_blank'; a.rel = 'noopener'; document.body.appendChild(a); a.click(); a.remove(); } },
          { label: 'Restore', action: async () => { await fetch('/api/research/' + r.id + '/archive?archived=false', { method: 'POST', credentials: 'same-origin' }); _renderLibArchive(); } },
          { label: 'Delete', danger: true, action: async () => { if (!await window.styledConfirm('Delete this research?', { confirmText: 'Delete', danger: true })) return; await fetch('/api/research/' + r.id, { method: 'DELETE', credentials: 'same-origin' }); _renderLibArchive(); } },
        ], { onSelect: () => {
          _arcSelectMode = true;
          _arcSelected.add('research:' + r.id);
          document.getElementById('doclib-arc-bulk')?.classList.remove('hidden');
          _renderArcGrid();
        } }); });
        _attachLongPressMenu(card, '._arc-res-menu');
        grid.appendChild(card);
      }
      _appendInlineLoadMore(grid, total, _arcVisibleLimit, () => {
        _arcVisibleLimit += _LIB_PAGE_SIZE;
        _renderArcGrid();
      });
    }

    function _renderArcChips() {
      const el = document.getElementById('doclib-arc-chips');
      if (!el) return;
      // Type filters: All / Chats / Documents / Research (only the ones present).
      el.innerHTML = '';
      const mk = (label, val, count) => {
        const c = document.createElement('button');
        c.className = 'memory-cat-chip' + (_arcTypeFilter === val ? ' active' : '');
        c.textContent = label + ' (' + count + ')';
        c.addEventListener('click', () => { _arcTypeFilter = _arcTypeFilter === val ? '' : val; _renderArcGrid(); _renderArcChips(); });
        el.appendChild(c);
      };
      const total = _arcSessions.length + _arcDocs.length + _arcResearch.length;
      if (!total) return;
      mk('All', '', total);
      if (_arcSessions.length) mk('Chats', 'chats', _arcSessions.length);
      if (_arcDocs.length) mk('Documents', 'documents', _arcDocs.length);
      if (_arcResearch.length) mk('Research', 'research', _arcResearch.length);
    }

    function _updateArcCount() { const el = document.getElementById('doclib-arc-selected-count'); if (el) el.textContent = _arcSelected.size + ' Selected'; }

    // Archive event listeners
    document.getElementById('doclib-arc-sort').addEventListener('change', (e) => { _arcSort = e.target.value; _renderArcGrid(); });
    document.getElementById('doclib-arc-search').addEventListener('input', (e) => { _arcSearch = e.target.value.trim(); _renderArcGrid(); });
    document.getElementById('doclib-arc-select-btn').addEventListener('click', () => { _arcSelectMode = !_arcSelectMode; _arcSelected.clear(); document.getElementById('doclib-arc-bulk').classList.toggle('hidden', !_arcSelectMode); _renderArcGrid(); });
    document.getElementById('doclib-arc-bulk-cancel')?.addEventListener('click', () => {
      _arcSelectMode = false; _arcSelected.clear();
      document.getElementById('doclib-arc-bulk').classList.add('hidden');
      _renderArcGrid();
    });
    // Select-all toggles EVERY visible archived card (chats + docs + research),
    // keyed by the card's composite "type:id" data-arckey.
    function _arcToggleAll() {
      const cbs = document.querySelectorAll('#doclib-arc-grid .memory-select-cb');
      const newState = _arcSelected.size < cbs.length;
      const allCb = document.getElementById('doclib-arc-select-all');
      if (allCb) allCb.checked = newState;
      cbs.forEach(cb => {
        cb.checked = newState;
        const k = cb.dataset.arckey;
        if (k) { if (newState) _arcSelected.add(k); else _arcSelected.delete(k); }
      });
      _updateArcCount();
    }
    document.getElementById('doclib-arc-select-all').addEventListener('change', _arcToggleAll);
    document.getElementById('doclib-arc-bulk').addEventListener('click', (e) => {
      if (e.target.closest('button') || e.target.closest('input')) return;
      _arcToggleAll();
    });
    // Route a composite "type:id" key to the right restore / delete endpoint.
    function _arcRestoreOne(key) {
      const i = key.indexOf(':'), type = key.slice(0, i), id = key.slice(i + 1);
      if (type === 'documents') return fetch(API_BASE + '/api/document/' + id + '/archive?archived=false', { method: 'POST', credentials: 'same-origin' });
      if (type === 'research') return fetch('/api/research/' + id + '/archive?archived=false', { method: 'POST', credentials: 'same-origin' });
      return fetch(API_BASE + '/api/session/' + id + '/unarchive', { method: 'POST', credentials: 'same-origin' });
    }
    function _arcDeleteOne(key) {
      const i = key.indexOf(':'), type = key.slice(0, i), id = key.slice(i + 1);
      if (type === 'documents') return fetch(API_BASE + '/api/document/' + id, { method: 'DELETE', credentials: 'same-origin' });
      if (type === 'research') return fetch('/api/research/' + id, { method: 'DELETE', credentials: 'same-origin' });
      return fetch(API_BASE + '/api/session/' + id, { method: 'DELETE', credentials: 'same-origin' });
    }
    document.getElementById('doclib-arc-bulk-restore').addEventListener('click', async () => {
      if (!_arcSelected.size) return;
      await Promise.all([..._arcSelected].map(_arcRestoreOne));
      _arcSelected.clear(); _arcSelectMode = false;
      document.getElementById('doclib-arc-bulk').classList.add('hidden');
      _renderLibArchive();
    });
    document.getElementById('doclib-arc-bulk-delete').addEventListener('click', async () => {
      const count = _arcSelected.size;
      if (!count) return;
      if (!await window.styledConfirm(`Delete ${count} archived item${count > 1 ? 's' : ''} permanently?`, { confirmText: 'Delete', danger: true })) return;
      const grid = document.getElementById('doclib-arc-grid');
      if (grid) {
        grid.querySelectorAll('.memory-item[data-arckey]').forEach(card => {
          if (_arcSelected.has(card.dataset.arckey)) {
            card.style.transition = 'opacity 0.25s, transform 0.25s';
            card.style.opacity = '0';
            card.style.transform = 'scale(0.95)';
          }
        });
      }
      await new Promise(r => setTimeout(r, 250));
      await Promise.all([..._arcSelected].map(_arcDeleteOne));
      _arcSelected.clear();
      _arcSelectMode = false;
      document.getElementById('doclib-arc-bulk').classList.add('hidden');
      _renderLibArchive();
    });

    // ── Research tab ──
    let _researchItems = [];
    let _researchSearch = '';
    let _researchSelectMode = false;
    let _researchArchivedView = false;
    const _researchSelected = new Set();

    async function _renderLibResearch() {
      const grid = document.getElementById('doclib-research-grid');
      const stats = document.getElementById('doclib-research-stats');
      if (!grid) return;
      // Show our whirlpool spinner instead of the plain "Loading..." text.
      grid.innerHTML = '';
      try {
        const _spm = (await import('./spinner.js')).default;
        const _sp = _spm.createWhirlpool(22);
        _sp.element.style.cssText = 'margin:18px auto;display:block;';
        grid.appendChild(_sp.element);
      } catch { grid.innerHTML = '<div class="hwfit-loading">Loading…</div>'; }
      try {
        const res = await fetch('/api/research/library' + (_researchArchivedView ? '?archived=true' : ''), { credentials: 'same-origin' });
        if (!res.ok) throw new Error(res.statusText);
        const data = await res.json();
        _researchItems = data.research || data || [];
      } catch (e) {
        grid.innerHTML = `<div class="hwfit-loading">Failed to load: ${e.message}</div>`;
        return;
      }
      _renderResearchGrid();
    }

    // Toggle inline preview for a research row. Mirrors _toggleChatPreview
     // but pulls research-specific metadata: query, sources list (truncated),
     // followed by an "Open" action that loads the full report.
    async function _toggleResearchPreview(card, item) {
      const preview = card.querySelector('.doclib-chat-preview');
      if (!preview) return;
      const isOpen = card.classList.contains('doclib-card-expanded');
      const grid = card.closest('.doclib-grid');
      if (grid) {
        grid.querySelectorAll('.doclib-card-expanded').forEach(c => {
          if (c !== card) {
            c.classList.remove('doclib-card-expanded');
            const p = c.querySelector('.doclib-chat-preview');
            if (p) { p.style.display = 'none'; p.innerHTML = ''; }
          }
        });
      }
      if (isOpen) {
        card.classList.remove('doclib-card-expanded');
        preview.style.display = 'none';
        preview.innerHTML = '';
        return;
      }
      card.classList.add('doclib-card-expanded');
      preview.style.display = 'block';
      preview.innerHTML = '<div style="opacity:0.4;font-size:11px;padding:8px 4px;">Loading…</div>';
      let detail = item;
      try {
        // Hit the per-research detail endpoint to pull sources + summary.
        // The library list endpoint only returns lightweight metadata.
        const res = await fetch(`${API_BASE}/api/research/detail/${item.id}`, { credentials: 'same-origin' });
        if (res.ok) detail = await res.json();
      } catch {}
      const sources = Array.isArray(detail.sources) ? detail.sources : [];
      const sourcesList = sources.slice(0, 12).map((src, i) => {
        const title = _esc(src.title || src.url || `Source ${i + 1}`);
        const url = src.url || '';
        return url
          ? `<li><a href="${_esc(url)}" target="_blank" rel="noopener">${title}</a></li>`
          : `<li>${title}</li>`;
      }).join('');
      const sourcesHtml = sources.length
        ? `<div class="doclib-research-sources"><div class="doclib-research-section-label">Sources (${sources.length})</div><ol>${sourcesList}${sources.length > 12 ? `<li style="opacity:0.5;">…and ${sources.length - 12} more</li>` : ''}</ol></div>`
        : '';
      // The stored research JSON keeps the report under `result` (clean) /
      // `raw_report` — there's no `summary` field, so the preview was empty.
      const summary = (detail.summary || detail.report_summary || detail.result || detail.raw_report || '').toString().trim();
      const summaryHtml = summary
        ? `<div class="doclib-research-summary"><div class="doclib-research-section-label">Report</div><div>${markdownModule.mdToHtml ? markdownModule.mdToHtml(summary) : _esc(summary)}</div></div>`
        : '';
      preview.innerHTML =
        '<div class="doclib-chat-preview-messages">' +
          (summaryHtml || sourcesHtml || '<div style="opacity:0.4;font-size:11px;padding:6px 4px;">No preview available</div>') +
          (summaryHtml && sourcesHtml ? sourcesHtml : '') +
        '</div>' +
        '<div class="doclib-chat-preview-actions">' +
          '<button class="doclib-chat-delete-btn">' +
            '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>' +
            'Delete' +
          '</button>' +
          '<button class="doclib-chat-archive-btn">' +
            '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/><line x1="10" y1="12" x2="14" y2="12"/></svg>' +
            ((_researchArchivedView || item.archived) ? 'Restore' : 'Archive') +
          '</button>' +
          // Discuss is hidden in the Archive so the footer matches chat
          // (Delete + Restore + Open).
          (item.archived ? '' :
          '<button class="doclib-chat-discuss-btn">' +
            '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>' +
            'Discuss' +
          '</button>') +
          '<button class="doclib-chat-open-btn">' +
            '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 5l7 7-7 7"/></svg>' +
            'Open' +
          '</button>' +
        '</div>';
      const discussBtn = preview.querySelector('.doclib-chat-discuss-btn');
      if (discussBtn) discussBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const _orig = discussBtn.innerHTML;
        discussBtn.disabled = true;
        discussBtn.textContent = 'Creating…';
        try {
          const _sid = detail.session_id || detail.id || item.id;
          const res = await fetch(`${API_BASE}/api/research/spinoff/${_sid}`, { method: 'POST', credentials: 'same-origin' });
          if (!res.ok) { let d = ''; try { d = (await res.json()).detail || ''; } catch {} throw new Error(d || ('HTTP ' + res.status)); }
          const payload = await res.json();
          if (window.sessionModule && payload.session_id) {
            await window.sessionModule.loadSessions().catch(e => console.error('Silent catch in documentLibrary:', e));
            await window.sessionModule.selectSession(payload.session_id);
          }
          closeLibrary();
        } catch (err) {
          discussBtn.disabled = false;
          discussBtn.innerHTML = _orig;
          if (uiModule) uiModule.showError('Could not start discussion: ' + (err.message || err));
        }
      });
      const openBtn = preview.querySelector('.doclib-chat-open-btn');
      if (openBtn) openBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const a = document.createElement('a');
        a.href = '/api/research/report/' + item.id;
        a.target = '_blank';
        a.rel = 'noopener';
        document.body.appendChild(a);
        a.click();
        a.remove();
      });
      const delBtn = preview.querySelector('.doclib-chat-delete-btn');
      if (delBtn) delBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const ok = uiModule && uiModule.styledConfirm
          ? await uiModule.styledConfirm('Delete this research report?', { confirmText: 'Delete', danger: true })
          : window.confirm('Delete this research report?');
        if (!ok) return;
        try {
          const res = await fetch(`${API_BASE}/api/research/${item.id}`, { method: 'DELETE', credentials: 'same-origin' });
          if (!res.ok) throw new Error(await res.text());
          if (item.archived) {
            _renderLibArchive();
          } else {
            _researchItems = _researchItems.filter(r => r.id !== item.id);
            _renderResearchGrid();
          }
        } catch (err) {
          if (uiModule && uiModule.showError) uiModule.showError('Failed to delete: ' + err.message);
        }
      });
      const arcBtn = preview.querySelector('.doclib-chat-archive-btn');
      if (arcBtn) arcBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        // From the main Archive tab the item is already archived → Restore and
        // refresh the archive. From the Research tab, toggle as before.
        const fromArchiveTab = !!item.archived;
        const toArchived = fromArchiveTab ? false : !_researchArchivedView;
        try {
          await fetch(`${API_BASE}/api/research/${item.id}/archive?archived=${toArchived}`, { method: 'POST', credentials: 'same-origin' });
          if (fromArchiveTab) {
            _renderLibArchive();
          } else {
            _researchItems = _researchItems.filter(r => r.id !== item.id);
            _renderResearchGrid();
          }
          if (uiModule) uiModule.showToast(toArchived ? 'Archived' : 'Restored');
        } catch { if (uiModule) uiModule.showError('Failed to ' + (toArchived ? 'archive' : 'restore')); }
      });
    }

    function _renderResearchGrid() {
      const grid = document.getElementById('doclib-research-grid');
      const stats = document.getElementById('doclib-research-stats');
      if (!grid) return;
      const _rsb = document.getElementById('doclib-research-select-btn');
      if (_rsb) { _rsb.classList.toggle('active', _researchSelectMode); _rsb.textContent = _researchSelectMode ? 'Cancel' : 'Select'; }
      let items = _researchItems;
      if (_researchSearch) {
        const s = _researchSearch.toLowerCase();
        items = items.filter(r => (r.query || '').toLowerCase().includes(s));
      }
      // Sort
      const _rSort = document.getElementById('doclib-research-sort')?.value || 'recent';
      if (_rSort === 'recent') items.sort((a, b) => (b.completed_at || 0) - (a.completed_at || 0));
      else if (_rSort === 'oldest') items.sort((a, b) => (a.completed_at || 0) - (b.completed_at || 0));
      else if (_rSort === 'most-sources') items.sort((a, b) => (b.source_count || 0) - (a.source_count || 0));
      else if (_rSort === 'alpha') items.sort((a, b) => (a.query || '').localeCompare(b.query || ''));
      if (stats) stats.textContent = items.length + ' research' + (items.length !== 1 ? 'es' : '');
      if (!items.length) {
        grid.innerHTML =
          '<div class="hwfit-loading" style="display:flex;align-items:center;justify-content:center;gap:8px;flex-wrap:wrap;">' +
            '<span>No research yet</span>' +
            '<span style="opacity:0.7;font-size:11px;">' +
              'create one in the <a href="#" data-doclib-open-research style="color:var(--accent,var(--red));text-decoration:underline;">Deep Research</a> tab' +
            '</span>' +
          '</div>';
        grid.querySelector('[data-doclib-open-research]')?.addEventListener('click', (e) => {
          e.preventDefault();
          document.getElementById('rail-research')?.click();
        });
        _appendInlineLoadMore(grid, 0, _researchVisibleLimit, () => {});
        return;
      }
      const total = items.length;
      items = items.slice(0, _researchVisibleLimit);
      let html = '';
      for (const r of items) {
        const date = r.completed_at ? new Date(r.completed_at * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '';
        const time = r.completed_at ? new Date(r.completed_at * 1000).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : '';
        const sources = r.source_count || 0;
        const duration = r.duration || '';
        const rounds = r.rounds || '';
        const selected = _researchSelected.has(r.id);
        const metaBits = [];
        if (date) metaBits.push(`${date} ${time}`);
        if (sources) metaBits.push(`${sources} sources`);
        if (rounds) metaBits.push(`${rounds} rounds`);
        if (duration) metaBits.push(`${duration}`);
        const metaText = metaBits.join(' \u00B7 ');
        html += `<div class="memory-item doclib-chat-row doclib-research-card" data-research-id="${r.id}" style="cursor:pointer;">`;
        html += `<div class="doclib-chat-header" style="display:flex;align-items:center;width:100%;gap:6px;">`;
        if (_researchSelectMode) html += `<input type="checkbox" class="memory-select-cb _res-cb" data-rid="${r.id}"${selected ? ' checked' : ''}>`;
        html += `<div style="flex:1;min-width:0;">`;
        html += `<div class="memory-item-title"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px;opacity:0.4;flex-shrink:0;"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg>${_esc(r.query || 'Untitled Research')}</div>`;
        html += `<div class="memory-item-meta" style="font-size:10px;opacity:0.4;margin-top:2px;">${metaText}</div>`;
        html += `</div>`;
        if (!_researchSelectMode) html += `<div class="memory-item-actions"><button class="memory-item-btn doclib-research-delete" data-rid="${r.id}" title="Delete"><svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="12" cy="19" r="2"/></svg></button></div>`;
        html += `</div>`;
        html += `<div class="doclib-chat-preview" style="display:none;"></div>`;
        html += `</div>`;
      }
      grid.innerHTML = html;
      _maybeCascadeGrid(grid, 'research');

      // Wire checkboxes
      grid.querySelectorAll('._res-cb').forEach(cb => {
        cb.addEventListener('click', e => e.stopPropagation());
        cb.addEventListener('change', () => {
          if (cb.checked) _researchSelected.add(cb.dataset.rid); else _researchSelected.delete(cb.dataset.rid);
          _updateResearchCount();
        });
      });

      // Click card → toggle preview (chat-style expand). The menu button
      // and Open-report button inside the preview are exempt.
      grid.querySelectorAll('.doclib-research-card').forEach(card => {
        card.addEventListener('click', (e) => {
          if (card._suppressNextClick) { card._suppressNextClick = false; return; }
          if (e.target.closest('.doclib-research-delete') || e.target.closest('._res-cb') || e.target.closest('.doclib-chat-open-btn')) return;
          const rid = card.dataset.researchId;
          if (_researchSelectMode) {
            const cb = card.querySelector('._res-cb');
            if (cb) { cb.checked = !cb.checked; cb.dispatchEvent(new Event('change')); }
            return;
          }
          const item = _researchItems.find(r => r.id === rid);
          if (item) _toggleResearchPreview(card, item);
        });
        _attachLongPressMenu(card, '.doclib-research-delete');
      });

      // The action button on each research row opens the actions menu
      // (Open report, Delete) — chat-style ••• menu.
      grid.querySelectorAll('.doclib-research-delete').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const rid = btn.dataset.rid;
          _showLibDropdown(btn, [
            { label: 'Open', action: () => {
                const a = document.createElement('a');
                a.href = '/api/research/report/' + rid;
                a.target = '_blank';
                a.rel = 'noopener';
                document.body.appendChild(a);
                a.click();
                a.remove();
              } },
            { label: _researchArchivedView ? 'Restore' : 'Archive', action: async () => {
                const toArchived = !_researchArchivedView;
                const card = btn.closest('.doclib-research-card');
                if (card) { card.style.transition = 'opacity 0.25s, transform 0.25s'; card.style.opacity = '0'; card.style.transform = 'scale(0.95)'; }
                try { await fetch('/api/research/' + rid + '/archive?archived=' + toArchived, { method: 'POST', credentials: 'same-origin' }); } catch {}
                await new Promise(r => setTimeout(r, 200));
                _researchItems = _researchItems.filter(r => r.id !== rid);
                _renderResearchGrid();
                if (uiModule) uiModule.showToast(toArchived ? 'Archived' : 'Restored');
              } },
            { label: 'Delete', danger: true, action: async () => {
                if (!await window.styledConfirm('Delete this research?', { confirmText: 'Delete', danger: true })) return;
                const card = btn.closest('.doclib-research-card');
                if (card) {
                  card.style.transition = 'opacity 0.25s, transform 0.25s';
                  card.style.opacity = '0';
                  card.style.transform = 'scale(0.95)';
                }
                await new Promise(r => setTimeout(r, 250));
                await fetch('/api/research/' + rid, { method: 'DELETE', credentials: 'same-origin' });
                _researchItems = _researchItems.filter(r => r.id !== rid);
                _renderResearchGrid();
              } },
          ], { onSelect: () => {
            _researchSelectMode = true;
            _researchSelected.add(rid);
            document.getElementById('doclib-research-bulk')?.classList.remove('hidden');
            _renderResearchGrid();
          } });
        });
      });
      _appendInlineLoadMore(grid, total, _researchVisibleLimit, () => {
        _researchVisibleLimit += _LIB_PAGE_SIZE;
        _renderResearchGrid();
      });
    }

    // Research sort + search
    const researchSortEl = document.getElementById('doclib-research-sort');
    if (researchSortEl) researchSortEl.addEventListener('change', () => _renderResearchGrid());
    const researchSearchEl = document.getElementById('doclib-research-search');
    if (researchSearchEl) {
      researchSearchEl.addEventListener('input', () => {
        _researchSearch = researchSearchEl.value.trim();
        _renderResearchGrid();
      });
    }

    function _updateResearchCount() {
      const el = document.getElementById('doclib-research-selected-count');
      if (el) el.textContent = _researchSelected.size + ' Selected';
      const arc = document.getElementById('doclib-research-bulk-archive');
      if (arc) arc.textContent = _researchArchivedView ? 'Restore' : 'Archive';
    }

    // Research select mode
    document.getElementById('doclib-research-select-btn')?.addEventListener('click', () => {
      _researchSelectMode = !_researchSelectMode;
      _researchSelected.clear();
      document.getElementById('doclib-research-bulk').classList.toggle('hidden', !_researchSelectMode);
      _renderResearchGrid();
    });

    // Research tidy — delete reports that came back empty (no sources, or
    // empty report body). Matches the Chats tidy whirlpool/borderless pattern
    // and skips confirmation per user request.
    document.getElementById('doclib-research-tidy-btn')?.addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      const origHTML = btn.innerHTML;
      btn.disabled = true;
      btn.classList.add('spinning');
      btn.textContent = '';
      const sp = spinnerModule.create('', 'clean', 'whirlpool');
      const el = sp.createElement();
      el.style.position = 'relative';
      el.style.top = '1px';
      btn.appendChild(el);
      sp.start();
      try {
        const candidates = [];
        const needFetch = [];
        for (const r of _researchItems) {
          if ((r.source_count || 0) === 0) candidates.push(r);
          else needFetch.push(r);
        }
        const results = await Promise.all(needFetch.map(async r => {
          try {
            const res = await fetch('/api/research/detail/' + r.id, { credentials: 'same-origin' });
            if (!res.ok) return null;
            const d = await res.json();
            // Backend JSON uses `result` (rendered) or `raw_report` (raw md).
            // If neither exists or both are tiny, treat as empty.
            const body = (d.result || d.raw_report || '').trim();
            return body.length < 200 ? r : null;
          } catch { return null; }
        }));
        for (const r of results) if (r) candidates.push(r);
        if (candidates.length === 0) {
          if (uiModule) uiModule.showToast('Nothing to tidy');
          return;
        }
        await Promise.all(candidates.map(r => fetch('/api/research/' + r.id, { method: 'DELETE', credentials: 'same-origin' }).catch(e => console.error('Silent catch in documentLibrary:', e))));
        const ids = new Set(candidates.map(r => r.id));
        _researchItems = _researchItems.filter(r => !ids.has(r.id));
        _renderResearchGrid();
        if (uiModule) uiModule.showToast('Deleted ' + candidates.length);
      } finally {
        sp.stop();
        btn.disabled = false;
        btn.classList.remove('spinning');
        btn.innerHTML = origHTML;
      }
    });
    document.getElementById('doclib-research-archived-btn')?.addEventListener('click', (e) => {
      _researchArchivedView = !_researchArchivedView;
      e.currentTarget.classList.toggle('active', _researchArchivedView);
      e.currentTarget.title = _researchArchivedView ? 'Show active research' : 'Show archived research';
      if (_researchSelectMode) { _researchSelectMode = false; _researchSelected.clear(); document.getElementById('doclib-research-bulk').classList.add('hidden'); }
      _renderLibResearch();
    });
    document.getElementById('doclib-research-bulk-cancel')?.addEventListener('click', () => {
      _researchSelectMode = false;
      _researchSelected.clear();
      document.getElementById('doclib-research-bulk').classList.add('hidden');
      _renderResearchGrid();
    });

    // Research select all
    document.getElementById('doclib-research-select-all')?.addEventListener('change', () => {
      const allCb = document.getElementById('doclib-research-select-all');
      const newState = allCb?.checked;
      _researchItems.forEach(r => { if (newState) _researchSelected.add(r.id); else _researchSelected.delete(r.id); });
      _updateResearchCount();
      _renderResearchGrid();
    });

    // Research bulk delete
    document.getElementById('doclib-research-bulk-delete')?.addEventListener('click', async () => {
      const count = _researchSelected.size;
      if (!count) return;
      if (!await window.styledConfirm(`Delete ${count} research report${count > 1 ? 's' : ''} permanently?`, { confirmText: 'Delete', danger: true })) return;
      const grid = document.getElementById('doclib-research-grid');
      if (grid) {
        grid.querySelectorAll('.doclib-research-card').forEach(card => {
          if (_researchSelected.has(card.dataset.researchId)) {
            card.style.transition = 'opacity 0.25s, transform 0.25s';
            card.style.opacity = '0';
            card.style.transform = 'scale(0.95)';
          }
        });
      }
      await new Promise(r => setTimeout(r, 250));
      await Promise.all([..._researchSelected].map(rid => fetch('/api/research/' + rid, { method: 'DELETE', credentials: 'same-origin' })));
      _researchItems = _researchItems.filter(r => !_researchSelected.has(r.id));
      _researchSelected.clear();
      _researchSelectMode = false;
      document.getElementById('doclib-research-bulk').classList.add('hidden');
      _renderResearchGrid();
    });

    // Research bulk archive / restore
    document.getElementById('doclib-research-bulk-archive')?.addEventListener('click', async () => {
      const count = _researchSelected.size;
      if (!count) return;
      const toArchived = !_researchArchivedView;
      const grid = document.getElementById('doclib-research-grid');
      if (grid) {
        grid.querySelectorAll('.doclib-research-card').forEach(card => {
          if (_researchSelected.has(card.dataset.researchId)) {
            card.style.transition = 'opacity 0.25s, transform 0.25s';
            card.style.opacity = '0';
            card.style.transform = 'scale(0.95)';
          }
        });
      }
      await new Promise(r => setTimeout(r, 250));
      await Promise.all([..._researchSelected].map(rid => fetch('/api/research/' + rid + '/archive?archived=' + toArchived, { method: 'POST', credentials: 'same-origin' })));
      _researchItems = _researchItems.filter(r => !_researchSelected.has(r.id));
      _researchSelected.clear();
      _researchSelectMode = false;
      document.getElementById('doclib-research-bulk').classList.add('hidden');
      _renderResearchGrid();
      if (uiModule) uiModule.showToast(toArchived ? 'Archived' : 'Restored');
    });

    // Shared dropdown for chats/archive menus — defined at module scope below
    // (was here originally; hoisted so libraryCreateCard's mobile kebab
    // handler — which lives outside openLibrary's closure — can call it).

    function _relTime(iso) {
      if (!iso) return '';
      const diff = Date.now() - new Date(iso).getTime();
      const mins = Math.floor(diff / 60000);
      if (mins < 60) return mins + 'm ago';
      const hrs = Math.floor(mins / 60);
      if (hrs < 24) return hrs + 'h ago';
      const days = Math.floor(hrs / 24);
      if (days < 30) return days + 'd ago';
      return new Date(iso).toLocaleDateString();
    }

    // Switch to initial tab if not documents
    if (_activeLibTab !== 'documents') _switchLibTab(_activeLibTab);

    const searchInput = document.getElementById('doclib-search');
    searchInput.addEventListener('input', () => {
      clearTimeout(_librarySearchDebounce);
      _librarySearchDebounce = setTimeout(() => {
        _librarySearch = searchInput.value.trim();
        libraryFetch(false);
      }, 300);
    });

    document.getElementById('doclib-sort').addEventListener('change', (e) => {
      _librarySort = e.target.value;
      libraryFetch(false);
    });

    document.getElementById('doclib-load-more').addEventListener('click', () => {
      _libraryOffset = _libraryDocs.length;
      libraryFetch(true);
    });

    // Show "Load more" only when scrolled near bottom
    const grid = document.getElementById('doclib-grid');
    if (grid) {
      grid.addEventListener('scroll', () => libraryRenderLoadMore());
      // Auto-fill on resize (fullscreen toggle, window resize, sidebar
      // toggle): re-run the load-more check so newly-revealed empty
      // space below the last card pulls in the next page automatically.
      if (typeof ResizeObserver !== 'undefined') {
        new ResizeObserver(() => libraryRenderLoadMore()).observe(grid);
      }
    }

    // Wire file import button
    const importFileBtn = document.getElementById('doclib-import-file-btn');
    const fileInput = document.getElementById('doclib-file-input');
    if (importFileBtn && fileInput) {
      importFileBtn.addEventListener('click', () => fileInput.click());
      fileInput.addEventListener('change', async () => {
        if (fileInput.files.length === 0) return;
        const files = fileInput.files;
        fileInput.value = '';
        // Swap the import icon for a whirlpool while files upload.
        const _orig = importFileBtn.innerHTML;
        importFileBtn.disabled = true;
        let _sp = null;
        try {
          _sp = spinnerModule.createWhirlpool(12);
          _sp.element.style.cssText = 'width:12px;height:12px;margin:0 4px 0 0;display:inline-block;vertical-align:middle;position:relative;top:-2px;';
          importFileBtn.innerHTML = '';
          importFileBtn.appendChild(_sp.element);
          importFileBtn.appendChild(document.createTextNode('Import'));
        } catch {}
        try {
          await libraryImportFiles(files);
        } finally {
          try { _sp && _sp.stop(); } catch {}
          importFileBtn.innerHTML = _orig;
          importFileBtn.disabled = false;
        }
      });
    }

    // Create button — new blank document
    const createBtn = document.getElementById('doclib-create-btn');
    if (createBtn) {
      createBtn.addEventListener('click', async () => {
        // Create a new session, then create a blank document in it
        try {
          const sRes = await fetch('/api/session', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: 'Untitled Document' }) });
          const sData = await sRes.json();
          const sessionId = sData.session_id;
          await _createDocument(sessionId);
          // Close library and open the new session
          closeLibrary();
          if (window.sessionsModule) window.sessionsModule.loadSession(sessionId);
          setTimeout(() => _openPanel(), 300);
        } catch (e) {
          console.error('Failed to create document:', e);
          if (uiModule) uiModule.showError('Failed to create document');
        }
      });
    }

    // Archived toggle — flip the Documents list between active and archived.
    const archivedBtn = document.getElementById('doclib-archived-btn');
    if (archivedBtn) archivedBtn.addEventListener('click', () => {
      _libraryArchivedView = !_libraryArchivedView;
      archivedBtn.classList.toggle('active', _libraryArchivedView);
      archivedBtn.title = _libraryArchivedView ? 'Show active documents' : 'Show archived documents';
      if (_librarySelectMode) libraryExitSelectMode();
      libraryFetch(false);
    });

    // Tidy button — remove empty/broken documents
    const tidyBtn = document.getElementById('doclib-tidy-btn');
    if (tidyBtn) tidyBtn.addEventListener('click', async () => {
      tidyBtn.disabled = true;
      tidyBtn.classList.add('spinning');
      const origHTML = tidyBtn.innerHTML;
      tidyBtn.textContent = '';
      const spinner = spinnerModule.create('', 'clean', 'whirlpool');
      const _spEl = spinner.createElement();
      // Optical alignment: whirlpool reads 1px high inside the button.
      _spEl.style.position = 'relative';
      _spEl.style.top = '1px';
      tidyBtn.appendChild(_spEl);
      spinner.start();

      let totalDeleted = 0;
      let totalFixed = 0;
      let aiMessage = '';
      try {
        // Phase 1: regex tidy (empty/broken docs)
        const [res1] = await Promise.all([
          fetch(`${API_BASE}/api/documents/tidy`, { method: 'POST' }),
          new Promise(r => setTimeout(r, 600)),
        ]);
        if (res1.ok) {
          const d1 = await res1.json();
          totalDeleted += d1.deleted || 0;
          totalFixed += d1.fixed_titles || 0;
        }

        // Phase 2: AI tidy (junk/test detection)
        try {
          const res2 = await fetch(`${API_BASE}/api/documents/ai-tidy`, { method: 'POST' });
          if (res2.ok) {
            const d2 = await res2.json();
            totalDeleted += d2.deleted || 0;
            if (d2.message) aiMessage = d2.message;
          }
        } catch (_) { /* AI tidy is optional */ }

        spinner.destroy();

        if (totalDeleted === 0 && totalFixed === 0) {
          tidyBtn.innerHTML = '<span style="opacity:0.7">Already tidy</span>';
        } else {
          const msg = aiMessage || `Removed ${totalDeleted} document${totalDeleted !== 1 ? 's' : ''}`;
          if (uiModule) uiModule.showToast(msg);
          libraryFetch(false);
        }
        setTimeout(() => { tidyBtn.innerHTML = origHTML; tidyBtn.disabled = false; tidyBtn.classList.remove('spinning'); }, 1500);
      } catch (e) {
        spinner.destroy();
        console.error('Document tidy failed:', e);
        if (uiModule) uiModule.showToast('Tidy failed');
        tidyBtn.disabled = false;
        tidyBtn.classList.remove('spinning');
        tidyBtn.innerHTML = origHTML;
      }
    });

    // Select mode
    const selectBtn = document.getElementById('doclib-select-btn');
    if (selectBtn) selectBtn.addEventListener('click', () => {
      if (_librarySelectMode) libraryExitSelectMode();
      else libraryEnterSelectMode();
    });

    const selectAll = document.getElementById('doclib-select-all');
    if (selectAll) selectAll.addEventListener('change', libraryToggleSelectAll);

    // Click anywhere in the bulk bar "All" label or count area to toggle select-all
    const bulkCheckLabel = modal.querySelector('.memory-bulk-check-all');
    if (bulkCheckLabel) {
      bulkCheckLabel.addEventListener('click', (e) => {
        if (e.target === selectAll) return; // let native checkbox handle it
        e.preventDefault();
        selectAll.checked = !selectAll.checked;
        libraryToggleSelectAll();
      });
    }
    const selectedCountEl = document.getElementById('doclib-selected-count');
    if (selectedCountEl) {
      selectedCountEl.style.cursor = 'pointer';
      selectedCountEl.addEventListener('click', () => {
        selectAll.checked = !selectAll.checked;
        libraryToggleSelectAll();
      });
    }

    const bulkActionsBtn = document.getElementById('doclib-bulk-actions');
    if (bulkActionsBtn) bulkActionsBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (_librarySelectedIds.size === 0) {
        if (uiModule) uiModule.showToast('Select documents first');
        return;
      }
      _showLibDropdown(e.currentTarget, [
        { label: _libraryArchivedView ? 'Restore' : 'Archive', icon: _libraryArchivedView ? 'restore' : 'archive', action: libraryBulkArchive },
        { label: 'Clone', icon: 'clone', action: libraryBulkClone },
        { label: 'Export', icon: 'open', action: libraryBulkExport },
        { label: 'Delete', icon: 'delete', danger: true, action: libraryBulkDelete },
      ], { onCancel: libraryExitSelectMode });
    });

    const bulkCancelBtn = document.getElementById('doclib-bulk-cancel');
    if (bulkCancelBtn) bulkCancelBtn.addEventListener('click', libraryExitSelectMode);

    // Close on click outside modal content
    modal.addEventListener('click', (e) => {
      if (uiModule.isTouchInsideModal()) return;
      if (e.target === modal) closeLibrary();
    });

    // Escape key
    _libraryEscHandler = (e) => {
      if (e.key === 'Escape') {
        // Collapse expanded card first, then close modal on second Escape
        const expanded = document.querySelector('#doclib-grid .doclib-card-expanded');
        if (expanded) {
          _collapseExpandedCard(expanded);
        } else {
          closeLibrary();
        }
      }
    };
    document.addEventListener('keydown', _libraryEscHandler);

    // Toggle active on tool button
    const btn = document.getElementById('tool-doclib-btn');
    if (btn) btn.classList.add('active');

    libraryFetch(false);
    if (window.innerWidth >= 768) searchInput.focus();
  }

  export function closeLibrary() {
    if (!_libraryOpen) return;
    _libraryOpen = false;
    _librarySelectMode = false;
    _librarySelectedIds.clear();
    _libraryImportMode = false;
    clearTimeout(_librarySearchDebounce);

    const modal = document.getElementById('doclib-modal');
    if (modal) {
      const content = modal.querySelector('.modal-content, .doclib-modal-content');
      if (content) {
        content.classList.add('modal-closing');
        content.addEventListener('animationend', () => modal.remove(), { once: true });
        setTimeout(() => { if (modal.parentElement) modal.remove(); }, 250);
      } else {
        modal.remove();
      }
    }

    if (_libraryEscHandler) {
      document.removeEventListener('keydown', _libraryEscHandler);
      _libraryEscHandler = null;
    }

    const btn = document.getElementById('tool-doclib-btn');
    if (btn) btn.classList.remove('active');
  }

  export function isLibraryOpen() {
    return _libraryOpen;
  }

  // ── Cross-surface document accessors (#293,#289) ───────────────────
  // Let other surfaces (Calendar, gallery, compare) read documents without
  // loading the full library modal.

  export function getStoredDocuments() {
    return _getDocs ? [..._getDocs().values()] : [];
  }

  export function getDocumentById(id) {
    const docs = _getDocs ? _getDocs() : new Map();
    return docs.get(id) || null;
  }

  export async function fetchEngineDocuments() {
    try {
      const r = await fetch(`${API_BASE}/api/applicant/documents`, { credentials: 'same-origin' });
      if (!r.ok) return [];
      const data = await r.json();
      return Array.isArray(data.documents) ? data.documents : (Array.isArray(data) ? data : []);
    } catch (_) {
      return [];
    }
  }

  const documentLibraryModule = {
    openLibrary, closeLibrary, isLibraryOpen,
    getStoredDocuments, getDocumentById, fetchEngineDocuments,
  };
