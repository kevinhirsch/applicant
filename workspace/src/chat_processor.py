# src/chat_processor.py
import logging
import math
import re
import threading
import time
from collections import Counter
from typing import List, Dict, Any, Optional, Tuple
from src.chat_helpers import extract_urls
from src.youtube_handler import is_youtube_url
from src.search import comprehensive_web_search, fetch_webpage_content
from src.prompt_security import UNTRUSTED_CONTEXT_POLICY, untrusted_context_message
# The one canonical identity (see src/applicant_identity.py). Reused — never
# re-described — so plain chat, the agent loop, and scheduled tasks all present
# as the SAME single agent.
from src.applicant_identity import APPLICANT_IDENTITY

logger = logging.getLogger(__name__)

# Default identity for plain chat mode (no custom character/preset). A user's
# preset/character prompt takes precedence over this when one is set.
# (APPLICANT_IDENTITY is imported above; kept as the plain-chat default.)

# ── Onboarding-gap awareness (mention-when-relevant) ──
#
# In plain chat, Applicant should KNOW which onboarding sections the user still
# hasn't filled in — but raise them only when the conversation actually touches
# them, never as a per-turn nag. Mapping engine section codes → plain labels:
_SECTION_LABELS = {
    "identity": "identity",
    "work_authorization": "work authorization",
    "location": "location",
    "target_roles": "target roles",
    "compensation": "compensation",
    "work_history": "work history",
    "education": "education",
    "references": "references",
    "key_attributes": "key attributes",
    "eeo": "optional EEO disclosures",
    "base_resume": "base résumé",
    "campaign_criteria": "campaign criteria",
}

# Per-session TTL cache of the onboarding-gap note. build_context_preface runs on
# EVERY chat turn, so we must NOT hit the engine each time. Key = owner; value =
# (expires_at, note_or_None). ``note is None`` is a real, cached answer ("nothing
# to mention" — onboarding complete / no campaign / engine down) so a degraded or
# finished engine is hit at most once per TTL, not per message.
_GAP_NOTE_TTL_SECONDS = 300.0
_gap_note_cache: Dict[str, Tuple[float, Optional[str]]] = {}
_gap_note_lock = threading.Lock()


def _run_engine_coro(coro):
    """Run an async ApplicantEngineClient coroutine to completion from sync code.

    build_context_preface is synchronous but is called from inside the async
    chat route (a running event loop), so ``asyncio.run`` here would raise. Run
    the coroutine on its own loop in a worker thread instead — short-lived and
    only reached on a cache miss (≤ once per TTL per user).
    """
    import asyncio

    result: list = []
    error: list = []

    def _worker():
        try:
            result.append(asyncio.run(coro))
        except BaseException as exc:  # noqa: BLE001 - degrade silently, see caller
            error.append(exc)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join()
    if error:
        raise error[0]
    return result[0] if result else None


def _fetch_onboarding_gap_note(owner: Optional[str]) -> Optional[str]:
    """Build the gap-awareness system note for ``owner``, or ``None`` if there is
    nothing to say (onboarding complete, no campaign, or the engine is unreachable).

    Uses only EXISTING ApplicantEngineClient methods (``setup_status``,
    ``list_campaigns``, ``onboarding_state``). Never raises — any failure degrades
    to ``None`` (inject nothing).
    """
    try:
        from src.applicant_engine import ApplicantEngineClient

        async def _gather():
            async with ApplicantEngineClient() as engine:
                # Fast exit when the whole intake is already done.
                try:
                    status = await engine.setup_status()
                    if isinstance(status, dict) and status.get("onboarding_complete"):
                        return None
                except Exception:
                    # setup_status is a best-effort fast-path; fall through to the
                    # per-campaign check rather than failing the whole note.
                    pass

                campaigns = await engine.list_campaigns()
                if not (isinstance(campaigns, list) and campaigns):
                    return None
                first = campaigns[0]
                cid = first.get("id") if isinstance(first, dict) else None
                if not cid:
                    return None

                state = await engine.onboarding_state(str(cid))
                if not isinstance(state, dict):
                    return None
                if state.get("complete"):
                    return None
                missing = state.get("missing_sections") or []
                labels = [
                    _SECTION_LABELS.get(code, code.replace("_", " "))
                    for code in missing
                    if isinstance(code, str)
                ]
                if not labels:
                    return None
                return (
                    "Onboarding note (for your awareness — do NOT bring this up "
                    "unprompted every turn): the user has not yet finished setting "
                    "up these parts of their profile: "
                    + ", ".join(labels)
                    + ". Mention a missing item ONLY when it is directly relevant to "
                    "what the user is asking about right now (for example, they ask "
                    "about something that depends on it), and offer to help finish it. "
                    "Otherwise just answer their question normally and stay silent "
                    "about setup."
                )

        return _run_engine_coro(_gather())
    except Exception as exc:  # noqa: BLE001 - degrade silently
        logger.debug("Onboarding-gap note unavailable: %s", exc)
        return None


def _onboarding_gap_note(owner: Optional[str]) -> Optional[str]:
    """TTL-cached wrapper around :func:`_fetch_onboarding_gap_note` (per owner)."""
    key = owner or ""
    now = time.time()
    with _gap_note_lock:
        cached = _gap_note_cache.get(key)
        if cached and cached[0] > now:
            return cached[1]
    note = _fetch_onboarding_gap_note(owner)
    with _gap_note_lock:
        _gap_note_cache[key] = (now + _GAP_NOTE_TTL_SECONDS, note)
    return note

# ── Stopwords & tokenizer ──

_STOPWORDS = frozenset(
    "a an the is am are was were be been being have has had do does did "
    "will would shall should can could may might must need ought dare "
    "i me my mine we us our ours you your yours he him his she her hers "
    "it its they them their theirs this that these those "
    "and but or nor not no so if then else than too also very "
    "in on at to for of by with from up out about into over after "
    "what when where which who whom how why all each every some any "
    "just very really actually like well also still already even "
    "oh ok okay yes yeah hey hi hello thanks thank please sorry "
    "much more most own other another such only same here there "
    "because while during before until since through between both "
    "few many several some none nothing something anything everything "
    "get got make made go going went been come came take took "
    "know think want let say tell give see look find way thing "
    "don doesn didn won wouldn couldn shouldn wasn weren isn aren haven hasn "
    "don't doesn't didn't won't wouldn't couldn't shouldn't "
    "it's i'm i've i'll i'd you're you've you'll he's she's we're we've they're they've "
    "that's there's here's what's who's how's let's can't".split()
)

def _content_tokens(text: str) -> list:
    """Extract meaningful content words: no stopwords, min 3 chars, lowercase."""
    words = re.findall(r'[a-z0-9]+(?:[-_][a-z0-9]+)*', text.lower())
    return [w for w in words if len(w) >= 3 and w not in _STOPWORDS]


class ChatProcessor:
    def __init__(self, memory_manager, personal_docs_manager, memory_vector=None, skills_manager=None):
        self.memory_manager = memory_manager
        self.personal_docs_manager = personal_docs_manager
        self.memory_vector = memory_vector
        self.skills_manager = skills_manager

    # Minimum similarity score for RAG results to be injected
    RAG_SIMILARITY_THRESHOLD = 0.35

    def _hybrid_retrieve(self, message: str, mem_entries: list, k: int = 5) -> list:
        """Retrieve memories relevant to the message.

        Uses BM25-style keyword scoring + optional vector similarity.
        Recency is a tiebreaker only, never the primary signal.
        """
        if not mem_entries or not message.strip():
            return []

        now = time.time()
        query_tokens = _content_tokens(message)

        # If the query has no meaningful tokens, skip keyword retrieval entirely
        if not query_tokens:
            # Fall back to vector-only if available
            if not (self.memory_vector and self.memory_vector.healthy):
                return []

        # ── Build IDF from the memory corpus ──
        N = len(mem_entries)
        doc_freq = Counter()  # token -> how many memories contain it
        mem_token_cache = {}  # mem_id -> set of content tokens
        for mem in mem_entries:
            toks = set(_content_tokens(mem["text"]))
            mem_token_cache[mem["id"]] = toks
            for t in toks:
                doc_freq[t] += 1

        def _bm25_score(query_toks, mem_id):
            """BM25-inspired score between query and a memory."""
            mem_toks = mem_token_cache.get(mem_id, set())
            if not mem_toks or not query_toks:
                return 0.0
            score = 0.0
            mem_len = len(mem_toks)
            avg_len = max(sum(len(v) for v in mem_token_cache.values()) / N, 1)
            k1, b = 1.5, 0.75
            for qt in query_toks:
                if qt not in mem_toks:
                    continue
                df = doc_freq.get(qt, 0)
                idf = math.log((N - df + 0.5) / (df + 0.5) + 1)
                tf = 1  # binary presence (memory entries are short)
                tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * mem_len / avg_len))
                score += idf * tf_norm
            return score

        # ── Score all candidates ──
        has_vector = self.memory_vector and self.memory_vector.healthy
        vector_scores = {}

        if has_vector:
            results = self.memory_vector.search(message, k=min(k * 3, 20))
            mem_by_id = {m["id"]: m for m in mem_entries}
            for r in results:
                if r["memory_id"] in mem_by_id:
                    vector_scores[r["memory_id"]] = max(r["score"], 0.0)

        scored = []
        for mem in mem_entries:
            mid = mem["id"]
            vs = vector_scores.get(mid, 0.0)
            kw = _bm25_score(query_tokens, mid)

            # Normalize BM25 to roughly 0-1 range (cap at a reasonable max)
            kw_norm = min(kw / 6.0, 1.0) if kw > 0 else 0.0

            # Category-aware boost for identity/contact queries
            category = mem.get("category", "fact")
            msg_lower = message.lower()
            mem_lower = mem["text"].lower()
            cat_boost = 1.0
            if any(w in msg_lower for w in ["name", "who am i", "my name"]):
                if category == "identity" or any(w in mem_lower for w in ["name is", "i am", "called"]):
                    cat_boost = 1.4
            elif any(w in msg_lower for w in ["phone", "email", "address", "contact"]):
                if category == "contact" or "@" in mem_lower:
                    cat_boost = 1.3
            elif any(w in msg_lower for w in ["like", "prefer", "favorite"]):
                if category == "preference":
                    cat_boost = 1.2

            kw_norm = min(kw_norm * cat_boost, 1.0)

            # Recency — tiebreaker only (max 5% contribution)
            ts = mem.get("timestamp", 0)
            days_old = max((now - ts) / 86400, 0)
            recency = 1.0 / (1.0 + days_old * 0.05)

            # Gate: need real relevance, not just recency
            if has_vector:
                if vs < 0.20 and kw_norm < 0.08:
                    continue
                final = (0.55 * vs) + (0.40 * kw_norm) + (0.05 * recency)
            else:
                if kw_norm < 0.08:
                    continue
                final = (0.95 * kw_norm) + (0.05 * recency)

            if final > 0.12:
                scored.append((final, mem))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [mem for _, mem in scored[:k]]

    def build_context_preface(
        self,
        message: str,
        session: Any,
        use_web: bool = False,
        use_rag: bool = True,
        use_memory: bool = True,
        time_filter: Optional[str] = None,
        preset_system_prompt: Optional[str] = None,
        owner: Optional[str] = None,
        character_name: Optional[str] = None,
        agent_mode: bool = False,
        use_skills: bool = True,
    ) -> Tuple[List[Dict[str, str]], List[Dict[str, Any]], List[Dict[str, str]]]:
        """Build the context preface for LLM calls.

        Returns:
            Tuple of (preface messages, rag_sources list)
        """
        preface = []
        rag_sources = []

        # Add preset system prompt if specified. Otherwise, in plain chat mode,
        # give the assistant its default Applicant identity. Agent mode gets its
        # identity from the agent system prompt (_AGENT_PREAMBLE), so skip it
        # here to avoid a duplicate identity message.
        if preset_system_prompt:
            preface.append({
                "role": "system",
                "content": preset_system_prompt
            })
        elif not agent_mode:
            preface.append({
                "role": "system",
                "content": APPLICANT_IDENTITY,
            })
            # Onboarding-gap awareness — ONLY in plain chat where Applicant is
            # speaking as itself (no preset/character has overridden identity).
            # The note tells the agent which setup steps are still open and to
            # raise them only when relevant — never as a per-turn nag. Cached
            # per owner (TTL) so the engine is not hit every message; absent /
            # complete / unreachable → no note (degrade silently).
            try:
                gap_note = _onboarding_gap_note(owner)
            except Exception as _e:  # noqa: BLE001 - never block chat on this
                logger.debug("Skipping onboarding-gap note: %s", _e)
                gap_note = None
            if gap_note:
                preface.append({
                    "role": "system",
                    "content": gap_note,
                })
        preface.append({
            "role": "system",
            "content": UNTRUSTED_CONTEXT_POLICY,
        })

        # Memory: pinned (always included) + extended (RAG-retrieved when relevant)
        self._last_used_memories = []  # track what was injected
        if use_memory:
            mem_entries = self.memory_manager.load(owner=owner)

            pinned = [m for m in mem_entries if m.get("pinned")]
            extended = [m for m in mem_entries if not m.get("pinned")]

            _used_ids: list = []
            if pinned:
                pinned_text = "\n- ".join([m["text"] for m in pinned])
                preface.append(untrusted_context_message(
                    "saved memory: pinned user facts",
                    f"Core facts about the user:\n- {pinned_text}",
                ))
                for m in pinned:
                    self._last_used_memories.append({"text": m["text"], "category": m.get("category", "fact"), "type": "pinned"})
                    if m.get("id"):
                        _used_ids.append(m["id"])

            if extended:
                relevant = self._hybrid_retrieve(message, extended, k=3)
                if relevant:
                    ext_text = "\n".join([f"- {m['text']}" for m in relevant])
                    preface.append(untrusted_context_message(
                        "saved memory: retrieved context",
                        (
                            "Memory context. Do not reference unless the user asks "
                            f"about these topics.\n{ext_text}"
                        ),
                    ))
                    for m in relevant:
                        self._last_used_memories.append({"text": m["text"], "category": m.get("category", "fact"), "type": "recalled"})
                        if m.get("id"):
                            _used_ids.append(m["id"])

            # Bump usage counters for the memories that were actually injected.
            if _used_ids and hasattr(self.memory_manager, "increment_uses"):
                try:
                    self.memory_manager.increment_uses(_used_ids)
                except Exception as _e:
                    logger.warning("Failed to increment memory uses: %s", _e)

            # (skills index injection moved out — see below; only fires in
            # agent mode so chat mode stays clean.)

        # RAG: search if enabled and rag_manager available, inject only above threshold
        if use_rag:
            try:
                rag_manager = getattr(self.personal_docs_manager, 'rag_manager', None)
                if rag_manager:
                    results = rag_manager.search(message, k=5, owner=owner)
                    # Filter by similarity threshold
                    relevant = [r for r in results if r.get("similarity", 0) >= self.RAG_SIMILARITY_THRESHOLD]
                    if relevant:
                        logger.info(f"RAG: {len(relevant)}/{len(results)} results above threshold {self.RAG_SIMILARITY_THRESHOLD}")
                        rag_sources = [
                            {
                                "filename": r["metadata"].get("filename", r["metadata"].get("source", "unknown")),
                                "snippet": r["document"][:200],
                                "similarity": round(r.get("similarity", 0), 3)
                            }
                            for r in relevant
                        ]
                        rag_content = "Relevant documents:\n\n" + "\n\n---\n\n".join(
                            f"[{s['filename']}]\n{r['document']}" for s, r in zip(rag_sources, relevant)
                        )
                        if len(rag_content) > 10000:
                            rag_content = rag_content[:10000] + "\n[Truncated]"
                        preface.append(untrusted_context_message("retrieved documents", rag_content))
            except Exception as e:
                logger.warning(f"RAG retrieval failed: {e}")

        # Add web search if enabled
        web_sources = []
        if use_web:
            try:
                web_context, web_sources = comprehensive_web_search(
                    message, time_filter=time_filter, return_sources=True
                )
                preface.append(untrusted_context_message("web search results", web_context))
            except Exception as e:
                logger.error(f"Web search failed: {e}")
                preface.append({"role": "system", "content": "Web search encountered an error and could not retrieve results."})

        # Process non-YouTube URLs in message (YouTube handled by preprocess_message)
        # Skip auto-fetch for long pastes (the user already pasted the content —
        # fetching every embedded link buries the actual question under
        # hundreds of KB of duplicate page HTML and confuses the model) or for
        # link-heavy pastes (>3 URLs typically means it's a boilerplate-laden
        # blog post, not a "summarize this URL" request).
        urls = extract_urls(message)
        non_yt_urls = [u for u in urls if not is_youtube_url(u)]
        skip_url_fetch = len(message) > 2000 or len(non_yt_urls) > 3
        if not skip_url_fetch:
            for url in non_yt_urls:
                result = fetch_webpage_content(url)
                if result.get('success'):
                    content = result.get('content', '')[:10000]
                    preface.append(untrusted_context_message(
                        f"web page: {url}",
                        f"Content from {url}:\n\n{content}",
                    ))

        # Skills index — progressive disclosure. Only injected when the
        # model has the `manage_skills` tool available (agent_mode). In plain
        # chat mode the model can't call the tool anyway, so the index would
        # be noise.
        if agent_mode and use_skills and self.skills_manager:
            try:
                idx = self.skills_manager.index_for(owner=owner)
            except Exception as e:
                logger.debug(f"Skills index unavailable: {e}")
                idx = []
            if idx:
                by_cat: Dict[str, list] = {}
                for s in idx:
                    by_cat.setdefault(s.get("category") or "general", []).append(s)
                lines = ["[Available skills — call manage_skills(action='view', name='...') to load one when relevant]"]
                for cat in sorted(by_cat):
                    lines.append(f"  {cat}:")
                    for s in sorted(by_cat[cat], key=lambda x: x["name"]):
                        desc = s.get("description") or ""
                        lines.append(f"    - {s['name']}: {desc}" if desc else f"    - {s['name']}")
                preface.append(untrusted_context_message("available skills index", "\n".join(lines)))

        return preface, rag_sources, web_sources
