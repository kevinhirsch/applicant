"""Unit tests for the ProviderProfile registry (FR-HARVEST-PROVIDER).

Validates:
- Profile detection by provider name and URL heuristic.
- Auth header generation per profile (Bearer vs. none).
- URL construction for model-list and chat endpoints.
- Models response parsing (Ollama tags format vs. OpenAI data format).
- The get_profile() dispatcher always returns a profile without raising.
"""

from __future__ import annotations

from applicant.adapters.llm.provider_profiles import (
    OLLAMA_PROFILE,
    OPENAI_PROFILE,
    PROFILES,
    ProviderProfile,
    get_profile,
)

# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


class TestOllamaDetection:
    def test_explicit_ollama_provider_name(self):
        assert OLLAMA_PROFILE.detect("ollama", "http://anything") is True

    def test_ollama_provider_name_case_insensitive(self):
        assert OLLAMA_PROFILE.detect("Ollama", "http://anything") is True
        assert OLLAMA_PROFILE.detect("OLLAMA", "http://anything") is True

    def test_default_port_11434_url(self):
        assert OLLAMA_PROFILE.detect("", "http://localhost:11434") is True

    def test_api_path_heuristic_when_provider_unset(self):
        assert OLLAMA_PROFILE.detect("", "http://myhost/api/") is True

    def test_explicit_openrouter_provider_not_ollama(self):
        # FR-LLM-2 regression: OpenRouter base contains /api/ but must not match Ollama
        # when provider is explicitly set to something other than "ollama".
        assert OLLAMA_PROFILE.detect("openrouter", "https://openrouter.ai/api/v1") is False

    def test_explicit_openai_provider_not_ollama(self):
        assert OLLAMA_PROFILE.detect("openai", "https://api.openai.com/v1") is False


class TestOpenAIDetection:
    def test_openai_url_matches(self):
        assert OPENAI_PROFILE.detect("openai", "https://api.openai.com/v1") is True

    def test_openrouter_url_matches(self):
        assert OPENAI_PROFILE.detect("openrouter", "https://openrouter.ai/api/v1") is True

    def test_catch_all_for_unknown_provider(self):
        assert OPENAI_PROFILE.detect("some-new-provider", "https://example.com/v1") is True

    def test_catch_all_for_empty_provider(self):
        # Empty provider, non-Ollama URL: openai profile is the catch-all.
        assert OPENAI_PROFILE.detect("", "https://custom.llm.example.com/v1") is True


class TestGetProfile:
    def test_returns_ollama_for_ollama_provider(self):
        profile = get_profile("ollama", "http://localhost:11434")
        assert profile.name == "ollama"

    def test_returns_openai_for_openai_provider(self):
        profile = get_profile("openai", "https://api.openai.com/v1")
        assert profile.name == "openai"

    def test_returns_openai_for_openrouter(self):
        profile = get_profile("openrouter", "https://openrouter.ai/api/v1")
        assert profile.name == "openai"

    def test_ollama_wins_over_openai_for_11434_url(self):
        # get_profile checks PROFILES in order; Ollama must come first.
        profile = get_profile("", "http://myhost:11434")
        assert profile.name == "ollama"

    def test_always_returns_a_profile(self):
        # Should never raise even for a completely unknown combination.
        profile = get_profile("totally-unknown", "https://whatever.example.com")
        assert isinstance(profile, ProviderProfile)

    def test_profiles_list_nonempty(self):
        assert len(PROFILES) >= 2


# ---------------------------------------------------------------------------
# Auth headers
# ---------------------------------------------------------------------------


class TestHeaders:
    def test_ollama_produces_no_auth_header_even_with_key(self):
        headers = OLLAMA_PROFILE.headers("super-secret-key")
        assert "Authorization" not in headers

    def test_ollama_produces_no_auth_header_with_empty_key(self):
        headers = OLLAMA_PROFILE.headers("")
        assert "Authorization" not in headers

    def test_openai_produces_bearer_header(self):
        headers = OPENAI_PROFILE.headers("sk-test-key")
        assert headers.get("Authorization") == "Bearer sk-test-key"

    def test_openai_produces_no_auth_header_when_key_empty(self):
        headers = OPENAI_PROFILE.headers("")
        assert "Authorization" not in headers


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------


class TestModelsUrl:
    def test_ollama_tags_url_basic(self):
        assert OLLAMA_PROFILE.models_url("http://localhost:11434") == "http://localhost:11434/api/tags"

    def test_ollama_strips_v1_suffix(self):
        # Ollama base ending in /v1 (OpenAI-compat shim) must still hit /api/tags.
        assert OLLAMA_PROFILE.models_url("http://gpu:11434/v1") == "http://gpu:11434/api/tags"

    def test_openai_models_with_v1(self):
        assert OPENAI_PROFILE.models_url("https://api.openai.com/v1") == "https://api.openai.com/v1/models"

    def test_openai_models_without_v1(self):
        assert OPENAI_PROFILE.models_url("https://api.openai.com") == "https://api.openai.com/v1/models"


class TestChatUrl:
    def test_ollama_chat_basic(self):
        assert OLLAMA_PROFILE.chat_url("http://localhost:11434") == "http://localhost:11434/api/chat"

    def test_ollama_chat_strips_v1(self):
        assert OLLAMA_PROFILE.chat_url("http://gpu:11434/v1") == "http://gpu:11434/api/chat"

    def test_openai_chat_with_v1(self):
        assert (
            OPENAI_PROFILE.chat_url("https://api.openai.com/v1")
            == "https://api.openai.com/v1/chat/completions"
        )

    def test_openai_chat_without_v1(self):
        assert (
            OPENAI_PROFILE.chat_url("https://api.openai.com")
            == "https://api.openai.com/v1/chat/completions"
        )

    def test_openrouter_chat(self):
        assert (
            OPENAI_PROFILE.chat_url("https://openrouter.ai/api/v1")
            == "https://openrouter.ai/api/v1/chat/completions"
        )


# ---------------------------------------------------------------------------
# Models response extraction
# ---------------------------------------------------------------------------


class TestModelsExtractor:
    def test_ollama_extracts_names(self):
        data = {"models": [{"name": "llama3.1:8b"}, {"name": "qwen2.5:14b"}]}
        assert OLLAMA_PROFILE.models_extractor(data) == ["llama3.1:8b", "qwen2.5:14b"]

    def test_ollama_empty_list(self):
        assert OLLAMA_PROFILE.models_extractor({"models": []}) == []

    def test_ollama_non_dict_body(self):
        assert OLLAMA_PROFILE.models_extractor([]) == []  # type: ignore[arg-type]

    def test_openai_extracts_ids(self):
        data = {"data": [{"id": "gpt-4o-mini"}, {"id": "gpt-4o"}]}
        assert OPENAI_PROFILE.models_extractor(data) == ["gpt-4o-mini", "gpt-4o"]

    def test_openai_empty_data(self):
        assert OPENAI_PROFILE.models_extractor({"data": []}) == []

    def test_openai_non_dict_body(self):
        assert OPENAI_PROFILE.models_extractor("not a dict") == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Request builder
# ---------------------------------------------------------------------------


class TestBuildRequest:
    def test_openai_basic_payload(self):
        msgs = [{"role": "user", "content": "hi"}]
        payload = OPENAI_PROFILE.build_request("gpt-4o-mini", msgs, None, None)
        assert payload["model"] == "gpt-4o-mini"
        assert payload["messages"] == msgs
        assert "response_format" not in payload
        assert "max_tokens" not in payload

    def test_openai_includes_response_format_when_schema_given(self):
        schema = {"type": "object", "required": ["score"]}
        payload = OPENAI_PROFILE.build_request("m", [], schema, None)
        assert payload["response_format"]["type"] == "json_schema"

    def test_openai_includes_max_tokens(self):
        payload = OPENAI_PROFILE.build_request("m", [], None, 512)
        assert payload["max_tokens"] == 512

    def test_ollama_basic_payload(self):
        msgs = [{"role": "user", "content": "hi"}]
        payload = OLLAMA_PROFILE.build_request("llama3.1:8b", msgs, None, None)
        assert payload["model"] == "llama3.1:8b"
        assert payload["stream"] is False
        assert "format" not in payload
        assert "options" not in payload

    def test_ollama_sets_format_json_when_schema(self):
        schema = {"type": "object"}
        payload = OLLAMA_PROFILE.build_request("llama3.1:8b", [], schema, None)
        assert payload["format"] == "json"

    def test_ollama_sets_num_predict(self):
        payload = OLLAMA_PROFILE.build_request("llama3.1:8b", [], None, 256)
        assert payload["options"]["num_predict"] == 256


# ---------------------------------------------------------------------------
# Extract text
# ---------------------------------------------------------------------------


class TestExtractText:
    def test_openai_extracts_content(self):
        raw = {"choices": [{"message": {"content": "hello world"}}]}
        assert OPENAI_PROFILE.extract_text(raw) == "hello world"

    def test_openai_extracts_tool_call_arguments(self):
        raw = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "f", "arguments": '{"k": "v"}'},
                            }
                        ],
                    }
                }
            ]
        }
        assert OPENAI_PROFILE.extract_text(raw) == '{"k": "v"}'

    def test_openai_empty_on_malformed(self):
        assert OPENAI_PROFILE.extract_text({}) == ""
        assert OPENAI_PROFILE.extract_text({"choices": []}) == ""

    def test_ollama_extracts_message_content(self):
        raw = {"message": {"content": "local reply"}}
        assert OLLAMA_PROFILE.extract_text(raw) == "local reply"

    def test_ollama_falls_back_to_response_key(self):
        raw = {"response": "fallback reply"}
        assert OLLAMA_PROFILE.extract_text(raw) == "fallback reply"

    def test_ollama_empty_on_empty_dict(self):
        assert OLLAMA_PROFILE.extract_text({}) == ""
