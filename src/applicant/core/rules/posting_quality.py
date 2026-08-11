"""Non-posting / posting-quality gate — is this a REAL specific job opening?

Viability scoring (``application/services/scoring_service.py``) and search-based
discovery both currently treat every scraped result as if it were a single job
posting. In practice a title/keyword-driven web search (SearXNG/brave/duckduckgo/
google-cse) returns a mix of:

* real single-employer job postings (a specific opening, one company, one role);
* search-engine/job-board INDEX or SEARCH RESULT pages ("Agile Release Train
  Engineer Jobs, Employment | Indeed", "132 Scrum Master jobs in United States"
  on LinkedIn, a bare ZipRecruiter/Dice.com query URL) that list MANY openings,
  not one;
* articles, comparison posts, and career/certification guides ("Scrum Master vs
  Release Train Engineer", "The Scrum Master Career Path Guide", a Reddit thread,
  a Medium post, scaledagile.com's own SAFe role-glossary pages); and
* recruiter/staffing marketing pages that are not a specific opening either.

A keyword-dense title (e.g. "Agile release train engineer jobs | Dice.com") can
score HIGH on lexical/semantic overlap alone even though it is not a posting at
all — the live calibration run that motivated this module found exactly that:
a Dice.com search-index URL and a "Scrum Master vs Release Train Engineer -
LinkedIn" comparison POST both scored in the 85-95 range.

This module is a PURE, deterministic, no-IO rule: given a posting's title,
source URL, and (optional) description, it decides whether the posting is
plausibly a real, single, specific job opening at all — a signal that is
DIFFERENT from (and prior to) viability ("is this a good match"): a non-posting
scores 0 viability regardless of how well its keywords line up with the
criteria, because there is nothing to apply to.

Detection is layered, cheapest/most-precise first:

1. **Known non-job-board domains** — methodology reference sites, blogs,
   certification-training marketers, and forum/article platforms that never
   host a specific employer's opening (e.g. ``scaledagile.com``'s own SAFe
   glossary, ``reddit.com``, ``medium.com``, ``knowledgehut.com``).
2. **URL structural patterns** — a search/index/query path on a known job
   board (``indeed.com/q-...``, ``dice.com/jobs/q-...``, a LinkedIn ``/jobs/``
   listing that is not ``/jobs/view/...``, a capitalized ``ziprecruiter.com
   /Jobs/...`` query, a recruiter's category-listing page).
3. **Title patterns** — generalizes to aggregator/article domains not in the
   curated lists above: "X vs Y" comparison posts, "<query> Jobs | <Site>"
   aggregator suffixes, a leading result COUNT ("132 ... jobs", "1,000+ ...
   jobs", "Top 158 ... Jobs"), career-guide/explainer phrasing, hourly-rate
   query-style titles ("$51-$83/hr ... Jobs"), and "Jobs Near Me"/"Now Hiring"
   marketing phrasing.
4. **Description boilerplate** — a captured "description" that is actually a
   site's related-jobs sidebar/navigation text (e.g. LinkedIn's "45,261 open
   jobs · ... jobs · ... jobs" block) rather than real posting content, even
   when the URL itself looks like a specific listing.

A title/URL/description that matches NONE of these is treated as a real
posting — this module is a NEGATIVE gate (denylist of known noise patterns),
never a positive allowlist, so it never penalizes a real posting just for
being unfamiliar.

# WIRING (not yet connected — separate workstream owns discovery adapters):
# ``discovery`` (``adapters/discovery/factory.py``/``clients.py``/
# ``jobspy_searxng.py``) and ``scoring_service.py`` should call
# ``is_real_posting(posting.title, posting.source_url, posting.description)``
# and either drop/flag non-postings at ingestion (preferred — never store them)
# or short-circuit ``ScoringService`` to a 0 score with the returned reason
# BEFORE the LLM/embedding pass, so the LLM's own non-posting judgment (see
# ``ScoringService._llm_base``'s ``system_text``) becomes a second, redundant
# line of defense instead of the only one. Left unwired here deliberately: a
# concurrent stealth-discovery workflow owns ``adapters/discovery/*`` and
# ``app/config.py`` in this branch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

# === known non-job-board domains ===========================================
# Sites that NEVER host a specific employer's job opening: methodology
# reference/glossary sites, blogs, certification-training marketers, and
# forum/article platforms. A curated, maintainable denylist (same style as
# ``jd_match.KNOWN_SKILL_TERMS``) — extend as new offenders are observed.
_KNOWN_NON_JOB_DOMAINS: frozenset[str] = frozenset(
    {
        # the SAFe methodology's own site — role/glossary/blog/certification
        # pages read exactly like a job description but are never an opening.
        "scaledagile.com",
        "framework.scaledagile.com",
        # forum / social / long-form article platforms
        "reddit.com",
        "medium.com",
        # agile career-advice / training / certification-marketing blogs
        "knowledgehut.com",
        "iconagility.com",
        "agilemania.com",
        "izenbridge.com",
        "agilentic.com",
        "birjob.com",
        "leanwisdom.com",
        "projectmanagertemplate.com",
        "agilesm.net",
        "gradebuilder.tech",
        "icertglobal.com",
        "simpliaxis.com",
        "skillifysolutions.com",
        "skillbookacademy.com",
        "agileseekers.com",
        "staragile.com",
        "theagileist.com",
    }
)


def _host(url: str) -> str:
    try:
        netloc = urlparse((url or "").strip()).netloc.lower()
    except Exception:
        return ""
    return netloc[4:] if netloc.startswith("www.") else netloc


def _host_matches(host: str, domain: str) -> bool:
    """``host`` is ``domain`` or a subdomain of it."""
    return host == domain or host.endswith("." + domain)


# === URL structural (search/index page) patterns ===========================
# ``(domain, path_regex)`` — a hit means the URL is a search/query/listing
# page on that board, not a specific single opening. Path regexes are anchored
# to the START of the path (``urlparse(...).path``).
_URL_INDEX_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # indeed.com/q-....html and indeed.com/q-....jobs.html are query pages;
    # a real Indeed posting URL never starts with "/q-".
    ("indeed.com", re.compile(r"^/q-", re.IGNORECASE)),
    # dice.com/jobs/q-... is a search-query URL.
    ("dice.com", re.compile(r"^/jobs/q-", re.IGNORECASE)),
    # a capitalized "/Jobs/" path on ZipRecruiter is a title/location QUERY
    # ("/Jobs/Scrum-Master-.../-in-Denver,CO"), never a specific job id.
    ("ziprecruiter.com", re.compile(r"^/Jobs/")),
    # LinkedIn: "/posts/..." and "/pulse/..." are articles; "/jobs/..." that is
    # NOT "/jobs/view/..." is a search-result listing page
    # (e.g. "/jobs/scrum-master-release-train-engineer-jobs").
    ("linkedin.com", re.compile(r"^/posts/", re.IGNORECASE)),
    ("linkedin.com", re.compile(r"^/pulse/", re.IGNORECASE)),
    ("linkedin.com", re.compile(r"^/jobs/(?!view/)", re.IGNORECASE)),
    # recruiter/staffing marketing category pages, not a specific opening.
    ("motionrecruitment.com", re.compile(r"^/tech-jobs/", re.IGNORECASE)),
    ("workgenius.com", re.compile(r"^/find/", re.IGNORECASE)),
)


# === title patterns (generalize to domains not curated above) ==============
#: "Scrum Master vs Release Train Engineer" / "RTE vs Scrum Master" — a
#: comparison article, never a job title.
_TITLE_COMPARISON_RE = re.compile(r"\bvs\.?\b", re.IGNORECASE)
#: Career-guide / explainer phrasing.
_TITLE_GUIDE_RE = re.compile(
    r"career\s+(path|progression|guide)|\bguide\b|\bexplained\b|"
    r"key\s+differences|critical\s+\w+\s+roles|"
    r"roles?\s+and\s+responsibilit(y|ies)|"
    r"understanding\s+(the\s+)?(differences?|roles?)|"
    r"avoiding\s+roles?\s+ambiguity",
    re.IGNORECASE,
)
#: "<query> Jobs | <Site>" / "<query> Jobs, Employment | <Site>" aggregator
#: title suffix — "jobs" as its own word immediately (optionally via
#: ", Employment") followed by a pipe. Deliberately narrow: a pipe AFTER a
#: site name (e.g. "... in Arlington, Virginia | ClearedJobs") does not match
#: because "jobs" there is not the word directly preceding the pipe.
_TITLE_JOBS_PIPE_RE = re.compile(
    r"\bjobs\b\s*(,\s*employment\s*)?\|", re.IGNORECASE
)
#: A leading result COUNT ("132 ... jobs", "1,000+ ... jobs", "Top 158 ...
#: Jobs") — the title of a search-results page, not one posting.
_TITLE_LEADING_COUNT_RE = re.compile(
    r"^\s*(top\s+)?[\d,]{2,}\+?\s+.{0,60}\bjobs\b", re.IGNORECASE
)
#: ZipRecruiter/Indeed-style hourly-rate query titles: "$51-$83/hr Scrum
#: Master Release Train Engineer Jobs (NOW HIRING)".
_TITLE_RATE_JOBS_RE = re.compile(
    r"^\$[\d,]+\s*-\s*\$?[\d,]+\s*/\s*(hr|hour|yr|year)\b.{0,80}\bjobs\b",
    re.IGNORECASE,
)
#: "Jobs Near Me" / "Now Hiring" / "Hiring Now" marketing phrasing on an
#: aggregator results page.
_TITLE_MARKETING_RE = re.compile(
    r"jobs\s+near\s+me|\bnow\s+hiring\b|\bhiring\s+now\b", re.IGNORECASE
)

_TITLE_NON_POSTING_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("comparison-article title (\"X vs Y\")", _TITLE_COMPARISON_RE),
    ("career-guide / explainer title", _TITLE_GUIDE_RE),
    ('aggregator "Jobs | <Site>" title suffix', _TITLE_JOBS_PIPE_RE),
    ("title leads with a result COUNT (search-results page)", _TITLE_LEADING_COUNT_RE),
    ("hourly-rate query-style aggregator title", _TITLE_RATE_JOBS_RE),
    ('"Jobs Near Me" / "Now Hiring" aggregator marketing title', _TITLE_MARKETING_RE),
)

# === description boilerplate (bad-scrape) signal ============================
#: LinkedIn's related-jobs sidebar text ("45,261 open jobs · Delivery Manager
#: ... Technical Program Manager jobs · ...") captured as the "description"
#: instead of real posting content — happens even on a "/jobs/view/..." URL
#: that otherwise looks like a specific listing.
_DESCRIPTION_SIDEBAR_RE = re.compile(r"[\d,]+\s+open\s+jobs\b", re.IGNORECASE)


@dataclass(frozen=True)
class PostingQualityVerdict:
    """Outcome of the non-posting / posting-quality gate."""

    is_posting: bool
    reason: str
    #: Short machine-readable tag for the signal that fired (empty when
    #: ``is_posting`` is True — nothing fired). For observability/debugging,
    #: not for branching on in callers (branch on ``is_posting``).
    signal: str = ""


def check_posting_quality(
    title: str, url: str, description: str = ""
) -> PostingQualityVerdict:
    """Decide whether ``title``/``url``/``description`` describe a REAL,
    single, specific job opening — as opposed to a search/index page, an
    article/comparison/guide, a methodology-reference page, or a captured
    "description" that is really site navigation boilerplate.

    Pure, deterministic, no IO. Returns a :class:`PostingQualityVerdict` with
    ``is_posting=False`` and a plain-language ``reason`` the moment ANY known
    non-posting signal fires; ``is_posting=True`` (with an empty ``reason``
    describing that nothing fired) otherwise. This is a NEGATIVE gate — an
    unfamiliar domain/title with no matching pattern is treated as a real
    posting, never penalized just for being unrecognized.
    """
    title = (title or "").strip()
    url = (url or "").strip()
    description = (description or "").strip()
    host = _host(url)
    path = ""
    if url:
        try:
            path = urlparse(url).path or ""
        except Exception:
            path = ""

    if host:
        for domain in _KNOWN_NON_JOB_DOMAINS:
            if _host_matches(host, domain):
                return PostingQualityVerdict(
                    is_posting=False,
                    reason=(
                        f"{host} is a known non-job-board domain (methodology "
                        "reference, blog, certification marketer, or forum/"
                        "article platform) — never a specific employer opening."
                    ),
                    signal="known_non_job_domain",
                )
        for domain, path_re in _URL_INDEX_PATTERNS:
            if _host_matches(host, domain) and path_re.search(path):
                return PostingQualityVerdict(
                    is_posting=False,
                    reason=(
                        f"URL path {path!r} on {host} matches a search/index/"
                        "listing pattern, not a specific single job posting."
                    ),
                    signal="url_index_pattern",
                )

    if title:
        for reason, pattern in _TITLE_NON_POSTING_PATTERNS:
            if pattern.search(title):
                return PostingQualityVerdict(
                    is_posting=False,
                    reason=f'Title matches a {reason}: "{title}".',
                    signal="title_pattern",
                )

    if description and _DESCRIPTION_SIDEBAR_RE.search(description):
        return PostingQualityVerdict(
            is_posting=False,
            reason=(
                "The captured description looks like site navigation / "
                "related-jobs sidebar boilerplate (\"N open jobs\"), not real "
                "posting content."
            ),
            signal="description_boilerplate",
        )

    return PostingQualityVerdict(
        is_posting=True,
        reason="No aggregator/index/article/boilerplate signal detected.",
    )


def is_real_posting(title: str, url: str, description: str = "") -> bool:
    """Convenience boolean wrapper around :func:`check_posting_quality`.

    Use :func:`check_posting_quality` directly when the ``reason`` is needed
    (e.g. to surface WHY a posting was rejected in logs/rationale).
    """
    return check_posting_quality(title, url, description).is_posting
