#!/usr/bin/env python3
"""
ask.py
------
Command-line entry point for the chatbot. Runs the same pipeline the MCP tool
uses, so the CLI and the MCP tool are guaranteed to behave identically.

Usage:
    python scripts/ask.py "How many PTO days do I get?"
    python scripts/ask.py "What's the VPN setup?" --top-k 3 --no-citations
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import Config          # noqa: E402
from glean_client import GleanClient  # noqa: E402
from pipeline import answer_question, format_answer  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask the Glean chatbot a question.")
    parser.add_argument("question", help="Natural-language question.")
    parser.add_argument("--top-k", type=int, default=5, help="Number of docs to retrieve.")
    parser.add_argument("--datasource", default=None,
                        help="Restrict retrieval to a datasource (defaults to configured one).")
    parser.add_argument("--no-citations", action="store_true", help="Suppress source list.")
    parser.add_argument("--debug", action="store_true", help="Verbose logging.")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    cfg = Config.from_env()
    client = GleanClient(
        cfg.instance, cfg.indexing_token, cfg.client_token, act_as=cfg.act_as,
    )

    result = answer_question(
        client,
        args.question,
        top_k=args.top_k,
        datasource=args.datasource or cfg.datasource,
        include_citations=not args.no_citations,
    )
    print(format_answer(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
