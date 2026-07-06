// static/sw.js — Applicant PWA Service Worker
// Strategy:
//   - HTML (navigation): stale-while-revalidate. Instant open from cache,
//     background refresh so the next open has latest HTML.
//   - JS/CSS (/static/*.js|.css): network-first, cache fallback for offline.
//     (So code/style edits show up on a normal reload, no manual cache clear.)
//   - Other static assets (images/fonts/libs): cache-first with bg refresh.
//   - API / non-GET: never cached.
// Bump CACHE_NAME whenever the precache list or SW logic changes.
const CACHE_NAME = 'applicant-v328';

// Core shell precached on install so repeat opens are instant without any
// network wait. Keep this list in sync with the <script type="module"> tags
// and <link rel="stylesheet"> in index.html.
const PRECACHE = [
  '/',
  '/static/style.css',
  '/static/app.js',
  '/static/js/storage.js',
  '/static/js/ui.js',
  '/static/js/markdown.js',
  '/static/js/dragSort.js',
  '/static/js/sessions.js',
  '/static/js/memory.js',
  '/static/js/skills.js',
  '/static/js/tourHints.js',
  '/static/js/fileHandler.js',
  '/static/js/voiceRecorder.js',
  '/static/js/models.js',
  '/static/js/rag.js',
  '/static/js/presets.js',
  '/static/js/search.js',
  '/static/js/spinner.js',
  '/static/js/tts-ai.js',
  '/static/js/document.js',
  '/static/js/gallery.js',
  '/static/js/chatRenderer.js',
  '/static/js/codeRunner.js',
  '/static/js/chatStream.js',
  '/static/js/chat.js',
  '/static/js/cookbook.js',
  '/static/js/search-chat.js',
  '/static/js/compare/index.js',
  '/static/js/theme.js',
  '/static/js/censor.js',
  '/static/js/settings.js',
  '/static/js/admin.js',
  '/static/js/init.js',
  '/static/js/slashCommands.js',
  '/static/js/emailInbox.js',
  '/static/js/emailLibrary/utils.js',
  '/static/js/emailLibrary/signatureFold.js',
  '/static/js/emailLibrary/state.js',
  '/static/js/notes.js',
  '/static/js/tasks.js',
  '/static/js/calendar.js',
  '/static/js/calendar/utils.js',
  '/static/js/group.js',
  '/static/js/keyboard-shortcuts.js',
  '/static/js/sidebar-layout.js',
  '/static/js/section-management.js',
  '/static/lib/highlight.min.js',
  // Applicant module chain (lens-06 mobile/PWA audit #40): these load
  // network-first like the rest of the JS above, but weren't in the initial
  // precache — a first offline open of the Portal (the PWA's actual daily
  // surface) 404'd on modules it had never fetched online yet. Keep this
  // block in sync with the applicant* / documentLibrary imports.
  '/static/js/applicantCore.js',
  '/static/js/applicantPortal.js',
  '/static/js/applicantActivity.js',
  '/static/js/applicantOnboarding.js',
  '/static/js/applicantChat.js',
  '/static/js/applicantRemote.js',
  '/static/js/applicantVault.js',
  '/static/js/applicantResults.js',
  '/static/js/applicantTracker.js',
  '/static/js/applicantToday.js',
  '/static/js/applicantMind.js',
  '/static/js/applicantTrust.js',
  '/static/js/applicantCapabilities.js',
  '/static/js/applicantReachability.js',
  '/static/js/applicantAutomationSettings.js',
  '/static/js/applicantCampaignSettings.js',
  '/static/js/applicantModelLadder.js',
  '/static/js/applicantShortcuts.js',
  '/static/js/applicantCompare.js',
  '/static/js/applicantGallery.js',
  '/static/js/applicantUpdate.js',
  '/static/js/applicantUpdateView.js',
  '/static/js/applicantDebug.js',
  '/static/js/emailLibrary/applicantDigest.js',
  '/static/js/documentLibrary.js',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then(cache =>
      // addAll is atomic — if any item fails, none are cached. Use individual
      // puts so a single 404 can't block the whole install.
      Promise.all(
        PRECACHE.map(url =>
          fetch(url, { cache: 'reload' })
            .then(res => res.ok ? cache.put(url, res) : null)
            .catch(() => null)
        )
      )
    )
  );
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);

  // Badging API sync (lens-06 mobile/PWA audit #9 / #44): the Portal's badge
  // poll (`applicantPortal.js` refreshBadge) already computes the exact
  // pending count by hitting this one lightweight endpoint every 60s. Rather
  // than duplicating that request, piggyback on it here: forward it to the
  // network completely unchanged (still never cached, same response returned
  // to the page) and, as a side effect, mirror the count onto the installed
  // app icon via the Badging API when the browser supports it. Feature-detected
  // and best-effort only — never blocks or alters the actual response.
  if (url.pathname === '/api/applicant/portal/pending/count' && e.request.method === 'GET') {
    e.respondWith(
      fetch(e.request).then(res => {
        if (res && res.ok && 'setAppBadge' in self.navigator) {
          res.clone().json().then(data => {
            if (!data || data.engine_available === false) return;
            const n = Number(data.count) || 0;
            if (n > 0) {
              self.navigator.setAppBadge(n).catch(() => {});
            } else if ('clearAppBadge' in self.navigator) {
              self.navigator.clearAppBadge().catch(() => {});
            }
          }).catch(() => {});
        }
        return res;
      })
    );
    return;
  }

  // Never touch API calls or non-GET.
  if (url.pathname.startsWith('/api/') || e.request.method !== 'GET') return;

  // HTML navigation: stale-while-revalidate the app shell — but ONLY for the
  // SPA root. Other navigations (e.g. a deep-linked /static/*.html page) must
  // go to the network/static handlers below; otherwise every navigation was
  // served the app index, replacing the page the user actually asked for.
  if (e.request.mode === 'navigate' && url.pathname === '/') {
    e.respondWith(
      caches.open(CACHE_NAME).then(async cache => {
        const cached = await cache.match('/');
        const network = fetch(e.request).then(res => {
          if (res && res.ok) cache.put('/', res.clone());
          return res;
        }).catch(() => cached);
        return cached || network;
      })
    );
    return;
  }

  // JS/CSS: network-first — always try the network so code/style edits show up
  // on a normal reload; fall back to cache only when offline.
  if (url.pathname.startsWith('/static/') && /\.(js|css)(\?|$)/.test(url.pathname + url.search)) {
    e.respondWith(
      fetch(e.request).then(res => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(e.request, copy));
        }
        return res;
      }).catch(() => caches.match(e.request))
    );
    return;
  }

  // Other static assets (images, fonts, libs): cache-first with background refresh.
  if (url.pathname.startsWith('/static/')) {
    e.respondWith(
      caches.open(CACHE_NAME).then(async cache => {
        const cached = await cache.match(e.request);
        const fetching = fetch(e.request).then(res => {
          if (res && res.ok) cache.put(e.request, res.clone());
          return res;
        }).catch(() => cached);
        return cached || fetching;
      })
    );
    return;
  }
});
