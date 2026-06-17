"""Batch F SECURITY fixes — fail-before/pass-after regression tests.

Each test cites the specific bug it pins:

1. Stored XSS in the digest email (untrusted scraped data rendered unescaped).
2. Path traversal in the base-resume upload (arbitrary file write).
3. Unbounded file uploads (memory DoS) on resume + font endpoints.
4. XML entity-expansion (billion-laughs) DoS on docx parse + RSS parse.
5. Live-session token minted for arbitrary/unknown session ids.
6. LaTeX content injection into the compiled .tex.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.app.main import create_app
from applicant.application.services.digest_service import DigestService
from applicant.application.services.scoring_service import ScoringService
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, JobPostingId, new_id


# ====================================================================== #1
def test_digest_email_escapes_xss_and_neutralizes_javascript_href():
    """#1: a malicious scraped title/url must not survive into the email HTML."""
    storage = InMemoryStorage()
    embedding = LocalEmbedding()
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    storage.postings.add(
        JobPosting(
            id=JobPostingId(new_id()),
            campaign_id=cid,
            title="<script>alert(1)</script>",
            company="<img src=x onerror=alert(2)>",
            source_url="javascript:alert(1)",
            work_mode="remote",
            description="python",
            source_key="jobspy:indeed",
        )
    )
    storage.commit()
    scoring = ScoringService(storage, llm=None, embedding=embedding, threshold=0)
    digest = DigestService(storage, AppriseNotifier(), scoring)
    crit = SearchCriteria(campaign_id=cid, titles=("engineer",), keywords=("python",))

    html = digest.render_email(cid, crit)["html"]

    # No raw script tag and no javascript: scheme survive into the rendered body.
    assert "<script>alert(1)</script>" not in html
    assert "javascript:" not in html.lower()
    # The escaped form is present instead (proves the value was rendered, escaped).
    assert "&lt;script&gt;" in html
    # The neutralized anchor falls back to a harmless href.
    assert "href='#'" in html


# ====================================================================== #2/#3
@pytest.fixture
def client(tmp_path):
    from applicant.app.config import Settings

    settings = Settings(FONTS_DIR=str(tmp_path / "fonts"))
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def _configure_llm(client) -> None:
    r = client.post(
        "/api/setup/llm",
        json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
    )
    assert r.status_code == 204


def test_base_resume_upload_path_is_contained(tmp_path):
    """#2: a traversal campaign_id+suffix can never resolve outside uploads.

    Exercises the exact path the handler now builds for ``dest`` from the raw
    path-param. Pre-fix this used ``uploads / f"{campaign_id}{suffix}"`` with no
    sanitization, so ``../../../../tmp/pwned`` escaped the uploads dir
    (arbitrary file write). Post-fix the value is sanitized to a flat segment and
    the resolved parent must equal the uploads root.
    """
    from fastapi import HTTPException

    from applicant.app.routers.onboarding import _safe_dest

    uploads = tmp_path / "applicant_uploads"
    uploads.mkdir()

    # A traversal campaign_id is either rejected (400) or flattened to stay inside.
    try:
        dest = _safe_dest(uploads, "../../../../tmp/pwned_batch_f.txt")
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        assert dest.resolve().parent == uploads.resolve()
        assert "pwned_batch_f" in dest.name  # contained, single flat segment
        # And it is not the escape target on disk.
        assert dest.resolve() != (tmp_path.parent / "tmp" / "pwned_batch_f.txt").resolve()


def test_base_resume_upload_rejects_oversize(client, monkeypatch):
    """#3: an over-limit resume upload is rejected (413), not buffered/written."""
    from applicant.app.routers import onboarding

    _configure_llm(client)
    monkeypatch.setattr(onboarding, "MAX_RESUME_UPLOAD_BYTES", 1024)
    cid = client.post("/api/campaigns", json={"name": "C"}).json()["id"]

    big = io.BytesIO(b"A" * 4096)
    r = client.post(
        f"/api/onboarding/{cid}/base-resume",
        files={"file": ("resume.txt", big, "text/plain")},
    )
    assert r.status_code == 413


def test_font_install_rejects_oversize(client, monkeypatch):
    """#3: an over-limit font upload is rejected (413)."""
    from applicant.app.routers import fonts

    _configure_llm(client)
    monkeypatch.setattr(fonts, "MAX_FONT_UPLOAD_BYTES", 1024)

    big = io.BytesIO(b"\x00" * 4096)
    r = client.post(
        "/api/fonts/install",
        data={"name": "Inconsolata"},
        files={"file": ("Inconsolata.ttf", big, "font/ttf")},
    )
    assert r.status_code == 413


def test_font_detect_rejects_oversize(client, monkeypatch):
    """#3: an over-limit detect upload is rejected (413)."""
    from applicant.app.routers import fonts

    _configure_llm(client)
    monkeypatch.setattr(fonts, "MAX_FONT_UPLOAD_BYTES", 1024)

    big = io.BytesIO(b"A" * 4096)
    r = client.post(
        "/api/fonts/detect",
        files={"file": ("resume.tex", big, "text/plain")},
    )
    assert r.status_code == 413


# ====================================================================== #4
_ENTITY_BOMB = (
    '<?xml version="1.0"?>'
    "<!DOCTYPE lolz ["
    '<!ENTITY lol "lol">'
    '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
    '<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">'
    "]>"
    "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>"
    "<w:body><w:p><w:r><w:t>&lol3;</w:t></w:r></w:p></w:body></w:document>"
)


def test_docx_parse_does_not_expand_entities():
    """#4: a docx document.xml entity bomb does not expand (text stays unexpanded)."""
    from applicant.adapters.resume_tailoring.docx_tailor import DocxTailor

    tailor = DocxTailor()
    text = tailor.extract_text(_ENTITY_BOMB)
    # Entity not resolved -> the recursive "lol" payload never materializes.
    assert "lollol" not in text


def test_rss_parse_rejects_entity_bomb():
    """#4: the RSS parser refuses/neutralizes an entity-expansion bomb."""
    from applicant.adapters.discovery.clients import _parse_feed_xml

    feed = (
        '<?xml version="1.0"?>'
        "<!DOCTYPE rss ["
        '<!ENTITY lol "lol">'
        '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;">'
        "]>"
        "<rss><channel><item><title>&lol2;</title></item></channel></rss>"
    )
    raised = False
    text = ""
    try:
        root = _parse_feed_xml(feed)
        text = "".join(e.text or "" for e in root.iter())
    except Exception:
        raised = True
    # Either the parse is refused, or it does not expand the entity.
    assert raised or "lollol" not in text


# ====================================================================== #5
def test_view_url_unknown_session_404(client):
    """#5: minting a live-session token for an unknown session id is refused."""
    from tests.conftest import open_automated_work_gate

    open_automated_work_gate(client)
    r = client.get("/api/remote/sessions/sbx-doesnotexist/view-url")
    assert r.status_code == 404


def test_view_url_provisioned_session_still_works(client):
    """#5: a real provisioned session still mints its URL (no regression)."""
    from tests.conftest import open_automated_work_gate

    open_automated_work_gate(client)
    sid = client.post(
        "/api/remote/sessions", json={"application_id": new_id()}
    ).json()["session_id"]
    r = client.get(f"/api/remote/sessions/{sid}/view-url")
    assert r.status_code == 200
    assert r.json()["view_url"]


def test_takeover_unknown_session_404(client):
    """#5: authorizing takeover on an unknown session id is refused."""
    from tests.conftest import open_automated_work_gate

    open_automated_work_gate(client)
    r = client.post("/api/remote/sessions/sbx-doesnotexist/takeover")
    assert r.status_code == 404


# ====================================================================== #6
def test_latex_edit_source_escapes_injected_content():
    """#6: substituted CONTENT with TeX specials is escaped in the emitted source."""
    from applicant.adapters.resume_tailoring.latex_tailor import LatexTailor

    tailor = LatexTailor()
    out = tailor.edit_source(
        "\\section{Skills}\nPLACEHOLDER",
        {"PLACEHOLDER": "\\input{/etc/passwd} 100% & more"},
    )
    # The dangerous control sequence / specials are escaped, not live TeX.
    assert "\\input{/etc/passwd}" not in out
    assert "\\%" in out
    assert "\\&" in out
    assert "\\textbackslash{}" in out
