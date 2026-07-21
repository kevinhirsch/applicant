# Panel Security + Robustness Audit — Findings for Hardening Wave

**Audit date:** 2026-07-21
**Scope:** 39 HTML panels (a0-applicant/webui/*.html) + 41 API proxies (a0-applicant/api/*.py)

## Summary

| Severity | Count |
|----------|-------|
| **HIGH** | 4 |
| **MEDIUM** | 3 |
| **LOW** | 3 |
| **Total** | 10 |

---

## 🔴 HIGH Severity

### 1. XSS via `x-html` — conversion panel preview result
- **File:** `a0-applicant/webui/conversion.html` line 60
- **Issue:** `x-html="previewResult"` renders API response data as raw HTML. The `preview()` function builds HTML strings from `d.artifact_available`, `d.page_count`, `d.fidelity_ok`, and `d.notes` via template literals without sanitization.
- **Snippet:** `<div class="preview-info" x-show="previewResult" x-html="previewResult"></div>`
- **Suggested fix:** Replace `x-html` with `x-text` for plain text display, or sanitize HTML before setting `previewResult` using DOMPurify or a safe innerText-only approach. If rich formatting is needed, use a CSP-safe markup renderer.

### 2. XSS via `x-html` — documents provenance data
- **File:** `a0-applicant/webui/documents.html` line 118
- **Issue:** `x-html="provenanceData || '<em>Loading…</em>'"` renders engine-response data as HTML. The `toggleProvenance()` function sets `provenanceData` directly from `r.data.provenance`, `r.data.html`, or `r.data.text` (assumed to be HTML).
- **Snippet:** `<div class="provenance-content" x-show="provenanceOpen === (doc.id || doc.document_id)" x-html="provenanceData || '<em>Loading…</em>'"></div>`
- **Suggested fix:** Use `x-text` for display and guard with a safe HTML serializer, or sanitize provenance data before rendering. Add a note that the engine response is assumed HTML.

### 3. XSS via `x-html` — documents submission snapshot
- **File:** `a0-applicant/webui/documents.html` line 131
- **Issue:** `x-html="snapshotData"` renders engine-response data as raw HTML. The `loadSnapshot()` function sets `snapshotData` from `r.data.snapshot`, `r.data.html`, or `r.data.text` without sanitization.
- **Snippet:** `<div x-html="snapshotData"></div>`
- **Suggested fix:** Replace with `x-text` and render adjacent raw HTML through a safe mechanism, or sanitize snapshot data with DOMPurify before display.

### 4. XSS via `x-html` — model endpoints models list
- **File:** `a0-applicant/webui/model_endpoints.html` line 85
- **Issue:** `x-html="item._modelsHtml || ''"` renders HTML built from model names via template strings. The `loadModels()` function constructs `item._modelsHtml` by mapping model data: `models.map(m => \`<div class="model-item">${m.name || m.id || m}</div>\`).join("")` — model names from the engine are injected without escaping.
- **Snippet:** `<div class="models-list" x-show="item._showModels && item._models" x-html="item._modelsHtml || ''"></div>`
- **Suggested fix:** Build a structured array of model objects instead of raw HTML strings, then render with `x-text` per-model or use a safe template approach (e.g., Alpine `x-for` over a models array).

---

## 🟡 MEDIUM Severity

### 5. API key exposed in frontend component state — model endpoints
- **File:** `a0-applicant/webui/model_endpoints.html` line 50
- **Issue:** `formApiKey` is stored in Alpine component state and sent via `callJsonApi` in plaintext. While the input is `type="password"`, the key remains in JavaScript memory and is forwarded to the engine proxy in cleartext.
- **Snippet:** `<input type="password" x-model="formApiKey" placeholder="API key (optional)…">`
- **Suggested fix:** Keep as password field but ensure the key is never exposed in UI elements, logs, or stored in session storage. Consider server-side proxied storage with masked display.

### 6. Captcha API key stored in plaintext form state — automation panel
- **File:** `a0-applicant/webui/automation.html` lines 252–253
- **Issue:** `captcha_api_key` is stored in plaintext Alpine form state (`x-model="fields.captcha_api_key"`) as a `type="text"` input (not password-masked).
- **Snippet:** `<input type="text" x-model="fields.captcha_api_key" />`
- **Suggested fix:** Change input `type` to `"password"` to mask the key on screen, and ensure it is not persisted in frontend state longer than needed.

### 7. Missing input validation on URL/API key forwarding — model endpoints proxy
- **File:** `a0-applicant/api/model_endpoints.py` lines 27–36 (dispatch function `add` and `test` actions)
- **Issue:** The `add` and `test` actions forward `base_url` and `api_key` from user input to the engine without validating URL format, protocol, or key format. An attacker-controlled or malformed URL could cause SSRF, open redirect, or injection against the engine.
- **Snippet:** The dispatch function forwards `base_url` and `api_key` directly from the request input.
- **Suggested fix:** Validate `base_url` against a URL scheme whitelist (e.g., `http://`, `https://`), check for valid host format, and reject obviously malformed URLs before forwarding.

---

## 🔵 LOW Severity

### 8. Missing form field validation — model endpoints add form
- **File:** `a0-applicant/webui/model_endpoints.html` line 153
- **Issue:** `addEndpoint()` only checks `if (!this.formBaseUrl.trim()) return;` but does not validate URL format at all in the frontend.
- **Suggested fix:** Add frontend URL format validation (e.g., simple regex or URL parse) to catch malformed URLs before a round-trip.

### 9. Missing form field validation — easy apply posting ID
- **File:** `a0-applicant/webui/easy_apply.html` line 39
- **Issue:** The `postingId` input submits without format validation beyond trimming.
- **Suggested fix:** Add basic format validation (e.g., non-empty, alphanumeric with allowed delimiters) before submitting.

### 10. hello.py uses non-standard response envelope
- **File:** `a0-applicant/api/hello.py`
- **Issue:** Returns `{"success": True, "message": ..., "plugin": ...}` instead of the standard `{"ok": True, "status": 200, "data": ...}` envelope used by all other proxies.
- **Suggested fix:** Align with the standard envelope pattern: return `{"ok": True, "status": 200, "data": {"message": "Hello from Applicant 2.0 plugin!", "plugin": "applicant"}}`.

---

## ✅ Categories with NO Findings

### Unsafe URLs (href/src/window.open/location from response data)
- **Result: NO FINDINGS.** All `window.openModal` calls use hardcoded, static argument paths (e.g., `'/plugins/applicant/webui/help.html?surface=X'`). No template literals construct URLs from response data. No `location.href`, `location.assign`, or `window.location` assignments found in any panel.

### TODO/FIXME/HACK/XXX markers
- **Result: NO FINDINGS.** No actual `TODO`, `FIXME`, `HACK`, or `XXX` comments found in any HTML or API Python file. All grep hits were false positives from `<template>` HTML tag content.

### console.log of secrets/PII
- **Result: NO FINDINGS.** No `console.log`, `console.dir`, or `console.table` calls found in any HTML panel. The vault panel includes a comment warning: "SECURITY: secrets pass straight through; NEVER log or print them."

### innerHTML, insertAdjacentHTML, v-html usage
- **Result: NO FINDINGS.** No usage of `innerHTML = `, `insertAdjacentHTML`, or `v-html` found in any panel.

### API proxy exception raises (crash instead of error envelope)
- **Result: NO FINDINGS.** All 37 files with `_forward` functions use the standardized try-except pattern returning error envelopes. 0 files use `raise` for error paths. 4 files without `_forward` (`base_resume.py`, `hello.py`, `help.py`, `__init__.py`) are either single-purpose or have their own proper error handling.

### Missing action->400 fallback in API dispatch functions
- **Result: NO FINDINGS.** All 37 API files with `dispatch` functions end with a proper `return {"ok": False, "status": 400, "error": f"unknown {name} action {action!r}"}` fallback. `features.py` is a single-purpose proxy without action routing (valid).

---

*Audit performed by automated code analysis. All findings were verified by reading source files.*
