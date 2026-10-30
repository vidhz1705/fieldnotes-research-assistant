import json
import unittest
from email.message import Message
from unittest.mock import patch
from urllib.parse import urlsplit
from urllib.error import URLError

from research_agent import (
    LiveWebTools,
    ResearchAgent,
    ToolFailure,
    _request,
    _validate_public_url,
)

class LiveToolTests(unittest.TestCase):
    def setUp(self):
        self.tools = LiveWebTools(provider="brave", brave_api_key="test-key")

    @staticmethod
    def candidate(url="https://example.org/heat"):
        return {
            "id": "source-1",
            "url": url,
            "title": "Heat safety",
            "organization": "example.org",
            "published": "Not provided",
            "snippet": "Heat health advice",
            "score": 0.75,
        }

    def test_brave_search_parses_and_filters_results(self):
        payload = {
            "web": {"results": [
                {
                    "url": "https://example.org/heat",
                    "title": "Extreme heat health guidance",
                    "description": "Health guidance for extreme heat and hydration.",
                },
                {
                    "url": "https://example.org/unrelated",
                    "title": "A recipe collection",
                    "description": "Cooking with seasonal vegetables.",
                },
            ]}
        }
        with (
            patch("research_agent._request", return_value=(None, "application/json", json.dumps(payload).encode())),
            patch("research_agent._validate_public_url", side_effect=lambda url: urlsplit(url)),
        ):
            candidates = self.tools.search_sources("extreme heat health")
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["url"], "https://example.org/heat")
        self.assertGreater(candidates[0]["score"], 0)

    def test_brave_rejects_malformed_response_shape(self):
        with (
            patch("research_agent._request", return_value=(None, "application/json", b'{"web":{}}')),
            self.assertRaisesRegex(ToolFailure, "result list"),
        ):
            self.tools.search_sources("extreme heat")

    def test_brave_rejects_unexpected_content_type(self):
        with (
            patch("research_agent._request", return_value=(None, "text/html", b"<html></html>")),
            self.assertRaisesRegex(ToolFailure, "response type"),
        ):
            self.tools.search_sources("extreme heat")

    def test_brave_returns_empty_list_for_valid_empty_results(self):
        with patch(
            "research_agent._request",
            return_value=(None, "application/json", b'{"web":{"results":[]}}'),
        ):
            self.assertEqual(self.tools.search_sources("unknown topic"), [])

    def test_duckduckgo_challenge_is_not_mistaken_for_empty_results(self):
        tools = LiveWebTools(provider="duckduckgo")
        with patch(
            "research_agent._request",
            return_value=(None, "text/html", b'<div class="anomaly-modal">challenge-form</div>'),
        ), self.assertRaisesRegex(ToolFailure, "anti-bot challenge"):
            tools.search_sources("extreme heat")

    def test_duckduckgo_rejects_malformed_html_page(self):
        tools = LiveWebTools(provider="duckduckgo")
        with patch(
            "research_agent._request",
            return_value=(None, "text/html", b"<html><body>unexpected content</body></html>"),
        ), self.assertRaisesRegex(ToolFailure, "malformed search page"):
            tools.search_sources("extreme heat")

    def test_page_fetch_extracts_only_query_relevant_sentences(self):
        headers = Message()
        headers["Content-Type"] = "text/html; charset=utf-8"

        class FakeResponse:
            def __init__(self):
                self.headers = headers

            @staticmethod
            def geturl():
                return "https://example.org/heat"

        body = (
            "<html><title>Heat Safety</title><body>"
            "<p>General information about weather conditions and seasonal forecasts."
            " These details do not address health or safety concerns.</p>"
            "<p>Extreme heat can cause serious health risks for older adults and children."
            " Drink water and seek a cool place during dangerous heat events.</p>"
            "</body></html>"
        ).encode()
        with (
            patch("research_agent._request", return_value=(FakeResponse(), "text/html", body)),
            patch("research_agent._validate_public_url", side_effect=lambda url: urlsplit(url)),
        ):
            source = self.tools._fetch_one({**self.candidate(), "query": "extreme heat health"})
        self.assertEqual(source["title"], "Heat Safety")
        self.assertIn("serious health risks", source["summary"])
        self.assertNotIn("seasonal forecasts", source["summary"])
        self.assertEqual(source["evidence_basis"], "Extracted from the fetched page; verify in context.")

    def test_non_html_page_is_rejected(self):
        with (
            patch("research_agent._request", return_value=(None, "application/pdf", b"%PDF")),
            self.assertRaisesRegex(ToolFailure, "HTML page"),
        ):
            self.tools._fetch_one({**self.candidate(), "query": "extreme heat"})

    def test_timeout_from_network_request_is_reported(self):
        with patch("research_agent._request", side_effect=ToolFailure("Remote request timed out.")):
            fetched = self.tools.fetch_sources([self.candidate()])
        self.assertEqual(fetched[0]["status"], "error")
        self.assertEqual(fetched[0]["error"], "Remote request timed out.")

    def test_expired_research_budget_stops_further_fetches(self):
        self.tools.deadline = 0
        fetched = self.tools.fetch_sources([self.candidate()])
        self.assertEqual(fetched[0]["status"], "error")
        self.assertIn("time budget expired", fetched[0]["error"])

    def test_request_converts_network_timeout_to_tool_failure(self):
        class FakeOpener:
            @staticmethod
            def open(request, timeout):
                raise URLError(TimeoutError())

        with (
            patch("research_agent._validate_public_url"),
            patch("research_agent.urllib.request.build_opener", return_value=FakeOpener()),
            self.assertRaisesRegex(ToolFailure, "timed out"),
        ):
            _request("https://example.org", timeout=1)

    def test_private_and_non_https_urls_are_rejected(self):
        with self.assertRaisesRegex(ToolFailure, "public HTTPS"):
            _validate_public_url("http://example.org")
        with patch("research_agent.socket.getaddrinfo", return_value=[
            (None, None, None, None, ("127.0.0.1", 443))
        ]), self.assertRaisesRegex(ToolFailure, "Private"):
            _validate_public_url("https://private.example")

    def test_live_candidate_without_well_formed_https_url_is_rejected(self):
        agent = ResearchAgent(search_provider="duckduckgo")
        with patch.object(
            LiveWebTools,
            "search_sources",
            return_value=[{"id": "bad", "score": 0.8, "url": "https://"}],
        ):
            result = agent.research("extreme heat")
        self.assertEqual(result["tools"][0]["status"], "error")
        self.assertEqual(result["sources"], [])

    def test_live_agent_reports_empty_search_without_claims(self):
        agent = ResearchAgent(search_provider="duckduckgo")
        with patch.object(LiveWebTools, "search_sources", return_value=[]):
            result = agent.research("question with no result")
        self.assertEqual(result["mode"], "live")
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["key_findings"], [])
        self.assertEqual(result["confidence"], "Low")
        self.assertEqual(result["tools"][0]["status"], "success")

    def test_live_agent_preserves_partial_success_and_explains_failure(self):
        agent = ResearchAgent(search_provider="duckduckgo")
        candidates = [
            self.candidate(),
            {**self.candidate("https://example.net/heat"), "id": "source-2"},
        ]
        good_source = {
            "id": "source-1",
            "title": "Heat Safety",
            "organization": "example.org",
            "url": "https://example.org/heat",
            "published": "Not provided",
            "summary": "Extreme heat can cause serious health risks.",
            "search_score": 0.75,
            "evidence_score": 0.66,
            "evidence_basis": "Extracted from fetched page.",
            "search_provider": "duckduckgo",
        }
        failed_source = {"id": "source-2", "status": "error", "error": "Source timed out."}
        with (
            patch.object(LiveWebTools, "search_sources", return_value=candidates),
            patch.object(LiveWebTools, "fetch_sources", return_value=[good_source, failed_source]),
        ):
            result = agent.research("extreme heat health")
        self.assertEqual([source["id"] for source in result["sources"]], ["source-1"])
        self.assertEqual(result["tools"][1]["status"], "partial")
        self.assertTrue(any("Source timed out" in note for note in result["limitations_assumptions"]))
        self.assertEqual(result["confidence"], "Low")
        self.assertIn("some candidate pages were unavailable", result["confidence_reason"])

    def test_live_confidence_uses_relevance_and_domain_coverage(self):
        agent = ResearchAgent(search_provider="duckduckgo")
        evidence = [
            {
                "url": f"https://example-{index}.org/source",
                "search_score": 0.8,
                "evidence_score": 0.7,
            }
            for index in range(3)
        ]
        confidence, reason = agent._confidence(evidence)
        self.assertEqual(confidence, "Moderate to high")
        self.assertIn("not a probability", reason)

        weak_evidence = [
            {**evidence[0], "search_score": 0.1, "evidence_score": 0.1},
            {**evidence[1], "search_score": 0.1, "evidence_score": 0.1},
        ]
        self.assertEqual(agent._confidence(weak_evidence)[0], "Low")

    def test_live_agent_rejects_malformed_search_candidate(self):
        agent = ResearchAgent(search_provider="duckduckgo")
        with (
            patch.object(LiveWebTools, "search_sources", return_value=[{"id": "bad", "score": "high"}]),
            patch.object(LiveWebTools, "fetch_sources", return_value=[]),
        ):
            result = agent.research("extreme heat")
        self.assertEqual(result["tools"][0]["status"], "error")
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["confidence"], "Low")

    def test_live_agent_rejects_fetch_id_mismatch(self):
        agent = ResearchAgent(search_provider="duckduckgo")
        with (
            patch.object(LiveWebTools, "search_sources", return_value=[self.candidate()]),
            patch.object(LiveWebTools, "fetch_sources", return_value=[]),
        ):
            result = agent.research("extreme heat")
        self.assertEqual(result["tools"][1]["status"], "error")
        self.assertEqual(result["sources"], [])
        self.assertTrue(any("omitted or changed" in note for note in result["limitations_assumptions"]))

    def test_live_agent_returns_structured_answer_from_verified_fetch(self):
        agent = ResearchAgent(search_provider="duckduckgo")
        source = {
            "id": "source-1",
            "title": "Heat Safety",
            "organization": "example.org",
            "url": "https://example.org/heat",
            "published": "Publication date not reliably identified",
            "summary": "Extreme heat can cause serious health risks for older adults.",
            "search_score": 0.75,
            "evidence_score": 0.66,
            "evidence_basis": "Extracted from the fetched page; verify in context.",
            "search_provider": "duckduckgo",
        }
        with (
            patch.object(LiveWebTools, "search_sources", return_value=[self.candidate()]),
            patch.object(LiveWebTools, "fetch_sources", return_value=[source]),
        ):
            result = agent.research("extreme heat health")
        self.assertEqual(result["mode"], "live")
        self.assertEqual([tool["status"] for tool in result["tools"]], ["success", "success"])
        self.assertEqual(result["sources"][0]["id"], "source-1")
        self.assertEqual(result["key_findings"][0]["source_ids"], ["source-1"])
        self.assertIn("serious health risks", result["short_answer"])
        self.assertEqual(result["confidence"], "Low")
        self.assertTrue(result["confidence_reason"])


if __name__ == "__main__":
    unittest.main()
