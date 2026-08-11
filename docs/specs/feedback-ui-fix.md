# Work order: per-posting +/- feedback UI in the digest panel

**Branch:** `claude/refactor-agent-zero-applicant-xn7xoc`. Commit locally, **do NOT push**. Minimal change; touch only the files named here.

**Goal:** add a per-posting freeform +/- feedback control to the digest panel that POSTs `{campaign_id, posting_id, sentiment, text}` to the (already-built, deployed) `POST /api/feedback/posting` engine route, which LLM-parses the text into learning signals.

## Endpoint contract (verified)
`POST /api/feedback/posting` (`src/applicant/app/routers/feedback.py`), gated behind `require_llm_configured`.
Request `PostingFeedbackIn`: `{"campaign_id","posting_id","sentiment":"positive|negative","text"}`.
Response: `{"folded":true,"sentiment","likes":[...],"dislikes":[...],"criteria_delta":{...}}`.

## CRITICAL GAP — the proxy does not forward this action yet
Panels never call the engine directly; they call the a0-shell plugin proxy via `callJsonApi("feedback", {...})` → `a0-applicant/api/feedback.py` `dispatch()`, which currently only handles `"history"`, `"freetext"`, `"survey"`. There is NO `"posting"` branch. **You must add it.**

## Ordered build checklist

**1. `a0-applicant/api/feedback.py`** — add a new branch in `dispatch()` right after the `"survey"` block (before the final `return {"ok": False, ...}` fallback):
```python
    if action == "posting":
        body = {
            "campaign_id": cid,
            "posting_id": input.get("posting_id"),
            "sentiment": input.get("sentiment", "positive"),
            "text": input.get("text"),
        }
        return _forward("POST", "/api/feedback/posting", body)
```
(Match the exact `_forward` signature/usage already used by the `"freetext"`/`"survey"` branches in this file.)

**2. `tests/unit/test_az3_feedback_proxy.py`** — add, mirroring `test_freetext_forwards_post_with_body`:
```python
def test_posting_forwards_post_with_body(self, mod):
    seen = {}
    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 200, "data": {}}
    with patch.object(mod, "_forward", fake):
        mod.dispatch({
            "action": "posting", "campaign_id": "c1", "posting_id": "p1",
            "sentiment": "negative", "text": "too much travel",
        })
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/feedback/posting"
    assert seen["body"] == {"campaign_id": "c1", "posting_id": "p1", "sentiment": "negative", "text": "too much travel"}
```
Run it green.

**3. `a0-applicant/webui/digest.html` — Alpine state.** In `digestPanel()` state (near `declineReasons: {}`), add:
```js
campaignId: "__system__",
postingFeedback: {},   // { [posting_id]: { text, sentiment } }
feedbackBusy: {},
feedbackResult: {},
feedbackError: {},
```
In `load()`, after `this.rows = ...`, add: `this.campaignId = (r.data && r.data.campaign_id) || "__system__";`
(The digest payload has a top-level `campaign_id`; rows themselves only carry `posting_id`, never `application_id` — use `row.posting_id` everywhere below. Do NOT use `row.application_id` — it is `undefined` on the real row shape; that's a pre-existing latent bug in the existing approve/decline controls, OUT OF SCOPE, leave it alone.)

**4. `a0-applicant/webui/digest.html` — handler** (add after `decline`, before `recap`):
```js
async submitPostingFeedback(postingId, sentiment) {
  const draft = this.postingFeedback[postingId] || {};
  const text = (draft.text || "").trim();
  if (!text) return;
  this.feedbackBusy = { ...this.feedbackBusy, [postingId]: true };
  this.feedbackError[postingId] = "";
  const r = await callJsonApi("feedback", {
    action: "posting", campaign_id: this.campaignId,
    posting_id: postingId, sentiment: sentiment, text: text,
  });
  this.feedbackBusy = { ...this.feedbackBusy, [postingId]: false };
  if (!r || !r.ok) {
    this.feedbackError[postingId] = (r && r.error) || "Feedback failed to save.";
    this.feedbackResult[postingId] = null;
  } else {
    this.feedbackResult[postingId] = r.data || {};
    this.postingFeedback[postingId] = { text: "", sentiment: null };
  }
}
```
(POSTs through the `"feedback"` proxy, NOT `"digest"`.)

**5. `a0-applicant/webui/digest.html` — markup.** Insert inside the per-row `<template>`, inside `.item .info`, right AFTER the `.why` div and before the `</div>` that closes `.info` (keeps it full-width under the "why" text, separate from the `.actions` approve/decline buttons so it doesn't collide with the existing decline-row input):
```html
<div class="feedback-row" x-show="!feedbackResult[row.posting_id]">
  <input type="text" class="feedback-input"
         x-model="(postingFeedback[row.posting_id] = postingFeedback[row.posting_id] || {text:'',sentiment:null}).text"
         placeholder="What do you think of this one?"
         :disabled="feedbackBusy[row.posting_id]">
  <button class="btn fb-btn" title="Like"
          @click="submitPostingFeedback(row.posting_id, 'positive')"
          :disabled="feedbackBusy[row.posting_id] || !((postingFeedback[row.posting_id]||{}).text||'').trim()">👍</button>
  <button class="btn fb-btn" title="Dislike"
          @click="submitPostingFeedback(row.posting_id, 'negative')"
          :disabled="feedbackBusy[row.posting_id] || !((postingFeedback[row.posting_id]||{}).text||'').trim()">👎</button>
</div>
<div class="feedback-err" x-show="feedbackError[row.posting_id]" x-text="feedbackError[row.posting_id]"></div>
<div class="feedback-confirm" x-show="feedbackResult[row.posting_id]">
  ✓ Feedback saved<template x-if="(feedbackResult[row.posting_id].likes||[]).length"><span> · likes: <span x-text="feedbackResult[row.posting_id].likes.join(', ')"></span></span></template><template x-if="(feedbackResult[row.posting_id].dislikes||[]).length"><span> · dislikes: <span x-text="feedbackResult[row.posting_id].dislikes.join(', ')"></span></span></template>
</div>
```

**6. `a0-applicant/webui/digest.html` — theming.** Extend the existing `<style>` block (scoped under `.adigest`, `var(--color-x, fallback)` tokens only — NEVER hardcoded light colors, NEVER body/html). `--color-success-*`/`--color-danger-*` fallbacks below match the real values already defined in the shared theme:
```css
.adigest .feedback-row{display:flex;gap:4px;align-items:center;margin-top:6px}
.adigest .feedback-row input{flex:1;min-width:0;padding:3px 6px;border-radius:6px;border:1px solid var(--color-border,#d8e0e6);background:var(--color-background,#fff);color:var(--color-text);font:inherit;font-size:.75rem}
.adigest .fb-btn{padding:3px 8px;font-size:.85rem;line-height:1}
.adigest .feedback-err{background:var(--color-danger-bg,#fdecea);color:var(--color-danger-text,#9b1c1c);border-radius:6px;padding:4px 8px;font-size:.72rem;margin-top:4px}
.adigest .feedback-confirm{background:var(--color-success-bg,#e8f8ef);color:var(--color-success-text,#1a7a3a);border-radius:6px;padding:4px 8px;font-size:.72rem;margin-top:4px}
```

**7. `tests/unit/test_az2_digest_panel.py`** — add to `TestDigestPanel`:
```python
def test_posting_feedback_wired(self, html):
    assert 'callJsonApi("feedback",' in html
    assert 'action: "posting"' in html
    assert 'posting_id:' in html and 'sentiment:' in html
```
Run the whole file green.

**8. Verify + commit.** Run the two unit test files (green). Then ONE commit on the branch (no push):
`feat(ui): per-posting freeform +/- feedback in digest, LLM-parsed into learning [FR-FB-2]`
Report exact files changed and note: digest.html + feedback.py proxy are static plugin files (hot-swappable into /a0/plugins/applicant); no engine (api) rebuild needed since the /api/feedback/posting route is already deployed.
