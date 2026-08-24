"""
pipeline.py
-----------
End-to-end RAG flow: Search first, refuse if empty, then closed-book Chat over
the retrieved docs. Shared by the CLI and the MCP tool so both behave identically.
"""

from __future__ import annotations

import difflib
import logging
import re
from typing import Optional

from glean_client import GleanClient

logger = logging.getLogger("pipeline")

NO_RESULTS_MESSAGE = (
    "I couldn't find anything about that in the indexed documents, so I don't "
    "have a grounded answer. Try rephrasing, or check that the relevant document "
    "has been indexed into the datasource."
)


def _get_available_titles(
    client: GleanClient,
    datasource: Optional[str] = None,
    limit: int = 10,
) -> list[str]:
    """Unique document titles from a broad search (oversample for client-side filter)."""
    try:
        # Oversample: sandbox client-side id filter discards most hits, so ask for more.
        results = client.search(
            "contract", page_size=max(limit * 4, 30), datasource=datasource,
        )
        titles: list[str] = []
        seen: set[str] = set()
        for result in results:
            title = (result.get("title") or "").strip()
            if title and title not in seen:
                seen.add(title)
                titles.append(title)
            if len(titles) >= limit:
                break
        return titles
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch available titles: %s", exc)
        return []


def _find_close_title_matches(
    question: str,
    titles: list[str],
    n: int = 3,
    cutoff: float = 0.4,
) -> list[str]:
    """Fuzzy-match question words to title words, then fall back to full-title matches."""
    try:
        if not titles:
            return []

        matches: list[str] = []
        seen: set[str] = set()

        def add_title(title: str) -> None:
            if title and title not in seen:
                seen.add(title)
                matches.append(title)

        # Match query words against individual title-words (not whole titles),
        # so typos like "Enronryy" can still hit "Enronry Tony - ...".
        word_to_titles: dict[str, list[str]] = {}
        for title in titles:
            for word in re.findall(r"\w+", title.lower()):
                if len(word) >= 4 and title not in word_to_titles.setdefault(word, []):
                    word_to_titles[word].append(title)
        title_words = list(word_to_titles)

        # Primary: query words vs title-words (typo-tolerant)
        for q_word in re.findall(r"\w+", question.lower()):
            if len(q_word) < 4:
                continue
            for close_word in difflib.get_close_matches(q_word, title_words, n=n, cutoff=0.7):
                for title in word_to_titles.get(close_word, []):
                    add_title(title)
            if len(matches) >= n:
                return matches[:n]

        # Secondary: full question / words vs complete titles
        for title in difflib.get_close_matches(question, titles, n=n, cutoff=cutoff):
            add_title(title)
        for word in re.findall(r"\w+", question):
            for title in difflib.get_close_matches(word, titles, n=n, cutoff=cutoff):
                add_title(title)
            if len(matches) >= n:
                break

        return matches[:n]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Close-title matching failed: %s", exc)
        return []


def _no_results_answer(
    client: GleanClient,
    question: str,
    datasource: Optional[str] = None,
) -> dict:
    """
    Empty Search → never call Chat (would risk hallucination). Instead suggest
    close title matches via difflib, or list what we can answer about.
    """
    titles = _get_available_titles(client, datasource=datasource)
    close_matches = _find_close_title_matches(question, titles)
    if close_matches:
        answer = (
            "I couldn't find an exact match for that. Did you mean one of these? "
            + "; ".join(close_matches)
        )
    elif titles:
        answer = (
            "I couldn't find anything matching that. Here are the documents I can "
            "answer questions about: "
            + "; ".join(titles)
        )
    else:
        answer = NO_RESULTS_MESSAGE

    return {
        "answer": answer,
        "sources": [],
        "retrieved": [],
        "grounded": False,
    }


def answer_question(
    client: GleanClient,
    question: str,
    top_k: int = 5,
    datasource: Optional[str] = None,
    include_citations: bool = True,
) -> dict:
    """
    Search first (inspectable retrieval), guard on empty, then closed-book Chat.
    Running Search before Chat lets us refuse to answer when nothing is relevant.
    """
    question = (question or "").strip()
    if not question:
        return {
            "answer": "Please provide a question.",
            "sources": [],
            "retrieved": [],
            "grounded": False,
        }

    # 1. Retrieve — explicit, inspectable set we control and can show the user.
    retrieved = client.search(question, page_size=top_k, datasource=datasource)
    logger.info("Search returned %d result(s) for %r", len(retrieved), question)

    # 2. Guard — no hits ⇒ no Chat call, so the model cannot invent an answer.
    if not retrieved:
        return _no_results_answer(client, question, datasource=datasource)

    # 3. Generate — closed-book: only the Search hits are allowed as context.
    chat_result = client.chat(question, context_docs=retrieved, datasource=datasource)
    answer = chat_result["answer"] or ""
    chat_citations = chat_result["citations"]

    # If Chat returns empty, fall back to a snippet summary still tied to a source.
    if not answer:
        top = retrieved[0]
        answer = (
            f"Based on the indexed documents, the most relevant is "
            f"\"{top['title']}\". {top['snippet']}"
        ).strip()

    # Prefer Chat citations (what grounded the answer); else Search hits.
    sources = chat_citations if chat_citations else _as_sources(retrieved)
    if not include_citations:
        sources = []

    return {
        "answer": answer,
        "sources": sources,
        "retrieved": retrieved,
        "grounded": True,
    }


def _as_sources(retrieved: list[dict]) -> list[dict]:
    return [
        {"title": r["title"], "url": r["url"], "snippet": r["snippet"]}
        for r in retrieved
    ]


def format_answer(result: dict) -> str:
    """Render a result dict as human-readable text with citations."""
    lines = [result["answer"]]
    sources = result.get("sources", [])
    if sources:
        lines.append("")
        lines.append("Sources:")
        for i, s in enumerate(sources, 1):
            title = s.get("title", "(untitled)")
            url = s.get("url", "")
            lines.append(f"  [{i}] {title}" + (f" - {url}" if url else ""))
    return "\n".join(lines)
