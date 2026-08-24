#!/usr/bin/env python3
"""
mcp_server.py
-------------
Exposes the chatbot as one MCP tool (`ask_glean`) over stdio. Thin adapter —
same pipeline as the CLI, so the demo and the tool behave identically.
"""

import logging
import os
import sys

# Make sibling imports work whether launched from repo root or from src/.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# mcp v1: FastMCP; v2 renamed it to MCPServer — support both installs.
try:
    from mcp.server.fastmcp import FastMCP  # mcp v1.x
except ImportError:  # pragma: no cover
    from mcp.server import MCPServer as FastMCP  # mcp v2.x

from config import Config  # noqa: E402
from glean_client import GleanClient, GleanError  # noqa: E402
from pipeline import answer_question  # noqa: E402

# stdout is the MCP protocol channel — logs must go to stderr only.
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("mcp_server")

mcp = FastMCP("glean-chatbot")

# Build once at startup so missing config fails loudly before any tool call.
_cfg = Config.from_env()
_client = GleanClient(
    _cfg.instance, _cfg.indexing_token, _cfg.client_token, act_as=_cfg.act_as,
)


@mcp.tool()
def ask_glean(
    question: str,
    datasource: str | None = None,
    top_k: int = 5,
    include_citations: bool = True,
) -> dict:
    """
    Answer a natural-language question using company documents indexed in Glean.

    Retrieves relevant documents via the Glean Search API and generates a grounded
    answer via the Glean Chat API. If nothing relevant is found, it returns a clear
    'no grounded answer' response instead of guessing.

    Args:
        question: The natural-language question to answer. (required)
        datasource: Restrict retrieval to a specific Glean datasource. Defaults to
            the configured one (the indexed company corpus).
        top_k: How many documents to retrieve from Search (default 5).
        include_citations: Whether to include the list of source documents.

    Returns:
        A dict with:
          answer:   the grounded natural-language answer
          sources:  list of {title, url, snippet} the answer is grounded in
          grounded: bool, False when no relevant content was found
    """
    ds = datasource or _cfg.datasource
    log.info("ask_glean(question=%r, datasource=%r, top_k=%d)", question, ds, top_k)
    try:
        result = answer_question(
            _client,
            question,
            top_k=top_k,
            datasource=ds,
            include_citations=include_citations,
        )
    except GleanError as e:
        # Return a structured error to the MCP client instead of a stack trace.
        log.error("Glean API error: %s %s", e.status, e.body)
        return {
            "answer": f"Error contacting Glean ({e.status}). {e}",
            "sources": [],
            "grounded": False,
            "error": True,
        }

    return {
        "answer": result["answer"],
        "sources": result["sources"],
        "grounded": result["grounded"],
    }


if __name__ == "__main__":
    log.info("Starting glean-chatbot MCP server on stdio...")
    mcp.run()
