"""
test_pipeline.py
----------------
Tests the orchestration logic and Chat-response parsing WITHOUT hitting the
network, by substituting a fake GleanClient. These run anywhere and prove the
behavior that matters most: grounding, the empty-result guard, and source merge.

Run:  python -m pytest tests/ -v      (or: python tests/test_pipeline.py)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from glean_client import GleanClient  # noqa: E402
from pipeline import answer_question, NO_RESULTS_MESSAGE  # noqa: E402


class FakeClient:
    """Stand-in for GleanClient with scriptable search/chat responses."""

    def __init__(self, search_results, chat_response):
        self._search_results = search_results
        self._chat_response = chat_response
        self.chat_called = False

    def search(self, query, page_size=5, datasource=None):
        return self._search_results

    def chat(self, question, context_docs=None, datasource=None):
        self.chat_called = True
        return self._chat_response


def test_grounded_answer_with_citations():
    fake = FakeClient(
        search_results=[{
            "title": "PTO Policy", "url": "https://financeevolution.internal/hr/pto",
            "snippet": "20 days per year", "datasource": "interviewds", "doc_id": "1",
        }],
        chat_response={
            "answer": "You get 20 days of PTO per year.",
            "citations": [{"title": "PTO Policy", "url": "https://financeevolution.internal/hr/pto",
                           "snippet": "20 days per year"}],
        },
    )
    result = answer_question(fake, "How many PTO days?", datasource="interviewds")
    assert result["grounded"] is True
    assert "20 days" in result["answer"]
    assert result["sources"][0]["title"] == "PTO Policy"
    assert fake.chat_called is True


def test_empty_search_refuses_to_hallucinate():
    """The core guard: no search hits -> no Chat call, grounded 'I don't know'."""
    fake = FakeClient(search_results=[], chat_response={"answer": "SHOULD NOT APPEAR", "citations": []})
    result = answer_question(fake, "What is the capital of France?", datasource="interviewds")
    assert result["grounded"] is False
    assert result["answer"] == NO_RESULTS_MESSAGE
    assert result["sources"] == []
    assert fake.chat_called is False  # we never asked Chat to make something up


def test_falls_back_to_search_snippets_when_chat_empty():
    fake = FakeClient(
        search_results=[{
            "title": "VPN Guide", "url": "https://financeevolution.internal/it/vpn",
            "snippet": "Install GlobalConnect and log in with Okta.",
            "datasource": "interviewds", "doc_id": "2",
        }],
        chat_response={"answer": "", "citations": []},  # Chat returned nothing
    )
    result = answer_question(fake, "How do I set up VPN?", datasource="interviewds")
    assert result["grounded"] is True
    assert "VPN Guide" in result["answer"]
    assert result["sources"][0]["title"] == "VPN Guide"  # fell back to search hit


def test_include_citations_false_suppresses_sources():
    fake = FakeClient(
        search_results=[{"title": "X", "url": "u", "snippet": "s", "datasource": "d", "doc_id": "1"}],
        chat_response={"answer": "answer", "citations": [{"title": "X", "url": "u", "snippet": "s"}]},
    )
    result = answer_question(fake, "q", datasource="d", include_citations=False)
    assert result["sources"] == []


def test_blank_question_is_rejected():
    fake = FakeClient(search_results=[], chat_response={"answer": "", "citations": []})
    result = answer_question(fake, "   ")
    assert result["grounded"] is False
    assert "provide a question" in result["answer"].lower()


def test_chat_response_parser():
    """Directly exercise the raw Chat response parser."""
    raw = {
        "messages": [
            {"author": "GLEAN_AI", "fragments": [
                {"text": "The vacation policy allows "},
                {"text": "20 days."},
                {"citation": {"sourceDocument": {
                    "title": "Handbook", "url": "https://h", "snippet": "20 days of PTO"}}},
            ]},
        ]
    }
    parsed = GleanClient._parse_chat_response(raw)
    assert parsed["answer"] == "The vacation policy allows 20 days."
    assert len(parsed["citations"]) == 1
    assert parsed["citations"][0]["title"] == "Handbook"


if __name__ == "__main__":
    # Minimal runner so this works without pytest installed.
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {fn.__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
    raise SystemExit(0 if passed == len(fns) else 1)
