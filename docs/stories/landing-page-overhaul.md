# User Story — Landing Page Overhaul (the daily command center)

**Story ID:** APP-LP-1
**Status:** Ready for build (pending Kevin sign-off)
**Created:** 2026-08-10

---

## Story

**As** Kevin, using Applicant every day to run his job search,
**I want** the first page I hit when I open Applicant to be a streamlined command center that surfaces exactly what needs my attention — in priority order — and lets me act on it in place,
**So that** in the first 30 seconds each morning I know what to do and can do it, without hunting through panels or wading past clutter that has nothing to do with getting a job.

---

## Priority order (Kevin's ranking — the page is laid out to reflect this)

1. **Review & act on drafts** — the review queue is the hero of the page.
2. **Approve new matches** — quickly turn fresh high-fit roles into drafts.
3. **Pipeline + progress** — see the funnel and today's momentum at a glance.
4. **Direct the agent** — a chat box to steer the search.

## Gadgets (all four; inline / act-in-place)

- **Pending Reviews** — count + list of drafts awaiting review (resume variant / cover letter / screening / work-auth answers), grouped per role; **Review / Approve / Decline** in place.
- **Top New Matches** — the freshest, highest-fit roles (viability score + one-line "why it fits"); **Draft this / Skip** one-click.
- **Pipeline Funnel** — Discovered → Scored → Drafted → Submitted → Interview counts for the active campaign.
- **Daily Progress** — today's drafted/submitted, streak, and target (throughput) attainment.

## Keep / Cut

- **Keep:** the chat box (top, for directing the agent); a **notifications-connect** affordance (email/Discord so alerts reach Kevin); the **System Resources** monitor.
- **Cut:** upstream Agent-Zero cards — **"Your AI accounts"** (Codex/Copilot/Grok) and **"Connect Channels"** (WhatsApp/Telegram/Email marketing cards). Irrelevant to a job search.

## Interaction model

**Act inline + keep chat.** Do the work (approve / review / draft / skip) directly on the landing page; keep the chat box at the top for directing the agent. Deep links into full panels remain available for anything that needs more room (e.g., editing a full resume), but the common actions do not require leaving the page.

---

## DoR — Definition of Ready

- [x] Requirements captured with Kevin (this story).
- [ ] **Fast data endpoints exist for every gadget (<2s each).** Each gadget reads a dedicated, cheap endpoint — NOT the heavy digest rebuild. (Depends on the digest/read-path perf fix, currently under investigation — APP-PERF-1.) A gadget must never block the page.
- [ ] Inline action endpoints confirmed working: approve/decline a draft; draft/skip a posting.
- [x] Theme tokens available (`a0-applicant/webui/applicant-theme.css`); light + dark.
- [x] Branding assets available (Applicant wordmark in overlay).

## DoD — Definition of Done

- [ ] New landing page replaces the current root view and **loads in < 2s** on the 10.0.1.11 instance.
- [ ] All four gadgets render with **real data** for the active campaign, in the priority order above.
- [ ] Inline actions work and update the view without a full reload (approve/decline draft; draft/skip match).
- [ ] Upstream clutter removed (AI-accounts, Connect-Channels marketing cards); notifications-connect + System Resources retained; chat box retained at top.
- [ ] No "Agent Zero" branding anywhere on the page.
- [ ] Passes the visual monkey-crawl: **zero console/render errors**, responsive, theme-consistent (light + dark).
- [ ] **Visually tight + meets good HIG** (Apple Human Interface Guidelines — Kevin runs a macOS-Tahoe-styled desktop): clear visual hierarchy; consistent spacing on a grid (uniform paddings/margins/gaps via theme tokens, no ad-hoc values); purposeful whitespace (not cramped, not sparse); everything aligned (no ragged edges, consistent card widths); consistent component styling; a real typographic scale; adequate contrast + comfortable click targets; restraint.
- [ ] **Zoomed screenshot inspection of EVERY region** (not just a full-page shot): header/logo, chat box, each of the 4 gadgets individually, the gaps/dividers between sections, and the page edges — each inspected close-up (device_scale_factor 2) for pixel-level defects (misalignment, inconsistent padding, clipped/overflowing text, uneven spacing, weak contrast, off-grid items). Iterate screenshot→zoom→fix→re-screenshot until **zero visible defects** in the zoomed views, in **both light and dark**. Zoomed screenshots attached for review.
- [ ] Every gadget **degrades gracefully** (skeleton / empty state) if its data source is slow or empty — never hangs the page.
- [ ] **Reuse-first / no redundancy** — each gadget is a THIN VIEW over an EXISTING endpoint/component (the scored Digest data for reviews + matches + score badges; existing status/stats for the funnel + progress), NOT a parallel reimplementation. New code only where nothing exists, and justified. The build report lists what was reused vs added.
- [ ] Fixed **in source** (`a0-webui/` + `a0-applicant/`), committed + pushed, **baked into the image** so a fresh install ships it.
- [ ] **Browser-verified with before/after screenshots.**

## AC — Acceptance Criteria (Given / When / Then)

1. **Layout & speed** — *Given* I open Applicant, *When* the landing page loads, *Then* within 2s I see, top→bottom: chat box → Pending Reviews → Top New Matches → Pipeline Funnel → Daily Progress, populated with my active campaign's real data.
2. **Pending Reviews** — *Given* drafts await review, *When* I view Pending Reviews, *Then* each entry shows role + company + what's ready, and I can Review / Approve / Decline in place; acting updates the list immediately (no full reload).
3. **Top New Matches** — *Given* newly-discovered high-fit roles, *When* I view Top New Matches, *Then* I see the freshest N with score + a one-line why, and "Draft this" / "Skip" act in place and remove the card.
4. **Pipeline & progress** — *Given* campaign activity, *When* I view the funnel + progress, *Then* counts (discovered/scored/drafted/submitted/interview) and today's drafted/submitted vs target are accurate.
5. **Clutter cut** — *Given* the redesign, *When* I inspect the page, *Then* the AI-accounts and Connect-Channels marketing cards are gone; a notifications-connect affordance + System Resources remain; the chat box is at the top.
6. **Graceful degradation** — *Given* a gadget's data source is slow/unavailable, *When* the page loads, *Then* that gadget shows a skeleton/empty state and the rest of the page is fully usable (no hang, no console error).
7. **Brand & QA** — *Given* the page, *When* rendered in light and dark, *Then* no "Agent Zero" branding appears and the visual monkey-crawl reports zero console/render errors.

## Notes / dependencies

- **APP-PERF-1 (digest/read-path perf)** is a hard dependency for the Top-New-Matches gadget's data. The gadget must read a cheap endpoint (stored scores, capped N), not trigger a full digest rebuild.
- Reuse existing engine endpoints where possible (Today pending-actions for reviews; a capped viable-postings read for matches; aggregate counts for the funnel; stats for progress). Add thin cheap endpoints only where a fast one doesn't exist.
- Implementation to be done by a dedicated agent once this story is signed off.
