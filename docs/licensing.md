# Licensing & funding

**tl;dr — Applicant is open source under the MIT License, free to self-host,
with optional donations. There is no paywall, no license key, and no
telemetry.**

## The decision (P4-DEC-1 / P3-3)

The owner decided:

- **DEC-1 — source-available / open source**, not closed-source: the full
  source (engine + front door) is public in this repository, under the
  permissive **MIT License** (see [`LICENSE`](../LICENSE)), not held back
  behind a proprietary/SaaS-only model.
- **Pricing — free / donate, no paywall**: there is no purchase flow, no
  license-key check, no trial-expiry gate, and no metered/seat pricing. This
  simplifies the original P3-3 backlog story (which had scoped a paid-license
  + trial-mode build) down to confirming the existing license plus this doc —
  there is no license-check code to build because there is nothing to unlock.

MIT keeps the project maximally free to use, modify, redistribute, and even
fold into a commercial product, with the single obligation of preserving the
copyright and permission notice. It imposes no copyleft or network-use
obligation on self-hosters or downstream users.

## What this means in practice

- **Free to self-host.** Clone the repo, run the Docker Compose stack (see
  [`docs/overview.md`](overview.md)), and use it. No fee, no seat count, no
  expiring trial.
- **No telemetry, no phone-home license check.** The engine and front door do
  not call out to any Applicant-operated server to validate a license or
  report usage. (Outbound calls the *product itself* makes on the operator's
  behalf — job boards, the operator's chosen LLM provider, SearXNG, etc. — are
  a different thing entirely and are documented in
  [`docs/overview.md`](overview.md) and [`docs/spec/master-spec.md`](spec/master-spec.md).)
- **Open source, permissive.** Under MIT you may use, copy, modify, merge,
  publish, distribute, sublicense, and sell copies, subject only to preserving
  the copyright and permission notice. There is no share-alike or
  source-offer requirement.
- **Optional donations.** If Applicant is useful to you and you'd like to
  support its development, there's a donate link in the [README](../README.md#license--funding).
  It is a placeholder today — **the owner has not yet published a live
  Open Collective / GitHub Sponsors / other donation page**; do not treat any
  URL there as final until the owner fills it in. Donations are optional and
  unlock nothing — the software is identical either way.

## The fork-license check (P2-4)

`workspace/` is a vendored front-door application, folded into this
repository and white-labeled as Applicant's public surface. Before confirming
a license for the combined repository, its license had to be checked for
compatibility — copying an incompatibly-licensed vendored app into the repo
would be a real legal problem, not a paperwork one.

**Finding: no conflict, no license change needed.**

- The **whole repository is MIT** — both the engine's own root
  [`LICENSE`](../LICENSE) (Copyright (c) 2026 kevinhirsch) and the vendored
  front door's **`workspace/LICENSE`** (MIT, Copyright (c) 2025 Applicant
  Contributors, confirmed in `workspace/README.md`'s own "## License"
  section). MIT-over-MIT is the simplest possible case: no license had to
  change to ship the combined work.
- **`workspace/ACKNOWLEDGMENTS.md`** documents the third-party portions
  adapted into the front door: [opencode](https://github.com/anomalyco/opencode)
  (MIT), [llmfit](https://github.com/AlexsJones/llmfit) (MIT), and
  [Tongyi DeepResearch](https://github.com/Alibaba-NLP/DeepResearch)
  (Apache-2.0) — full upstream license texts are preserved verbatim in
  `workspace/licenses/`. All are permissive and impose only notice-preservation
  obligations, which those files satisfy.
- The engine side (`src/applicant/`) depends on an overwhelmingly permissive
  stack (FastAPI, SQLAlchemy, httpx, LangGraph, JobSpy, Apprise, etc., all
  MIT/BSD/Apache-2.0) plus `psycopg` (LGPL-3.0, used as a library — LGPL's
  linking terms don't impose copyleft on the linking application). The full
  ledger is `THIRD_PARTY_LICENSES.md`.
- The one **AGPL-3.0** component in the tree is `PyMuPDF` — optional,
  lazy-imported, used only by the workspace's PDF form-filling feature (per
  `workspace/ACKNOWLEDGMENTS.md`). It is not installed by default and does not
  affect the repository's own MIT license; if an operator chooses to install
  it, AGPL's obligations then apply to *that feature* for *their* deployment.
- Services that are merely **composed via Docker Compose or interoperated
  with over the network** — SearXNG (AGPL-3.0), ntfy (Apache-2.0/GPL-2.0),
  Radicale (GPL-3.0), Dovecot, isync/mbsync (GPL-2.0), tmux (ISC), OpenSSH —
  are not linked or distributed as part of this codebase, so their licenses
  don't impose obligations on Applicant's own license choice. See
  `workspace/ACKNOWLEDGMENTS.md` for the full list.

**Honest gap:** this is a good-faith compatibility read grounded in the
license texts and grants actually on disk (MIT-over-MIT, the permissive
attribution obligations, LGPL's linking exception), not a substitute for a
lawyer's opinion. If the owner is distributing this commercially at scale, or
a downstream user has a jurisdiction-specific concern, get that reviewed by
counsel before relying on this note. Nothing found here required a license
change or blocks shipping this repository as MIT-licensed open source as
currently composed.

## See also

- [`LICENSE`](../LICENSE) — the MIT License text.
- [`THIRD_PARTY_LICENSES.md`](../THIRD_PARTY_LICENSES.md) — the engine-side
  vendored/dependency license ledger.
- [`workspace/ACKNOWLEDGMENTS.md`](../workspace/ACKNOWLEDGMENTS.md) — the
  front door's third-party attribution ledger (adapted code, bundled
  libraries, fonts, Python dependencies, and companion services).
- [`docs/backlog/road-to-market.md`](backlog/road-to-market.md) — P4-DEC-1,
  P3-3, and P2-4 record this decision and its DoD status.
