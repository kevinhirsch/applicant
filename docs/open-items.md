# Open Items (defaults in place — non-blocking)

Source: master spec §12. Per the engineering mandate, any new ambiguity is recorded here with a **recommended default**, never silently decided. Defaults are in place so none of these block implementation.

## From §12 (verbatim defaults)

| Item | Default / status |
|---|---|
| **Codename** | Placeholder **Applicant**; rename cascades everywhere. |
| **Resume aggressiveness tuning** | Deferred: optimize for job-getting potential now; ship the UI control **grayed out** with a stub spec (FR-RESUME-9). See [dormant-surfaces.md](dormant-surfaces.md) #1. |
| **Resume-fit "badly" threshold** and **viability threshold** | Default **≥70**, configurable (FR-RESUME-7, FR-AGENT-3). |
| **Quiet hours** | Errors always immediate; approvals/digests respect optional quiet hours unless 24/7 (FR-NOTIF-5). |
| **Resolved through v4** | Durable engine = DBOS; deployment = Proxmox VM; per-campaign attribute cloud; resume feedback/revision engine; resume fidelity via font subsystem + embedded-font PDF/docx; full zero-CLI OOBE wizard + in-UI Update button; screening-answer generation with review; pending-actions portal; EEO stored-answers policy; single-campaign MVP-1 with multi-campaign-ready architecture; both credential-banking modes; Workday-ready onboarding; master aggregator in wave one. |

## Newly-discovered ambiguity (recorded per §12)

### Odysseus UI license is AGPLv3, not MIT

- **Ambiguity:** The §5 stack table and §5.1 reference list state the Odysseus UI source is **MIT** and instruct vendoring its `static/` "under MIT with notice preserved" (FR-UI-1). On inspection, the Odysseus UI source is licensed **AGPLv3**, not MIT. The spec's vendoring instruction and the "permissive; preserve Odysseus's MIT notice" caveat in §11 are therefore based on an incorrect license assumption.
- **Recommended default** (consistent with the §11 AGPL guidance — "AGPL deps carry distribution obligations, immaterial for personal self-hosted use; keep private or swap if distributed"):
  - **Vendor Odysseus's UI as an isolated, separately-licensed `frontend/static/` subtree.**
  - **Preserve its LICENSE verbatim** (the actual AGPLv3 text, not an MIT notice).
  - **Document it in `THIRD_PARTY_LICENSES.md`.**
  - **Accept AGPL for the self-hosted deployment**, which is the intended use (personal, self-hosted on the Proxmox VM) where AGPL obligations are immaterial. If the product is ever distributed, either keep the deployment private or swap the UI for a permissive alternative.
- **Status:** **User has authorized vendoring.** Proceed with the isolated, separately-licensed AGPLv3 subtree as above.
- **Spec corrections implied:** where §5 / §5.1 / §11 say Odysseus is MIT and reference an "MIT notice," substitute AGPLv3 and an AGPLv3 LICENSE/THIRD_PARTY_LICENSES.md entry. (The master spec in [spec/master-spec.md](spec/master-spec.md) is preserved verbatim as the source of truth; this correction is recorded here rather than edited into the copy.)
