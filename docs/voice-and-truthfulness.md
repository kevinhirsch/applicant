# Voice & Truthfulness

Source: master spec **FR-RESUME-2** (truthfulness hard guardrail), **FR-RESUME-4** (output fidelity), **FR-RESUME-5** (non-AI-looking), **FR-ANSWER-1**, **NFR-TRUTH-1**. Seeded from `kevinhirsch/ai-job-search` `.claude/skills/job-application-assistant/03-writing-style.md` and the `CLAUDE.md` **Verification Checklist** (consulted per §5.1: "almost a line-for-line statement of our guardrails"). Those origins are cited inline below.

These rules apply to **every revision pass** of every generated artifact (resume, cover letter, screening answer) and are enforced before any artifact reaches review, and again before submission.

## 1. Truthfulness (hard guardrail) — FR-RESUME-2, NFR-TRUTH-1

Adaptation **reframes, reorders, re-emphasizes, and re-terms real experience** and surfaces relevant true history. It **never fabricates** qualifications, titles, dates, or skills. The fit-scorer is a **coverage check, not a target to game**.

### The interview-backtrack test
*(from 03-writing-style.md rule 6, "Reframe emphasis, not substance")*

> Could the candidate comfortably explain this bullet in an interview without backtracking? If they'd have to say "well, what I actually meant was..." then it's too far.

- **OK:** reordering experience to lead with what's most relevant; natural synonyms for the target domain; emphasizing one aspect of a broad role.
- **Flag it:** combining academic + industry experience into a single claim implying it was all industry; describing work in the posting's specific terminology when the actual work was adjacent but not the same.
- **Never:** claiming experience the candidate doesn't have; implying they worked in a domain they haven't.

When a bullet falls in the "flag it" zone, surface it to the user with the reason and a keep/soften/drop choice. If the experience-match score is below 50, warn before drafting that extensive reframing would be needed. (This routes into the interactive review/revision loop, FR-RESUME-8.)

### Unverified company claims
Every company-specific statement (partnerships, product names, technology, expansions) must be **independently verified** via web research before inclusion; do not trust reviewer-agent research at face value. If a claim cannot be verified, rephrase generally or omit it. *(03-writing-style.md rule 5; CLAUDE.md Verification Checklist "Factual accuracy".)*

## 2. No em-dashes — deterministic post-filter — FR-RESUME-5

**Em dashes are forbidden** and are **stripped/replaced by a deterministic post-filter, not left to the model.** En-dashes used as em are normalized. Use commas, periods, or restructure the sentence instead. *(03-writing-style.md rule 1.)* Because the model cannot be trusted to obey this reliably, the filter is a code-level pass that runs on every generated/revised artifact (FR-RESUME-5).

## 3. Banned-phrase list (concept) — FR-RESUME-5

A **UI-editable banned-phrase list** constrains generation. Seed entries (clichés/filler from 03-writing-style.md rule 2): "I am passionate about", "I believe I would be a great fit", "leverage my skills", "hit the ground running", "drive results", "synergies". Plus: no generic buzzwords without concrete backing; no apologetic/overly-humble language; every claim supported by a specific example or fact. The list is user-editable and applied on every revision pass.

## 4. Voice-matching to the user's corpus — FR-RESUME-5

Generation is constrained to **sound like the user**, matched to the user's own resume corpus (and onboarding voice material). Tone targets (from 03-writing-style.md): warm but direct; conversational professional; first person, active voice; demonstrate, don't state. Voice-matching runs on **every revision pass** so revisions don't drift back toward generic AI phrasing.

> Caveat (FR-RESUME-5, §11): no tool can *guarantee* defeating AI-text detectors. The **mandatory human review/revision loop is the safeguard**, not the filters alone.

## 5. Compile-and-visually-inspect fidelity check — FR-RESUME-4

*(from the CLAUDE.md Verification Checklist, "Compiled PDF verification (MANDATORY — never skip)"; adopted per §5.1 for our docx→PDF and LaTeX paths.)*

A **fidelity check guards every artifact before review**. "**Looks fine in source is not acceptable**" — LaTeX/docx page-break decisions are unpredictable, so the rendered output must be compiled and visually inspected. The check MUST verify:

- The artifact **compiles** (LaTeX: xelatex/lualatex + fontspec, fonts embedded; docx: docx→PDF with embedded fonts or docx upload, per FR-RESUME-4). Use **lualatex** where fontawesome5 font-expansion errors appear, **xelatex** where fontspec is required (CLAUDE.md gotchas).
- **Exact page count** — e.g., a CV is exactly 2 pages, a cover letter exactly 1 page; not one more, not one fewer.
- **No orphaned section/entry titles** — a job/education title must never sit at the bottom of a page with its bullets spilling over (use `\needspace`/`\enlargethispage` per CLAUDE.md).
- **Fonts render correctly** (depends on the FR-FONT subsystem providing the build environment's fonts), and bullet/body fonts match.
- **Content fidelity: nothing dropped** in conversion (FR-RESUME-3).

Overflow or any failure surfaces as a **soft error** (FR-RESUME-3); the artifact does not proceed to review until the fidelity check passes.

## 6. Where these rules run

- During **MATERIAL_PREP** (§7): generation applies em-dash filter + banned-phrase list + voice-matching + truthfulness, then the fidelity check.
- During **MATERIAL_REVIEW** (§7, FR-RESUME-8): every revision re-applies all of the above before re-rendering the redline.
- Before **submission**: nothing submits without user approval (FR-RESUME-8, FR-ANSWER-1).

## Origin citations

- `kevinhirsch/ai-job-search` `.claude/skills/job-application-assistant/03-writing-style.md` — em-dash ban, banned-phrase/cliché list, tone, interview-backtrack test, unverified-company-claims rule.
- `kevinhirsch/ai-job-search` `CLAUDE.md` Verification Checklist — factual accuracy, render-and-inspect fidelity, exact page count, no orphaned titles, "looks fine in source is not acceptable," lualatex/xelatex gotchas.
- Master spec §5.1 directs reuse of these as our guardrails for the docx→PDF and LaTeX paths.
