#!/usr/bin/env python3
"""Applicant docs site generator (P3-4).

Builds a small, static, offline-viewable docs site — Quickstart, FAQ,
Troubleshooting, Security & Privacy — by pulling its content straight out of
the repo's own markdown/scripts/compose files instead of hand-duplicating
prose. That's the whole point: nothing here is written twice, so the site
can't silently drift from the source it's summarizing.

Sources (see the extraction functions below for exactly which section of
each):
  - docs/requirements-and-model-matrix.md  (host requirements table)
  - docker/docker-compose.prod.yml         (the real service list)
  - scripts/install.sh / scripts/proxmox-deploy.sh (quickstart commands)
  - workspace/static/landing.html          (the shipped #faq accordion)
  - docs/known-issues.md                  (the live OPEN defects table)
  - CLAUDE.md                              (the runtime-dependency gotchas)
  - docs/security-review.md                (the security findings table)
  - docs/reverse-proxy-https.md             (the HTTPS checklist)
  - workspace/static/privacy.html          (linked, not duplicated)

No third-party dependencies (stdlib only) so it runs anywhere `python3` runs,
with no network access and no build step — the output is plain HTML you can
open directly or serve with `python -m http.server`.

Usage:
    python scripts/build_docs_site.py [--out docs/site]

Regenerate any time repo docs change; the output directory is not committed
(see .gitignore) — that's what "can't drift" means here: there is no stale
copy to go stale, only a script that reads the live source on every run.
"""
from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GITHUB_REPO_URL = "https://github.com/kevinhirsch/applicant"


# --------------------------------------------------------------------------
# Tiny stdlib-only markdown helpers (deliberately not a full renderer — just
# enough for the plain prose/bullets/tables this repo's docs already use).
# --------------------------------------------------------------------------

def esc(text: str) -> str:
    return html.escape(text, quote=False)


def md_inline(text: str) -> str:
    """Escape then apply the handful of inline markdown forms these docs use."""
    text = esc(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def md_block_to_html(text: str) -> str:
    """Render a plain-prose block: paragraphs plus '- '/'N. ' lists (with
    2+-space-indented wrapped continuation lines, which is how every doc in
    this repo wraps its bullets)."""
    lines = text.strip("\n").split("\n")
    parts: list[str] = []
    para: list[str] = []
    items: list[str] = []
    ordered = False

    def flush_para():
        if para:
            parts.append("<p>" + md_inline(" ".join(line.strip() for line in para)) + "</p>")
            para.clear()

    def flush_list():
        nonlocal ordered
        if items:
            tag = "ol" if ordered else "ul"
            parts.append(f"<{tag}>" + "".join(f"<li>{md_inline(it)}</li>" for it in items) + f"</{tag}>")
            items.clear()
            ordered = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush_para()
            continue
        bullet = re.match(r"^[-*]\s+(.*)", stripped)
        numbered = re.match(r"^\d+\.\s+(.*)", stripped)
        if bullet:
            flush_para()
            items.append(bullet.group(1))
        elif numbered:
            flush_para()
            ordered = True
            items.append(numbered.group(1))
        elif items and (line.startswith("  ") or line.startswith("\t")):
            # continuation of the previous list item
            items[-1] += " " + stripped
        else:
            flush_list()
            para.append(stripped)
    flush_para()
    flush_list()
    return "\n".join(parts)


def extract_section(text: str, heading_pattern: str) -> str:
    """Return the body text between a heading matching heading_pattern and
    the next heading of the same-or-higher level.

    Single chokepoint: every caller passes through strip_spec_jargon here, so
    a docs page can never surface FR-/NFR- spec-ID jargon even if a future
    edit to an internal doc (CLAUDE.md, known-issues.md, ...) reintroduces it
    — binding principle #3 (white-label) applies to this generated site too,
    since it's public-facing output, not an internal doc.
    """
    lines = text.split("\n")
    start = None
    level = None
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s", line)
        if m and re.search(heading_pattern, line):
            start = i + 1
            level = len(m.group(1))
            break
    if start is None:
        return ""
    end = len(lines)
    for j in range(start, len(lines)):
        m = re.match(r"^(#{1,6})\s", lines[j])
        if m and len(m.group(1)) <= level:
            end = j
            break
    return strip_spec_jargon("\n".join(lines[start:end]))


def parse_md_table(section_text: str, id_pattern: str) -> list[list[str]]:
    """Parse a '| a | b | c |' markdown table, returning only data rows whose
    first cell matches id_pattern (so header/separator rows are skipped)."""
    rows = []
    for line in section_text.split("\n"):
        line = line.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells and re.match(id_pattern, cells[0]):
            rows.append(cells)
    return rows


def read(relpath: str) -> str:
    return (REPO_ROOT / relpath).read_text(encoding="utf-8")


# Binding principle #3 (white-label): zero FR-/NFR- spec jargon in any
# user-facing string. Several internal docs (CLAUDE.md in particular) cite
# spec IDs like "(FR-RESUME-3/4)" for engineers; this docs site is public, so
# strip them before they reach a rendered page. Two passes:
#   1. the common form is a whole parenthetical, "(FR-RESUME-3/4)" or
#      "(FR-PREFILL, FR-STEALTH)" — drop the parenthetical (and its leading
#      space) entirely so the surrounding prose reads cleanly;
#   2. then a token sweep for any remaining BARE spec id ("FR-RESUME-3" with
#      no wrapping parens), which the paren pass leaves untouched but which is
#      just as much a white-label violation — collapse the stray whitespace it
#      leaves behind so we don't emit double spaces.
_SPEC_ID_PAREN = re.compile(
    r"\s*\([A-Za-z0-9/,\- ]*\b(?:FR|NFR)-[A-Za-z0-9/-]+[A-Za-z0-9/,\- ]*\)"
)
_SPEC_ID_TOKEN = re.compile(r"\b(?:FR|NFR)-[A-Za-z0-9/-]+")


def strip_spec_jargon(text: str) -> str:
    text = _SPEC_ID_PAREN.sub("", text)
    text = _SPEC_ID_TOKEN.sub("", text)
    # Tidy up the artifacts a bare-token removal can leave (" ,"/doubled
    # interior spaces). Do this PER LINE and preserve each line's LEADING
    # indentation — md_block_to_html detects list-item continuation lines via
    # `line.startswith("  ")`, so collapsing leading whitespace would corrupt
    # the rendering.
    tidied = []
    for line in text.split("\n"):
        indent = line[: len(line) - len(line.lstrip(" \t"))]
        rest = line[len(indent):]
        rest = re.sub(r" +([,.;:])", r"\1", rest)
        rest = re.sub(r"[ \t]{2,}", " ", rest)
        tidied.append(indent + rest)
    return "\n".join(tidied)


# --------------------------------------------------------------------------
# Extractors — one per source doc.
# --------------------------------------------------------------------------

def get_faq_items() -> list[tuple[str, str]]:
    """Pull the shipped landing-page FAQ accordion verbatim (P4-2's #faq).

    Anchored on the real `<section id="faq">...</section>` tags (NOT the
    markdown-heading extract_section helper above, which doesn't apply to
    HTML) so a `<summary>`/`<details>` mention in an unrelated CSS comment
    earlier in the file can't be mistaken for the start of a FAQ entry.
    """
    landing = read("workspace/static/landing.html")
    section_match = re.search(
        r'<section id="faq">(.*?)</section>', landing, re.DOTALL
    )
    if section_match is None:
        # Fail CLOSED. Falling back to the whole page would silently scrape
        # unrelated <summary>/<p> pairs (e.g. a CSS comment or an unrelated
        # <details>), shipping junk as "the FAQ". If the landing page's #faq
        # section moved/renamed, that's a real breakage the generator must
        # surface, not paper over.
        raise RuntimeError(
            'workspace/static/landing.html has no <section id="faq"> — the FAQ '
            "source moved or was renamed; update get_faq_items()."
        )
    pairs = re.findall(
        r"<summary>(.*?)</summary>\s*<p>(.*?)</p>", section_match.group(1), re.DOTALL
    )
    if not pairs:
        raise RuntimeError(
            'workspace/static/landing.html #faq matched no <summary>/<p> pairs '
            "— the accordion markup changed; update get_faq_items()."
        )
    return [(q.strip(), a.strip()) for q, a in pairs]


def get_open_known_issues() -> list[dict]:
    """The live OPEN table from docs/known-issues.md — real, unresolved
    defects, not a hand-copied snapshot."""
    text = read("docs/known-issues.md")
    section = extract_section(text, r"^## OPEN")
    rows = parse_md_table(section, r"^[A-Z]\d+$")
    out = []
    for r in rows:
        if len(r) < 4:
            continue
        out.append(
            {
                "id": r[0],
                "severity": r[1],
                "finding": r[2],
                "where": r[3] if len(r) > 3 else "",
            }
        )
    return out


def get_runtime_gotchas() -> str:
    """The Dockerfile runtime-dependency gotchas straight from the project's
    own CLAUDE.md (single source of truth for these already)."""
    text = read("CLAUDE.md")
    section = extract_section(text, r"^## Runtime dependencies")
    return md_block_to_html(section)


def get_security_findings() -> list[dict]:
    text = read("docs/security-review.md")
    section = extract_section(text, r"^## Summary of findings")
    rows = parse_md_table(section, r"^\d+$")
    out = []
    for r in rows:
        if len(r) < 5:
            continue
        out.append(
            {
                "area": r[1],
                "severity": r[2],
                "finding": r[3],
                "disposition": r[4],
            }
        )
    return out


def get_reverse_proxy_checklist() -> str:
    text = read("docs/reverse-proxy-https.md")
    section = extract_section(text, r"^## Checklist after enabling TLS")
    return md_block_to_html(section)


def get_private_mode_summary() -> str:
    text = read("docs/private-mode.md")
    # First paragraph only — the one-sentence claim, not the whole page.
    section = extract_section(text, r"^# Verified local-only private mode")
    first_para = section.strip().split("\n\n")[0]
    return md_block_to_html(first_para)


def get_install_oneliner() -> str:
    """The advertised curl-pipe-bash one-liner, pulled from install.sh's own
    header comment so the docs command can't drift from what the script
    documents. Fail closed if the shape changes."""
    text = read("scripts/install.sh")
    m = re.search(
        r"bash -c \"\$\(curl -fsSL https://\S+/scripts/install\.sh\)\" -- --apply",
        text,
    )
    if not m:
        raise RuntimeError(
            "scripts/install.sh no longer advertises the curl|bash one-liner in the "
            "expected shape — update get_install_oneliner()."
        )
    return m.group(0)


def get_proxmox_oneliner() -> str:
    text = read("scripts/proxmox-deploy.sh")
    m = re.search(
        r"bash -c \"\$\(curl -fsSL https://\S+/scripts/proxmox-deploy\.sh\)\"",
        text,
    )
    if not m:
        raise RuntimeError(
            "scripts/proxmox-deploy.sh no longer advertises its curl|bash one-liner "
            "in the expected shape — update get_proxmox_oneliner()."
        )
    return m.group(0)


def get_install_modes() -> list[tuple[str, str]]:
    """The install.sh mode flags + descriptions, parsed from the script's own
    `Usage:` help block so the docs stay in lockstep with the real flags."""
    text = read("scripts/install.sh")
    usage = re.search(r"^Usage: install\.sh.*?^EOF", text, re.DOTALL | re.MULTILINE)
    block = usage.group(0) if usage else text
    modes = []
    for line in block.split("\n"):
        m = re.match(r"^\s{2}(--[a-z]+(?:, -[a-z])?)\s{2,}(.+)$", line)
        if m:
            modes.append((m.group(1).strip(), m.group(2).strip()))
    if not modes:
        raise RuntimeError(
            "scripts/install.sh Usage block parsed no `--flag  description` lines "
            "— update get_install_modes()."
        )
    return modes


def get_compose_services() -> list[str]:
    """The real service list straight out of the production compose file —
    if a service is added/removed there, this list changes with it."""
    text = read("docker/docker-compose.prod.yml")
    # Bound the services block by the NEXT top-level key (or EOF), not a
    # hard-coded `volumes:` — a `networks:`/`configs:` block appearing before
    # `volumes:` would otherwise be swallowed and leak non-service names.
    services_block = re.search(
        r"^services:\n(.*?)(?=^[A-Za-z][\w-]*:|\Z)", text, re.DOTALL | re.MULTILINE
    )
    block = services_block.group(1) if services_block else text
    return re.findall(r"^  ([a-zA-Z][a-zA-Z0-9_-]*):\s*$", block, re.MULTILINE)


def get_requirements_baseline_table() -> list[list[str]]:
    text = read("docs/requirements-and-model-matrix.md")
    section = extract_section(text, r"^### 1\.1 Baseline")
    rows = []
    for line in section.split("\n"):
        line = line.strip()
        if line.startswith("|") and line.endswith("|") and "---" not in line:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if cells and cells[0] not in ("", "Minimum", "Recommended (installer default)"):
                rows.append(cells)
    return rows


SERVICE_BLURBS = {
    "applicant-ui": "The public front door (white-labeled workspace). The only service published to the host, on <code>${APP_PORT}</code>.",
    "api": "The engine — internal only, never published to the host. Reached in-network at <code>http://api:8000</code>.",
    "postgres": "The engine's database (profile, applications, campaigns, credentials vault).",
    "searxng": "Self-hosted search backend used for job discovery. Internal only.",
    "chromadb": "Vector store for the front-door's memory/RAG features. Internal only.",
    "ntfy": "Self-hosted push notifications. Internal only unless you put a reverse proxy in front of it.",
    "takeover-desktop": "Optional streamed desktop for live hand-off on CAPTCHA/verification/final-submit steps. Off by default (<code>--profile takeover</code>).",
    "updater": "Powers the in-UI one-click update button. Optional — comment it out to update from the CLI instead.",
}


# --------------------------------------------------------------------------
# Page shell (lifted from the shipped /privacy page's own theme — same dark,
# no-framework, self-contained style, so the docs site looks like it belongs
# to the same product rather than a bolted-on generator output).
# --------------------------------------------------------------------------

NAV_PAGES = [
    ("index.html", "Docs"),
    ("quickstart.html", "Quickstart"),
    ("faq.html", "FAQ"),
    ("troubleshooting.html", "Troubleshooting"),
    ("security-privacy.html", "Security & Privacy"),
]

STYLE = """
  :root {
    --bg: #282c34; --panel: #111; --fg: #9cdef2; --heading: #9cdef2;
    --muted: #6b8a94; --border: #355a66; --accent: #e06c75;
    --green: #50fa7b; --gold: #f0ad4e;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--fg);
    font-family: 'Fira Code', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    line-height: 1.65; -webkit-font-smoothing: antialiased;
  }
  a { color: var(--accent); }
  a:hover { text-decoration: underline; }
  header {
    position: sticky; top: 0; z-index: 5; background: rgba(17,17,17,0.92);
    border-bottom: 1px solid var(--border); backdrop-filter: blur(8px);
  }
  header .row {
    max-width: 860px; margin: 0 auto; padding: 14px 22px;
    display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;
  }
  .brand { display: flex; align-items: center; gap: 8px; font-weight: 700; font-size: 16px; color: var(--heading); }
  header nav a { color: var(--muted); font-size: 13px; font-weight: 500; margin-left: 16px; }
  header nav a:hover, header nav a.active { color: var(--fg); }
  main { max-width: 860px; margin: 0 auto; padding: 36px 22px 80px; }
  h1 { color: var(--heading); font-size: 26px; margin-bottom: 4px; }
  .updated, .sub { color: var(--muted); font-size: 13px; margin-bottom: 28px; }
  h2 { color: var(--heading); font-size: 17px; margin-top: 40px; border-bottom: 1px solid var(--border); padding-bottom: 6px; }
  h3 { color: var(--fg); font-size: 14px; margin-top: 22px; }
  p, li { font-size: 14px; }
  ul, ol { padding-left: 22px; }
  li { margin-bottom: 6px; }
  code { background: #1e2228; border: 1px solid var(--border); border-radius: 4px; padding: 1px 5px; font-size: 12.5px; }
  pre { background: #1e2228; border: 1px solid var(--border); border-radius: 6px; padding: 12px 14px; overflow-x: auto; }
  pre code { border: none; padding: 0; background: none; }
  table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 13px; }
  th, td { border: 1px solid var(--border); padding: 6px 10px; text-align: left; vertical-align: top; }
  th { color: var(--heading); background: #1e2228; }
  .callout {
    border: 1px solid var(--border); border-left: 3px solid var(--accent);
    background: #1e2228; border-radius: 6px; padding: 12px 16px; margin: 16px 0; font-size: 13.5px;
  }
  .card-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin: 20px 0; }
  .card { border: 1px solid var(--border); border-radius: 8px; padding: 16px; background: #1e2228; }
  .card h3 { margin-top: 0; }
  footer {
    max-width: 860px; margin: 0 auto; padding: 24px 22px 60px;
    border-top: 1px solid var(--border); color: var(--muted); font-size: 12.5px;
  }
  footer a { margin-right: 16px; }
  details.faq { border: 1px solid var(--border); border-radius: 6px; margin-bottom: 10px; background: #1e2228; }
  details.faq summary { padding: 12px 16px; cursor: pointer; color: var(--heading); font-weight: 600; font-size: 14px; }
  details.faq p { padding: 0 16px 14px; margin: 0; color: var(--fg); }
"""

BRAND_SVG = (
    '<svg width="20" height="20" viewBox="0 0 32 32" aria-hidden="true">'
    '<path d="M16 2C16 7 11 9 11 14C11 16 9 16 9 13C7 16 6 19 6 21A10 10 0 0 0 26 21'
    'C26 14 19 13 18 4C17 7 15 8 16 11C17 7 16 4 16 2Z" fill="currentColor"/>'
    '<path d="M16 13C16 16 13 17 13 21A3.5 3.5 0 0 0 20 21C20 18 18 17 18 14C17 16 '
    '15 16 16 13Z" fill="currentColor" opacity="0.6"/></svg>'
)


def page_shell(active_file: str, title: str, description: str, body: str) -> str:
    nav_links = []
    for fname, label in NAV_PAGES:
        cls = ' class="active"' if fname == active_file else ""
        nav_links.append(f'<a href="{fname}"{cls}>{label}</a>')
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="description" content="{esc(description)}">
<title>{esc(title)} — Applicant docs</title>
<style>{STYLE}</style>
</head>
<body>
  <header>
    <div class="row">
      <div class="brand">{BRAND_SVG} Applicant docs</div>
      <nav>
        {''.join(nav_links)}
        <a href="{GITHUB_REPO_URL}" target="_blank" rel="noopener noreferrer">GitHub</a>
      </nav>
    </div>
  </header>
  <main>
{body}
  </main>
  <footer>
    <span>Generated straight from the repo by
    <code>python scripts/build_docs_site.py</code> — never hand-edited, so it can't
    drift from the source.</span><br><br>
    <a href="{GITHUB_REPO_URL}" target="_blank" rel="noopener noreferrer">Source on GitHub</a>
    <a href="{GITHUB_REPO_URL}/blob/main/docs/overview.md" target="_blank" rel="noopener noreferrer">docs/overview.md</a>
  </footer>
</body>
</html>
"""


# --------------------------------------------------------------------------
# Page builders
# --------------------------------------------------------------------------

def build_index() -> str:
    body = """
    <h1>Applicant — docs</h1>
    <p class="sub">A self-hosted autonomous job-application system. Everything below is
    generated straight from the repo's own docs, scripts, and compose files, so it can't
    drift from what's actually shipped.</p>
    <div class="card-grid">
      <div class="card"><h3><a href="quickstart.html">Quickstart</a></h3>
        <p>Stand up the whole stack with one command.</p></div>
      <div class="card"><h3><a href="faq.html">FAQ</a></h3>
        <p>Straight answers to the questions people actually ask.</p></div>
      <div class="card"><h3><a href="troubleshooting.html">Troubleshooting</a></h3>
        <p>Known issues and the runtime dependencies that must be baked into the image.</p></div>
      <div class="card"><h3><a href="security-privacy.html">Security &amp; Privacy</a></h3>
        <p>What's checked, what's encrypted, and where your data lives.</p></div>
    </div>
    <h2>Not sure where to start?</h2>
    <p>New install: start with <a href="quickstart.html">Quickstart</a>. Something's not
    working: check <a href="troubleshooting.html">Troubleshooting</a> first — most
    surprises are documented there. Questions about what the software does with your
    data: see <a href="security-privacy.html">Security &amp; Privacy</a>.</p>
"""
    return page_shell("index.html", "Docs", "Applicant self-hosted docs: quickstart, FAQ, troubleshooting, security & privacy.", body)


def build_quickstart() -> str:
    req_rows = get_requirements_baseline_table()
    req_table = "<table><thead><tr><th></th><th>Minimum</th><th>Recommended</th></tr></thead><tbody>"
    for row in req_rows:
        if len(row) >= 3:
            req_table += f"<tr><td>{md_inline(row[0])}</td><td>{md_inline(row[1])}</td><td>{md_inline(row[2])}</td></tr>"
    req_table += "</tbody></table>"

    services = get_compose_services()
    services_html = "<ul>"
    for svc in services:
        blurb = SERVICE_BLURBS.get(svc, "See <code>docker/docker-compose.prod.yml</code>.")
        services_html += f"<li><code>{esc(svc)}</code> — {blurb}</li>"
    services_html += "</ul>"

    install_oneliner = get_install_oneliner()
    proxmox_oneliner = get_proxmox_oneliner()
    modes_html = "<ul>"
    for flag, desc in get_install_modes():
        modes_html += f"<li><code>{esc(flag)}</code> — {esc(desc)}</li>"
    modes_html += "</ul>"

    body = f"""
    <h1>Quickstart</h1>
    <p class="updated">The commands and mode list below are extracted from
    <code>scripts/install.sh</code> / <code>scripts/proxmox-deploy.sh</code>, and the
    service list from <code>docker/docker-compose.prod.yml</code> — so they can't drift
    from the real scripts.</p>

    <h2>One-liner install</h2>
    <p>A single script provisions the whole Docker Compose stack with sane, editable
    defaults — no CLI knowledge required beyond running it:</p>
    <pre><code>{esc(install_oneliner)}</code></pre>
    <p>Or, from an existing checkout:</p>
    <pre><code>bash scripts/install.sh --apply</code></pre>
    <p>Modes (the default with no flag is a <strong>safe dry run</strong> — it prints the
    steps it would run and changes nothing):</p>
    {modes_html}

    <h2>Fresh Proxmox VM</h2>
    <p>If you're starting from a bare Proxmox host, this provisions a VM (Ubuntu Server
    24.04 LTS by default) and then runs the installer inside it:</p>
    <pre><code>{esc(proxmox_oneliner)}</code></pre>

    <h2>Host requirements</h2>
    {req_table}

    <h2>What gets started</h2>
    <p>The production compose file (<code>docker/docker-compose.prod.yml</code>) brings
    up these services:</p>
    {services_html}
    <p>Only the front door is ever published to the host — the engine and every other
    service stay on the internal Compose network.</p>

    <h2>Applying an update later</h2>
    <pre><code>bash scripts/update.sh --apply</code></pre>
    <p>Git-syncs, backs up the database, rebuilds, migrates, restarts, then verifies a
    heartbeat — and rolls back automatically if a migration fails.</p>

    <h2>HTTPS</h2>
    <p>The default posture is plain HTTP on a private LAN/VPN. If you want TLS, put a
    reverse proxy in front of the front door — see
    <a href="security-privacy.html#https">Security &amp; Privacy</a>.</p>
"""
    return page_shell("quickstart.html", "Quickstart", "Stand up the Applicant stack in one command.", body)


def build_faq() -> str:
    items = get_faq_items()
    faq_html = ""
    for q, a in items:
        faq_html += f'<details class="faq"><summary>{q}</summary><p>{a}</p></details>\n'
    body = f"""
    <h1>FAQ</h1>
    <p class="updated">Reused verbatim from the shipped landing page's
    <code>#faq</code> section — the same answers, not a second copy that can drift
    from what users are actually shown.</p>
    {faq_html}
"""
    return page_shell("faq.html", "FAQ", "Frequently asked questions about Applicant.", body)


def build_troubleshooting() -> str:
    issues = get_open_known_issues()
    rows_html = ""
    for it in issues:
        rows_html += (
            f"<tr><td><code>{esc(it['id'])}</code></td><td>{md_inline(it['severity'])}</td>"
            f"<td>{md_inline(it['finding'])}</td><td>{md_inline(it['where'])}</td></tr>"
        )
    issues_table = (
        "<table><thead><tr><th>#</th><th>Severity</th><th>Finding</th><th>Where</th></tr></thead>"
        f"<tbody>{rows_html}</tbody></table>"
        if rows_html
        else "<p><em>No open issues found — check docs/known-issues.md.</em></p>"
    )

    gotchas = get_runtime_gotchas()

    body = f"""
    <h1>Troubleshooting</h1>
    <p class="updated">Generated from <code>docs/known-issues.md</code> (the live
    OPEN table) and <code>CLAUDE.md</code>'s runtime-dependency notes.</p>

    <h2>Known open issues</h2>
    <p>Real, currently-unfixed defects tracked in the repo's living bug log. If
    something you're hitting matches one of these, it's a known limitation, not
    something wrong with your deployment.</p>
    {issues_table}

    <h2>Runtime dependencies that must be baked into the image</h2>
    <p>The engine shells out to a few external binaries and detects them at
    runtime — if one is missing, the feature silently degrades instead of erroring
    loudly, so a missing dependency looks like "it just doesn't work" rather than a
    clear error message. These are already baked into the shipped Docker image; this
    matters mainly if you're building your own image or running outside Docker.</p>
    {gotchas}

    <h2>Still stuck?</h2>
    <p>Open an issue on <a href="{GITHUB_REPO_URL}" target="_blank" rel="noopener noreferrer">GitHub</a>
    with your <code>docker compose logs</code> output and, if relevant,
    <code>bash scripts/install.sh --doctor</code>'s report.</p>
"""
    return page_shell("troubleshooting.html", "Troubleshooting", "Known issues and runtime-dependency gotchas.", body)


def build_security_privacy() -> str:
    findings = get_security_findings()
    findings_rows = ""
    for f in findings:
        findings_rows += (
            f"<tr><td>{md_inline(f['area'])}</td><td>{md_inline(f['severity'])}</td>"
            f"<td>{md_inline(f['finding'])}</td><td>{md_inline(f['disposition'])}</td></tr>"
        )
    findings_table = (
        "<table><thead><tr><th>Area</th><th>Severity</th><th>Finding</th><th>Disposition</th></tr></thead>"
        f"<tbody>{findings_rows}</tbody></table>"
        if findings_rows
        else "<p><em>See docs/security-review.md.</em></p>"
    )
    checklist = get_reverse_proxy_checklist()
    private_mode = get_private_mode_summary()

    body = f"""
    <h1>Security &amp; Privacy</h1>
    <p class="updated">Generated from <code>docs/security-review.md</code>,
    <code>docs/reverse-proxy-https.md</code>, and <code>docs/private-mode.md</code>.</p>

    <div class="callout">
      <strong>The full privacy policy</strong> — what's stored, what's encrypted, what
      leaves your deployment and when, and how to export or delete your data — lives in
      the app itself at <a href="/privacy"><code>/privacy</code></a> on your running
      instance (also linked from the app's landing page and Settings). This page summarizes the
      engineering side: the security review and the network-hardening options.
    </div>

    <h2>Security review findings</h2>
    <p>A launch-gate pass over secrets-at-rest, the dependency audit, and an
    authenticated-endpoint sweep. Full detail (how to re-run each check) is in
    <a href="{GITHUB_REPO_URL}/blob/main/docs/security-review.md" target="_blank" rel="noopener noreferrer">docs/security-review.md</a>.</p>
    {findings_table}

    <h2>Local-only private mode</h2>
    {private_mode}
    <p>Full contract: <a href="{GITHUB_REPO_URL}/blob/main/docs/private-mode.md" target="_blank" rel="noopener noreferrer">docs/private-mode.md</a>.</p>

    <h2 id="https">HTTPS via a reverse proxy</h2>
    <p>Applicant's baseline posture is plain HTTP on a private LAN/VPN. If you want TLS
    (a public DNS name, a shared network you don't fully trust, or remote access without
    a VPN), put a reverse proxy — Caddy, Traefik, or nginx all work with no app-side
    code changes — in front of the front door and terminate HTTPS there. Full configs:
    <a href="{GITHUB_REPO_URL}/blob/main/docs/reverse-proxy-https.md" target="_blank" rel="noopener noreferrer">docs/reverse-proxy-https.md</a>.</p>
    <h3>Checklist after enabling TLS</h3>
    {checklist}
"""
    return page_shell("security-privacy.html", "Security & Privacy", "Security review findings and privacy posture.", body)


PAGES = {
    "index.html": build_index,
    "quickstart.html": build_quickstart,
    "faq.html": build_faq,
    "troubleshooting.html": build_troubleshooting,
    "security-privacy.html": build_security_privacy,
}


def build(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    # Clear out any stale generated pages first so a removed/renamed PAGES
    # entry can't leave an orphaned .html behind. Only *.html is swept —
    # anything else a user put in the dir (a .nojekyll, a CNAME, an image)
    # is left untouched.
    for stale in out_dir.glob("*.html"):
        stale.unlink()
    written = []
    for fname, builder in PAGES.items():
        content = builder()
        path = out_dir / fname
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "docs" / "site"),
        help="output directory (default: docs/site)",
    )
    args = parser.parse_args(argv)
    out_dir = Path(args.out)
    written = build(out_dir)
    print(f"Wrote {len(written)} pages to {out_dir}:")
    for p in written:
        try:
            print(f"  {p.relative_to(REPO_ROOT)}")
        except ValueError:
            print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
