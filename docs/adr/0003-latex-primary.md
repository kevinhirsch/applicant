# ADR-0003: LaTeX-primary resume engine with docx-XML fallback

**Status:** Accepted (mandated by master spec §3.12 FR-RESUME-3/3a/4, §5, §11).

## Context

The engine must adapt the user's resume per role and produce an artifact that **uploads correctly and looks correct** (FR-RESUME-4), with content fidelity guaranteed and a deterministic redline diff for the interactive add/subtract/free-text revision loop (FR-RESUME-8). The user uploads a base resume as a **docx** and does **not** hand-author `.tex`. The user's own `kevinhirsch/ai-job-search` repo already produces a proven moderncv "banking" template and carries hard-won LaTeX gotchas (lualatex for fontawesome5, xelatex for fontspec, `\needspace`/`\enlargethispage` for page-fit). Design fidelity to a hand-tuned docx cannot be guaranteed by automated conversion.

## Decision

Make the resume renderer **pluggable behind the `ResumeTailoring` port** with two engines selected **per campaign at onboarding** (FR-RESUME-3):

- **LaTeX (primary):** auto-convert the uploaded docx (content extracted; user never writes `.tex`) into the proven moderncv "banking" template; generate variants/revisions by editing the **LaTeX source** (plain text → trivial redline diffing). Output via **xelatex/lualatex + fontspec** with fonts embedded natively (deterministic, no rendering drift).
- **docx (fallback):** if the converted LaTeX look is not accepted, edit the uploaded docx's **OOXML (`document.xml`)** in place — preserving run properties, fonts, layout — anchored to the base XML; output docx→PDF with embedded fonts or docx upload, whichever the ATS accepts.

A **conversion preview & accept/reject gate at onboarding** (FR-RESUME-3a) lets the user choose the engine. Both engines run a **page-fit check** and a **compile-and-visually-inspect fidelity check** before review (FR-RESUME-4). Both depend on the FR-FONT subsystem for build-environment fonts.

## Consequences

- **Positive:** LaTeX gives deterministic, font-embedded output and trivial source-level redline diffing (ideal for FR-RESUME-8); reuses the user's existing moderncv template and LaTeX gotchas (§5.1); content fidelity is guaranteed.
- **Negative / cost:** docx→LaTeX conversion does **not** guarantee a match to the user's exact hand-tuned design — so the **docx fallback is load-bearing** and **genuine use is expected** when the converted look doesn't satisfy the user (that is the safety net working, §11). Two engines to maintain behind one port; the fidelity check ("looks fine in source is not acceptable," exact page count, no orphaned titles) is mandatory on every artifact (see [voice-and-truthfulness.md](../voice-and-truthfulness.md)).
- **Acceptance bar:** "Uploads right and looks right" — design fidelity is the user's judgment via the accept/fallback gate, not an automated guarantee.
