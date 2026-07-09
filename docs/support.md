# Getting support (P5-1, "Support machinery")

Applicant is self-hosted — when something goes wrong, it's happening on your
own machine, and the fastest path to a fix is giving whoever's helping you
(a GitHub issue, or the community chat) enough to reproduce it **without ever
handing over a secret**.

## 1. Redacted diagnostic bundle

Run this on the host running Applicant (the same box where you ran
`scripts/install.sh` / `scripts/proxmox-deploy.sh`):

```bash
bash scripts/diagnostic-bundle.sh
```

It collects, into one `.tar.gz`:

- `version.txt` — git commit + Docker/Compose versions
- `compose-ps.txt` — which services are up (`docker compose ps`)
- `env-sanitized.txt` — your deploy config with every secret-bearing value
  redacted (key names are kept, so a helper can see *which* settings are on
  without ever seeing a password, token, or key)
- `logs/<service>.log` — recent logs per service, secret-scrubbed
- `health.txt` — a best-effort health check
- `MANIFEST.txt` — exactly what landed in the bundle and what was skipped (and
  why) on this run — nothing is silently dropped

**Redaction happens inside the script itself** — there is no flag to turn it
off, and no caller input can opt a value back into the plaintext output. It
uses a denylist of secret-bearing keys (`POSTGRES_PASSWORD`,
`APPLICANT_INTERNAL_TOKEN`, `LLM_API_KEY`, `DATABASE_URL`, and anything with
`password`/`secret`/`token`/`api_key`/`credential` in its name) plus
value-pattern scrubbing (provider API keys, GitHub/GitLab/Slack/npm tokens,
JWTs, PEM private keys, and `user:pass@host`-shaped URLs) so a secret is
caught even under a key name nobody anticipated. See
`scripts/lib/diagnostic_redact.py` for the exact rules, and
`tests/unit/test_diagnostic_bundle_script.py` /
`tests/unit/test_diagnostic_redact.py` for the tests that prove known secrets
never survive into the bundle.

Even so — **skim the archive yourself** before attaching it anywhere public.
Automated redaction is a strong safety net, not a substitute for a human
glance.

This needs to run on the deploy host (it shells out to `docker compose`); it
is not reachable from inside the app itself, since the containers it inspects
don't have Docker access. Settings → System (the honest health panel) surfaces
this same command so it's discoverable without reading this page first.

Prefer `docs/backup-restore.md`'s "Download my data" export if what you need
is your *own* application data (résumé, documents, activity) rather than a
support-facing snapshot of the deployment itself — this bundle is deliberately
the opposite of that: deploy/ops diagnostics, not personal job-search data.

## 2. Issue templates

Opening a GitHub issue offers three forms (`.github/ISSUE_TEMPLATE/`):

- **Bug report** — something isn't working right.
- **Feature request** — something you wish it did.
- **Support question** — you're stuck and want help (not sure if it's a bug?
  this one's fine too).

All three ask for the diagnostic bundle above, and all three say plainly:
never paste secrets. `.github/ISSUE_TEMPLATE/config.yml` is the chooser
shown when opening a new issue.

## 3. Community chat

> **Owner action required.** The line below is a **placeholder** —
> `https://example.invalid/applicant-community-placeholder` is a
> guaranteed-not-real URL (RFC 2606 reserved), not a real invite. Before
> pointing real users at this doc or the issue-template chooser, the project
> owner needs to:
>
> 1. Stand up an actual community space (a Discord server or a lightweight
>    forum — Discourse, GitHub Discussions, whatever fits).
> 2. Replace the placeholder URL **in both places it appears**:
>    `docs/support.md` (this file) and
>    `.github/ISSUE_TEMPLATE/config.yml`'s `contact_links` entry.
> 3. Remove this callout once that's done.
>
> This repo does not invent or ship a real invite link on the owner's behalf —
> that's a real community the owner has to actually create and moderate.

Community chat: `https://example.invalid/applicant-community-placeholder`
*(placeholder — see the callout above)*.

## 4. What to expect

There's no SLA — this is a self-hosted, small-team project. A clear repro
(ideally with the diagnostic bundle attached) is the single biggest thing
that speeds up a response.
