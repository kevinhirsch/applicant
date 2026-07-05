"""Résumé <-> job-posting keyword match scorer (product-gaps backlog #23).

Pure, deterministic, extractive — **no LLM, no IO**. Given the tailored résumé
text and the target posting text, this rule produces a plain-language "match
score" plus the keywords the résumé already covers and the highest-signal
keywords it is missing, so the redline/review surface can show something like
"Match score: 78/100 — you cover React, Python, AWS; consider adding:
Kubernetes, GraphQL".

This is a DIFFERENT signal from :mod:`applicant.core.rules.ats_match_rate`
(FR-PREFILL-2/6): that rule measures **form-fill quality** (fields actually
filled vs detected during a live pre-fill walk). This rule measures **keyword
coverage** between two free-text documents and never touches a browser/DOM.

Algorithm, entirely deterministic:

1. Extract candidate keyword terms from the posting text:
   (a) any term from a curated ~150-entry set of common hard skills / tools /
       certifications / methodologies (:data:`KNOWN_SKILL_TERMS`) that
       appears in the posting (highest signal — checked first), then
   (b) a fallback of multi-word capitalized phrases and other notable
       capitalized nouns pulled straight out of the posting text (lower
       signal, catches domain terms the curated set does not know about).
2. Normalize case, dedupe (case-insensitive, first occurrence wins), and cap
   the candidate pool so a long posting cannot dilute the score.
3. For every candidate term, check case-insensitive, word-boundary presence
   in the résumé text.
4. ``score = round(100 * matched / max(1, total_candidates))``, clamped to
   [0, 100]. ``matched`` / ``missing`` are returned in signal-priority order
   (curated hits first), each capped to keep the UI list readable.

Empty/tiny inputs degrade to a zero score and empty lists rather than raising.
"""

from __future__ import annotations

import functools
import re

# === curated hard-skill / tool / certification / methodology terms =========
# A ~150-term heuristic set of the terms postings and résumés most commonly
# share. This is a deliberately maintainable HEURISTIC, not an ontology —
# extend it over time rather than trying to make it exhaustive.
KNOWN_SKILL_TERMS: tuple[str, ...] = (
    # languages
    "Python", "JavaScript", "TypeScript", "Java", "C++", "C#", "Go", "Golang",
    "Rust", "Ruby", "PHP", "Swift", "Kotlin", "Scala", "MATLAB", "Perl",
    "SQL", "NoSQL", "Bash", "PowerShell", "HTML", "CSS", "Objective-C",
    "Elixir", "Haskell", "Dart",
    # frameworks / libraries
    "React", "Angular", "Vue", "Vue.js", "Next.js", "Node.js", "Express",
    "Django", "Flask", "FastAPI", "Spring", "Spring Boot", ".NET", "Rails",
    "TensorFlow", "PyTorch", "Keras", "scikit-learn", "Pandas", "NumPy",
    "jQuery", "Redux", "GraphQL", "REST", "gRPC", "Bootstrap", "Tailwind",
    "Svelte", "Laravel",
    # data / ml / ai
    "Machine Learning", "Deep Learning", "Natural Language Processing", "NLP",
    "Computer Vision", "Data Science", "Data Engineering", "ETL",
    "Artificial Intelligence", "LLM", "Generative AI", "Big Data", "Spark",
    "Hadoop", "Kafka", "Airflow", "dbt", "Snowflake", "Databricks",
    "Tableau", "Power BI", "Looker", "Data Analysis", "Data Visualization",
    "Statistics", "A/B Testing",
    # databases
    "PostgreSQL", "MySQL", "MongoDB", "Redis", "Elasticsearch", "SQLite",
    "DynamoDB", "Cassandra", "Oracle", "MariaDB", "BigQuery", "Neo4j",
    # cloud / infra
    "AWS", "Azure", "GCP", "Google Cloud", "Kubernetes", "Docker",
    "Terraform", "Ansible", "Jenkins", "CI/CD", "DevOps", "Linux",
    "Serverless", "Lambda", "CloudFormation", "Helm", "Nginx", "Prometheus",
    "Grafana", "Istio", "OpenShift", "Puppet", "Chef",
    # tools / platforms
    "Git", "GitHub", "GitLab", "Bitbucket", "Jira", "Confluence", "Slack",
    "Figma", "Sketch", "Postman", "Salesforce", "HubSpot", "SAP", "Workday",
    "ServiceNow", "Zendesk", "Notion", "Asana", "Trello", "Miro",
    # methodologies
    "Agile", "Scrum", "Kanban", "Lean", "Waterfall", "Six Sigma", "SDLC",
    "TDD", "BDD", "Pair Programming", "Continuous Integration",
    "Continuous Deployment", "Design Thinking", "OKRs", "KPIs",
    # certifications
    "PMP", "CPA", "CFA", "CISSP", "CISA", "AWS Certified", "PMI-ACP",
    "Scrum Master", "CSM", "Six Sigma Black Belt", "ITIL", "SHRM-CP",
    "CompTIA", "CCNA",
    # security
    "Cybersecurity", "Penetration Testing", "SOC 2", "GDPR", "HIPAA",
    "OAuth", "SSO", "Encryption", "Firewall", "Zero Trust", "PCI DSS",
    # roles / disciplines
    "Product Management", "Project Management", "UX Design", "UI Design",
    "Business Analysis", "Quality Assurance", "QA", "Technical Writing",
    "Sales", "Marketing", "SEO", "SEM", "Content Marketing",
    "Digital Marketing", "Customer Success", "Account Management",
    "Business Development", "Recruiting", "Human Resources",
    "Supply Chain", "Operations", "Finance", "Accounting", "Legal",
    "Underwriting", "Procurement",
    # workplace / general terms with real signal
    "Stakeholder Management", "Cross-functional", "Leadership",
    "Public Speaking", "Negotiation", "Budget Management",
    "Vendor Management", "Risk Management", "Change Management",
    "Excel", "PowerPoint", "Word", "Google Analytics", "Google Ads",
    "API", "Microservices", "Mobile Development",
    "iOS", "Android", "Full Stack", "Backend", "Frontend", "Automation",
    "Machine Vision", "Robotics", "Embedded Systems", "Blockchain",
)

# Words to drop from the fallback (multi-word-phrase / notable-noun) pass so
# generic sentence filler does not masquerade as a keyword. Lowercase.
_FALLBACK_STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "this", "that", "these", "those", "we", "our", "you", "your",
        "is", "are", "was", "were", "will", "and", "for", "with", "from",
        "have", "has", "had", "not", "all", "any", "who", "what", "when",
        "where", "why", "how", "job", "role", "team", "company", "position",
        "experience", "skills", "skill", "requirements", "requirement",
        "responsibilities", "responsibility", "qualifications",
        "qualification", "benefits", "about", "apply", "join", "looking",
        "work", "years", "year", "ability", "strong", "excellent", "good",
        "great", "new", "must", "please", "including", "such", "etc", "also",
        "other", "more", "most", "may", "can", "should", "would", "if", "as",
        "an", "a", "in", "on", "at", "to", "of", "or", "it", "be", "us",
        "we're", "we'll", "you'll", "you're", "here", "there", "their",
        "they", "he", "she", "his", "her", "them", "one", "two", "we've",
    }
)

#: Safety cap on the total candidate pool so a very long posting cannot
#: dilute the score into meaninglessness. Curated (high-signal) hits are
#: never dropped by this cap; only the lower-signal fallback pass is capped.
_MAX_CANDIDATES = 40
#: How many matched / missing terms the UI surface gets back (readable list).
_MAX_RETURNED = 12

_MULTI_WORD_PHRASE_RE = re.compile(
    r"\b(?:[A-Z][a-zA-Z0-9+/#.\-]*\s+){1,3}[A-Z][a-zA-Z0-9+/#.\-]*\b"
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|[\n\r]+")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+/#.\-]*")


@functools.lru_cache(maxsize=512)
def _term_pattern(term: str) -> re.Pattern[str]:
    """A case-insensitive, "word"-boundary regex for ``term``.

    Uses alnum-boundary lookarounds (not ``\\b``) so terms containing
    punctuation the standard ``\\b`` mishandles (``C++``, ``C#``, ``.NET``,
    ``CI/CD``) still match as whole terms rather than as a raw substring.

    Memoized (perf): ``term`` -> compiled pattern is a pure, deterministic
    mapping, and ``compute_jd_match`` calls this for every one of the ~150
    ``KNOWN_SKILL_TERMS`` PLUS every candidate term (against both the posting
    and the résumé text) on EVERY call — recompiling the same fixed set of
    regexes from scratch each time despite them never changing. 512 comfortably
    covers the curated lexicon plus per-call fallback candidates.
    """
    escaped = re.escape(term)
    return re.compile(rf"(?<![A-Za-z0-9])(?:{escaped})(?![A-Za-z0-9])", re.IGNORECASE)


def _contains_term(text: str, term: str) -> bool:
    return bool(_term_pattern(term).search(text))


def _dedupe_preserve_order(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in terms:
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def _fallback_candidates(posting_text: str) -> list[str]:
    """Multi-word capitalized phrases + notable single nouns (lower signal).

    Purely extractive: multi-word Title-Case runs (e.g. "Product Management",
    "Customer Relationship Management") plus standalone capitalized words
    (excluding a sentence's first word, where capitalization is just
    grammar) that are not common filler. No POS tagging / NLP model — a
    cheap heuristic fallback for when the curated set finds nothing.
    """
    candidates: list[str] = []
    for phrase in _MULTI_WORD_PHRASE_RE.findall(posting_text):
        cleaned = phrase.strip()
        words = cleaned.split()
        if len(words) < 2:
            continue
        if all(w.lower() in _FALLBACK_STOPWORDS for w in words):
            continue
        candidates.append(cleaned)

    for sentence in _SENTENCE_SPLIT_RE.split(posting_text):
        words = _WORD_RE.findall(sentence)
        for word in words[1:]:  # skip the sentence-initial word (grammar, not signal)
            if len(word) < 4:
                continue
            if not word[0].isupper():
                continue
            if word.lower() in _FALLBACK_STOPWORDS:
                continue
            candidates.append(word)

    return _dedupe_preserve_order(candidates)


def _candidate_terms(posting_text: str) -> list[str]:
    """The ranked, deduped, capped candidate keyword pool for a posting."""
    if not posting_text or not posting_text.strip():
        return []
    curated = [t for t in KNOWN_SKILL_TERMS if _contains_term(posting_text, t)]
    curated = _dedupe_preserve_order(curated)
    remaining = max(0, _MAX_CANDIDATES - len(curated))
    fallback = _fallback_candidates(posting_text)[:remaining] if remaining else []
    # Curated hits are highest-signal and always kept; fallback only fills the
    # remaining slots up to the cap, and never duplicates a curated hit.
    curated_lower = {t.lower() for t in curated}
    fallback = [t for t in fallback if t.lower() not in curated_lower]
    return (curated + fallback)[:_MAX_CANDIDATES] if curated else fallback[:_MAX_CANDIDATES]


def compute_jd_match(resume_text: str, posting_text: str) -> dict:
    """Score how well ``resume_text`` covers the keywords in ``posting_text``.

    Returns ``{"score": int 0-100, "matched": [str], "missing": [str]}``.
    ``matched`` / ``missing`` are capped at :data:`_MAX_RETURNED` entries each,
    ordered highest-signal first (curated hard-skill terms before the
    capitalized-phrase fallback). Degrades gracefully on empty/tiny inputs —
    never raises.
    """
    posting_text = posting_text or ""
    resume_text = resume_text or ""
    candidates = _candidate_terms(posting_text)
    total = len(candidates)
    if total == 0:
        return {"score": 0, "matched": [], "missing": []}

    matched: list[str] = []
    missing: list[str] = []
    if resume_text.strip():
        for term in candidates:
            if _contains_term(resume_text, term):
                matched.append(term)
            else:
                missing.append(term)
    else:
        missing = list(candidates)

    score = round(100 * len(matched) / max(1, total))
    score = max(0, min(100, score))
    return {
        "score": score,
        "matched": matched[:_MAX_RETURNED],
        "missing": missing[:_MAX_RETURNED],
    }
