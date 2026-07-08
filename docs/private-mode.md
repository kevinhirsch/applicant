# Verified local-only private mode

`LLM_LOCAL_ONLY=true` puts the engine in a hard privacy mode with one precise
claim: **your profile and job data never go to a third-party LLM API.** Every
model call the engine makes — digest scoring, résumé/cover-letter tailoring,
screening answers, the résumé parse double-check, chat — runs only against
endpoints on your own box or private network.

This page is the honest contract: what the mode enforces, what it deliberately
does not cover, and how to verify both.

## What the mode enforces

- **Non-private model tiers are refused, not deprioritized.** The tier ladder
  is filtered at its single construction point (`SetupService.build_ladder`),
  so no consumer — boot, runtime reconfiguration, or the smart-routing
  reorder — can ever walk a cloud rung while the mode is on. (Smart routing
  only reorders existing tiers, so it cannot reintroduce one.)
- **"Configured" means "a model the mode allows."** The LLM-configured gate
  and setup status apply the *same* filter as the ladder: with only cloud
  tiers stored, the engine reports the model as not configured and automated
  work stays gated — it never silently falls back to a cloud endpoint. The
  stored tier config is not rewritten; turning the mode off restores it.
- **Private means private.** A host passes only if it is loopback
  (`127.0.0.1`, `::1`), a private/link-local IP range (`10/8`, `172.16/12`,
  `192.168/16`, `169.254/16`), `localhost` or a private-use name
  (`.local`, `.lan`, `.internal`, `.home.arpa`), or a single-label hostname
  (a Docker service like `http://ollama:11434`). A public domain does not
  pass by containing a friendly word — `https://ollama.example.com` is
  refused. See `src/applicant/core/rules/private_endpoints.py`.
- **Embeddings are always on-box** (mode or no mode): the engine uses its
  local embedding adapter and the in-stack vector store.

## What still leaves the box (by design)

Private mode is about the *model path*. The product's job is applying to
jobs, which inherently talks to the outside world:

- **Discovery queries** go to job boards (via the in-stack SearXNG and the
  scraping path). Search terms derive from your criteria — that is the
  product working, not a leak, but be aware of it.
- **The automation browser** visits ATS sites and submits exactly the
  material you approved at review.
- **Opt-in notification fan-out** (Discord webhook, email, push) sends the
  notification text to the channel you configured. Skip configuring them and
  everything stays in the in-app portal.
- **Deploy tooling** (image pulls, `update.sh` git sync) reaches its usual
  sources.

## How to run it

1. Serve a model privately — any of:
   - Ollama / llama.cpp / vLLM / SGLang on the same box
     (`http://127.0.0.1:11434`, `http://localhost:8000`, …);
   - the same, on another machine on your LAN (`http://192.168.x.y:11434`);
   - the in-compose service name if you add one (`http://ollama:11434`);
   - the workspace's own local-model serving (Cookbook), which stays on the
     internal Docker network.
2. Set `LLM_LOCAL_ONLY=true` in the engine's environment (compose: the `api`
   service) and restart it.
3. Connect the model in the setup wizard / Settings exactly as usual.

Verify: `GET /api/setup/status` (through the front door) reports
`"llm_local_only": true`, and `llm_configured` flips to true only once a
private-host tier exists. With a cloud-only config it stays false — that is
the mode refusing, out loud.

## The executable assertion

```bash
DATABASE_URL='postgresql+psycopg://x:x@127.0.0.1:1/none' \
  uv run pytest -q tests/unit/test_local_only_private_mode.py
```

Pins: the host classifier's accept/refuse table (including the
`ollama.example.com` trap), cloud tiers dropped from the ladder while private
tiers survive in order, the gate/status refusing on a cloud-only config while
the mode is on, byte-identical behavior while it is off, and the status
surfacing. If that suite goes red, this page's claim is no longer citable.
