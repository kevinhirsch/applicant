"""Unit tests for src/applicant/adapters/discovery/url_intake.py."""

import json
import pytest
from applicant.adapters.discovery.url_intake import (
    _strip_tags,
    _iter_jsonld_nodes,
    _jobposting_from_jsonld,
    extract_posting_metadata,
)


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Ensure no module-level state leaks between tests in parallel workers."""
    yield


@pytest.mark.unit
class TestStripTags:
    def test_plain_text(self):
        assert _strip_tags("Software Engineer") == "Software Engineer"

    def test_simple_tag(self):
        assert _strip_tags("<strong>Senior</strong> Developer") == "Senior Developer"

    def test_nested_tags(self):
        assert _strip_tags("<p><em>Full</em> <strong>Stack</strong></p>") == "Full Stack"

    def test_malformed_unclosed_tag(self):
        assert _strip_tags("<b>Junior<b> Dev") == "Junior Dev"

    def test_empty_string(self):
        assert _strip_tags("") == ""

    def test_whitespace_normalization(self):
        assert _strip_tags("<p>  Lots   of   whitespace </p>") == "Lots of whitespace"

    def test_entity_references(self):
        assert _strip_tags("&lt;script&gt;code&lt;/script&gt;") == "<script>code</script>"


@pytest.mark.unit
class TestIterJsonldNodes:
    def test_dict_input(self):
        nodes = list(_iter_jsonld_nodes({"@type": "JobPosting"}))
        assert len(nodes) == 1
        assert nodes[0]["@type"] == "JobPosting"

    def test_list_input(self):
        data = [{"@type": "JobPosting"}, {"@type": "Organization"}]
        nodes = list(_iter_jsonld_nodes(data))
        assert len(nodes) == 2

    def test_graph_structure(self):
        data = {"@graph": [{"@type": "JobPosting"}, {"@type": "Place"}]}
        nodes = list(_iter_jsonld_nodes(data))
        # Yields root dict + each graph node
        assert len(nodes) == 3

    def test_empty_list(self):
        assert list(_iter_jsonld_nodes([])) == []

    def test_empty_dict(self):
        nodes = list(_iter_jsonld_nodes({}))
        assert len(nodes) == 1
        assert nodes[0] == {}


@pytest.mark.unit
class TestJobpostingFromJsonld:
    def test_minimal_blob(self):
        blob = json.dumps({"@type": "JobPosting", "title": "Engineer"})
        result = _jobposting_from_jsonld([blob])
        assert result.get("title") == "Engineer"

    def test_full_blob(self):
        blob = json.dumps({
            "@type": "JobPosting",
            "title": "Backend Developer",
            "description": "<p>Build APIs</p>",
            "hiringOrganization": {"name": "TechCorp"},
            "jobLocation": {"address": {"addressLocality": "Berlin"}},
            "baseSalary": {
                "value": {"minValue": 80_000, "maxValue": 120_000, "unitText": "YEAR"},
            },
            "jobLocationType": "TELECOMMUTE",
        })
        result = _jobposting_from_jsonld([blob])
        assert result.get("title") == "Backend Developer"
        assert result.get("company") == "TechCorp"
        assert "APIs" in result.get("description", "")
        assert result.get("location") == "Berlin"
        assert result.get("salary") == "80000-120000 per year"
        assert result.get("work_mode") == "remote"

    def test_graph_with_jobposting(self):
        blob = json.dumps({
            "@graph": [
                {"@type": "Organization", "name": "Acme"},
                {"@type": "JobPosting", "title": "Designer", "hiringOrganization": {"name": "Acme"}},
            ]
        })
        result = _jobposting_from_jsonld([blob])
        assert result.get("title") == "Designer"

    def test_invalid_json(self):
        result = _jobposting_from_jsonld(["not json"])
        assert result == {}

    def test_no_jobposting_type(self):
        blob = json.dumps({"@type": "Thing", "title": "Role"})
        result = _jobposting_from_jsonld([blob])
        assert result == {}

    def test_empty_blobs(self):
        assert _jobposting_from_jsonld([]) == {}


@pytest.mark.unit
class TestExtractPostingMetadata:
    def test_full_page(self):
        html = """<html>
<head>
<title>Senior Python Developer at DataCo</title>
<meta name="description" content="Join our team">
<script type="application/ld+json">
{"@type": "JobPosting", "title": "Senior Python Developer", "hiringOrganization": {"name": "DataCo"}}
</script>
</head>
<body></body>
</html>"""
        result = extract_posting_metadata(html)
        assert "Senior Python Developer" in result.get("title", "")
        assert result.get("company") == "DataCo"

    def test_no_jsonld(self):
        html = """<html><head><title>Dev Role</title></head><body></body></html>"""
        result = extract_posting_metadata(html)
        assert result.get("title") == "Dev Role"

    def test_empty_html(self):
        result = extract_posting_metadata("")
        assert result.get("title") is None

    def test_no_meta_tags(self):
        html = """<html><head><title>Role</title></head><body></body></html>"""
        result = extract_posting_metadata(html)
        assert result.get("title") == "Role"

    def test_multiple_meta_same_name(self):
        html = """<html><head>
<meta name="description" content="First">
<meta name="description" content="Second">
</head><body></body></html>"""
        result = extract_posting_metadata(html)
        # First one wins per implementation
        assert result.get("description") == "First"
