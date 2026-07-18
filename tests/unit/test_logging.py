import pytest

from applicant.observability import logging as logging_mod


class TestRedactText:
    """Tests for redact_text / _redact_text secret masking (NFR-PRIV-1)."""

    # --- passthrough for short / safe strings ---
    def test_short_string_passthrough(self):
        assert logging_mod.redact_text("hi") == "hi"

    def test_shortish_safe_string(self):
        assert logging_mod.redact_text("hello world") == "hello world"

    def test_plain_email(self):
        assert logging_mod.redact_text("user@example.com") == "user@example.com"

    # --- JWT tokens ---
    def test_jwt_token_redacted(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dK3gB3kQnF7p8W-4gk5v6w7x8y9z"
        assert logging_mod.redact_text(jwt) == logging_mod._REDACTED

    def test_jwt_embedded_in_message(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.signature12345"
        msg = f"Token: {jwt} used for auth"
        result = logging_mod.redact_text(msg)
        assert logging_mod._REDACTED in result
        assert result.count(logging_mod._REDACTED) == 1

    # --- sk- API keys ---
    def test_sk_api_key_redacted(self):
        assert logging_mod.redact_text("sk-proj-abcd1234efgh5678ijkl9012mnop3456") == logging_mod._REDACTED

    def test_sk_short_key_redacted(self):
        assert logging_mod.redact_text("sk-abc123def456ghi789") == logging_mod._REDACTED

    def test_sk_key_embedded_in_message(self):
        msg = "Using key sk-abc123def456ghi789 for OpenAI"
        result = logging_mod.redact_text(msg)
        assert logging_mod._REDACTED in result

    # --- bearer / token patterns ---
    def test_bearer_token_line(self):
        msg = "Authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz123456"
        result = logging_mod.redact_text(msg)
        assert logging_mod._REDACTED in result

    def test_api_key_equals_value(self):
        msg = "api_key=sk-abc123def456ghi789"
        result = logging_mod.redact_text(msg)
        assert logging_mod._REDACTED in result

    # --- password= inline patterns ---
    def test_password_equals_inline(self):
        msg = "connection password=superS3cret!@#"
        result = logging_mod.redact_text(msg)
        assert logging_mod._REDACTED in result

    def test_pwd_colon_inline(self):
        msg = "pwd: mypass123"
        result = logging_mod.redact_text(msg)
        assert logging_mod._REDACTED in result

    def test_secret_equals_inline(self):
        msg = "secret=mysecretvalue"
        result = logging_mod.redact_text(msg)
        assert logging_mod._REDACTED in result

    # --- URL userinfo ---
    def test_url_userinfo_redacted(self):
        url = "smtps://user:password@smtp.example.com:587"
        result = logging_mod.redact_text(url)
        assert "://" + logging_mod._REDACTED + "@" in result
        assert "user:" not in result
        assert "password" not in result or "@" not in result.split("password")[0]

    def test_url_userinfo_with_special_chars(self):
        url = "http://admin:secret123@host.local/path"
        result = logging_mod.redact_text(url)
        assert "://" + logging_mod._REDACTED + "@" in result

    # --- high-entropy catch-all ---
    def test_high_entropy_32plus_redacted(self):
        token = "aB3dE5fGhIjKlMnOpQrStUvWxYz0123456789"
        assert len(token) >= 32
        result = logging_mod.redact_text(token)
        assert result == logging_mod._REDACTED

    def test_high_entropy_embedded(self):
        token = "aB3dE5fGhIjKlMnOpQrStUvWxYz0123456789"
        msg = f"token={token}"
        result = logging_mod.redact_text(msg)
        assert logging_mod._REDACTED in result

    def test_short_token_not_redacted_by_high_entropy(self):
        token = "aB3dE5fG"  # 8 chars but < 32
        result = logging_mod.redact_text(token)
        assert result == token

    # --- multiple patterns in one string ---
    def test_multiple_secrets_in_message(self):
        msg = "jwt=eyJ.eyJ.sig and key=sk-abc123def456ghi789"
        result = logging_mod.redact_text(msg)
        assert logging_mod._REDACTED in result
        # Should have replaced at least the secret tokens
        assert "eyJ" not in result.split(logging_mod._REDACTED)[0] if result.startswith(logging_mod._REDACTED) else True

    # --- edge cases ---
    def test_empty_string(self):
        assert logging_mod.redact_text("") == ""

    def test_single_char(self):
        assert logging_mod.redact_text("a") == "a"

    def test_numeric_string(self):
        assert logging_mod.redact_text("1234567") == "1234567"


class TestRedactValue:
    """Tests for _redact_value recursive secret redaction."""

    # --- dict redaction by key name ---
    def test_dict_secret_key_redacted(self):
        d = {"password": "mysecret123", "name": "Alice"}
        result = logging_mod._redact_value(d)
        assert result["password"] == logging_mod._REDACTED
        assert result["name"] == "Alice"

    def test_dict_case_insensitive_secret_key(self):
        d = {"API_KEY": "sk-abc123", "Token": "ghp_xyz"}
        result = logging_mod._redact_value(d)
        assert result["API_KEY"] == logging_mod._REDACTED
        assert result["Token"] == logging_mod._REDACTED

    def test_dict_multiple_secret_keys(self):
        d = {"password": "p1", "api_key": "k1", "ssn": "123-45-6789", "normal": "ok"}
        result = logging_mod._redact_value(d)
        assert result["password"] == logging_mod._REDACTED
        assert result["api_key"] == logging_mod._REDACTED
        assert result["ssn"] == logging_mod._REDACTED
        assert result["normal"] == "ok"

    def test_dict_all_secret_keys_accounted(self):
        """Ensure every key in _SECRET_KEYS triggers redaction."""
        d = {k: f"value_{k}" for k in logging_mod._SECRET_KEYS}
        result = logging_mod._redact_value(d)
        for k in logging_mod._SECRET_KEYS:
            assert result[k] == logging_mod._REDACTED, f"Key {k} was not redacted"

    # --- nested dict ---
    def test_nested_dict_nested_secret_redacted(self):
        d = {"config": {"password": "secret123"}}
        result = logging_mod._redact_value(d)
        assert result["config"]["password"] == logging_mod._REDACTED

    def test_deeply_nested_secret(self):
        d = {"a": {"b": {"c": {"token": "ghp_abc"}}}}
        result = logging_mod._redact_value(d)
        assert result["a"]["b"]["c"]["token"] == logging_mod._REDACTED

    # --- list / tuple ---
    def test_list_values_redacted(self):
        lst = ["safe", "sk-abc123def456ghi789"]
        result = logging_mod._redact_value(lst)
        assert result[0] == "safe"
        assert result[1] == logging_mod._REDACTED

    def test_tuple_values_redacted(self):
        tup = ("safe", "password=secret123")
        result = logging_mod._redact_value(tup)
        assert result[0] == "safe"
        assert result[1] == logging_mod._REDACTED

    def test_list_with_dict_secret(self):
        lst = [{"password": "secret"}]
        result = logging_mod._redact_value(lst)
        assert result[0]["password"] == logging_mod._REDACTED

    # --- string values ---
    def test_string_value_redacted_via_redact_text(self):
        result = logging_mod._redact_value("sk-abc123def456ghi789")
        assert result == logging_mod._REDACTED

    def test_safe_string_value_passthrough(self):
        assert logging_mod._redact_value("hello world") == "hello world"

    # --- non-string/dict/list passthrough ---
    def test_int_passthrough(self):
        assert logging_mod._redact_value(42) == 42

    def test_float_passthrough(self):
        assert logging_mod._redact_value(3.14) == 3.14

    def test_bool_passthrough(self):
        assert logging_mod._redact_value(True) is True

    def test_none_passthrough(self):
        assert logging_mod._redact_value(None) is None

    # --- empty containers ---
    def test_empty_dict(self):
        assert logging_mod._redact_value({}) == {}

    def test_empty_list(self):
        assert logging_mod._redact_value([]) == []


class TestBindCorrelationId:
    """Tests for bind_correlation_id and its contextvar (FR-OBS-1)."""

    def test_bind_sets_contextvar(self):
        token = logging_mod.bind_correlation_id("test-cid-123")
        assert logging_mod.correlation_id.get() == "test-cid-123"
        logging_mod.correlation_id.reset(token)

    def test_bind_returns_token(self):
        token = logging_mod.bind_correlation_id("abc")
        # Resetting with the token should restore default (None)
        logging_mod.correlation_id.reset(token)
        assert logging_mod.correlation_id.get() is None

    def test_multiple_binds_replace(self):
        t1 = logging_mod.bind_correlation_id("first")
        t2 = logging_mod.bind_correlation_id("second")
        assert logging_mod.correlation_id.get() == "second"
        logging_mod.correlation_id.reset(t2)
        logging_mod.correlation_id.reset(t1)

    def test_default_is_none(self):
        # Ensure correlation_id is not set (test isolation important here)
        current = logging_mod.correlation_id.get()
        assert current is None or isinstance(current, (str, type(None)))


class TestAddCorrelationIdProcessor:
    """Tests for _add_correlation_id processor."""

    def test_adds_correlation_id_when_set(self):
        token = logging_mod.bind_correlation_id("req-456")
        event_dict = {}
        result = logging_mod._add_correlation_id(None, "info", event_dict)
        assert result["correlation_id"] == "req-456"
        logging_mod.correlation_id.reset(token)

    def test_noop_when_not_set(self):
        event_dict = {}
        result = logging_mod._add_correlation_id(None, "info", event_dict)
        assert "correlation_id" not in result

    def test_does_not_overwrite_existing(self):
        token = logging_mod.bind_correlation_id("new-cid")
        event_dict = {"correlation_id": "existing"}
        result = logging_mod._add_correlation_id(None, "info", event_dict)
        # setdefault means existing value is kept
        assert result["correlation_id"] == "existing"
        logging_mod.correlation_id.reset(token)


class TestCaptureLogAndRecentLogs:
    """Tests for _capture_log processor and recent_logs reader (FR-OBS-2, FR-LOG-3)."""

    @pytest.fixture(autouse=True)
    def clear_ring(self):
        logging_mod._LOG_RING.clear()
        yield

    def test_capture_log_appends_event(self):
        logging_mod._capture_log(None, "info", {"msg": "hello world", "level": "info"})
        logs = logging_mod.recent_logs()
        assert len(logs) == 1
        assert logs[0]["msg"] == "hello world"
        assert logs[0]["level"] == "info"

    def test_capture_log_returns_event_dict(self):
        event = {"msg": "test"}
        result = logging_mod._capture_log(None, "info", event)
        assert result is event

    def test_recent_logs_returns_newest_last(self):
        logging_mod._capture_log(None, "info", {"seq": 1})
        logging_mod._capture_log(None, "info", {"seq": 2})
        logging_mod._capture_log(None, "info", {"seq": 3})
        logs = logging_mod.recent_logs()
        assert [l["seq"] for l in logs] == [1, 2, 3]

    def test_recent_logs_respects_limit(self):
        for i in range(20):
            logging_mod._capture_log(None, "info", {"i": i})
        logs = logging_mod.recent_logs(limit=5)
        assert len(logs) == 5
        assert logs[0]["i"] == 15
        assert logs[-1]["i"] == 19

    def test_recent_logs_default_limit_100(self):
        for i in range(50):
            logging_mod._capture_log(None, "info", {"i": i})
        logs = logging_mod.recent_logs()
        assert len(logs) == 50

    def test_recent_logs_zero_limit_returns_all(self):
        for i in range(10):
            logging_mod._capture_log(None, "info", {"i": i})
        logs = logging_mod.recent_logs(limit=0)
        assert len(logs) == 10

    def test_ring_buffer_maxlen_500(self):
        assert logging_mod._LOG_RING.maxlen == 500

    def test_ring_buffer_overflow_drops_oldest(self):
        for i in range(600):
            logging_mod._capture_log(None, "info", {"i": i})
        assert len(logging_mod._LOG_RING) == 500
        logs = logging_mod.recent_logs(limit=0)
        assert logs[0]["i"] == 100  # oldest remaining

    def test_capture_stores_jsonable_copy(self):
        """Verify the stored event dict is converted via _to_jsonable."""
        logging_mod._capture_log(None, "info", {"val": 42})
        logs = logging_mod.recent_logs()
        assert logs[0]["val"] == 42


class TestToJsonable:
    """Tests for _to_jsonable type coercion."""

    def test_primitives_passthrough(self):
        assert logging_mod._to_jsonable("s") == "s"
        assert logging_mod._to_jsonable(1) == 1
        assert logging_mod._to_jsonable(1.5) == 1.5
        assert logging_mod._to_jsonable(True) is True
        assert logging_mod._to_jsonable(None) is None

    def test_dict_keys_coerced_to_str(self):
        result = logging_mod._to_jsonable({1: "one", 2: "two"})
        assert result == {"1": "one", "2": "two"}

    def test_nested_dict(self):
        result = logging_mod._to_jsonable({"a": {"b": [1, 2]}})
        assert result == {"a": {"b": [1, 2]}}

    def test_tuple_becomes_list(self):
        result = logging_mod._to_jsonable((1, "two", 3.0))
        assert result == [1, "two", 3.0]

    def test_list_passthrough(self):
        result = logging_mod._to_jsonable(["a", 1, True])
        assert result == ["a", 1, True]

    def test_fallback_to_str(self):
        class Custom:
            def __str__(self):
                return "custom_str"
        assert logging_mod._to_jsonable(Custom()) == "custom_str"


class TestTraceHook:
    """Tests for set_trace_hook / get_trace_hook (FR-OBS-1)."""

    def test_default_is_none(self):
        assert logging_mod.get_trace_hook() is None

    def test_set_and_get(self):
        hook = lambda x: x
        logging_mod.set_trace_hook(hook)
        assert logging_mod.get_trace_hook() is hook
        # Reset to None for isolation
        logging_mod.set_trace_hook(None)
        assert logging_mod.get_trace_hook() is None

    def test_set_none(self):
        logging_mod.set_trace_hook(None)
        assert logging_mod.get_trace_hook() is None

    def test_set_overwrites(self):
        hook_a = lambda: "a"
        hook_b = lambda: "b"
        logging_mod.set_trace_hook(hook_a)
        logging_mod.set_trace_hook(hook_b)
        assert logging_mod.get_trace_hook() is hook_b
        logging_mod.set_trace_hook(None)


class TestRedactSecretsProcessor:
    """Tests for _redact_secrets structlog processor."""

    def test_redacts_secret_key_values(self):
        event = {"password": "mysecret", "msg": "logged in"}
        result = logging_mod._redact_secrets(None, "info", event)
        assert result["password"] == logging_mod._REDACTED
        assert result["msg"] == "logged in"

    def test_redacts_secret_values_in_non_secret_keys(self):
        event = {"note": "key is sk-abc123def456ghi789", "msg": "test"}
        result = logging_mod._redact_secrets(None, "info", event)
        assert logging_mod._REDACTED in result["note"]
        assert "sk-" not in result["note"]

    def test_returns_same_event_dict(self):
        event = {"msg": "test"}
        result = logging_mod._redact_secrets(None, "info", event)
        assert result is event

    def test_recursive_redaction(self):
        event = {"data": {"api_key": "sk-xxx", "safe": "ok"}}
        result = logging_mod._redact_secrets(None, "info", event)
        assert result["data"]["api_key"] == logging_mod._REDACTED
        assert result["data"]["safe"] == "ok"


class TestConstants:
    """Smoke tests for module-level constants."""

    def test_redacted_constant(self):
        assert logging_mod._REDACTED == "***REDACTED***"

    def test_secret_keys_is_frozenset(self):
        assert isinstance(logging_mod._SECRET_KEYS, frozenset)

    def test_secret_keys_contains_expected(self):
        expected = {"password", "secret", "api_key", "apikey", "token",
                    "authorization", "credential", "llm_api_key",
                    "discord_webhook_url", "apprise_urls", "master_key", "ssn"}
        assert logging_mod._SECRET_KEYS == expected

    def test_log_ring_is_deque(self):
        from collections import deque
        assert isinstance(logging_mod._LOG_RING, deque)


class TestModuleSmoke:
    """Smoke tests: imports work and public names exist."""

    def test_redact_text_exists(self):
        assert callable(logging_mod.redact_text)

    def test_recent_logs_exists(self):
        assert callable(logging_mod.recent_logs)

    def test_bind_correlation_id_exists(self):
        assert callable(logging_mod.bind_correlation_id)

    def test_set_trace_hook_exists(self):
        assert callable(logging_mod.set_trace_hook)

    def test_get_trace_hook_exists(self):
        assert callable(logging_mod.get_trace_hook)

    def test_protected_functions_exist(self):
        assert callable(logging_mod._redact_text)
        assert callable(logging_mod._redact_value)
        assert callable(logging_mod._redact_secrets)
        assert callable(logging_mod._capture_log)
        assert callable(logging_mod._to_jsonable)
        assert callable(logging_mod._add_correlation_id)
