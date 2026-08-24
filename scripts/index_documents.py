#!/usr/bin/env python3
"""
index_documents.py
------------------
Creates (or updates) the datasource and pushes the document corpus into Glean
via the Indexing API. Run this once before using the chatbot.

Usage:
    python scripts/index_documents.py
    python scripts/index_documents.py --data data/documents.json --verify
"""

import argparse
import json
import logging
import os
import sys
import time

# make src/ importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import Config          # noqa: E402
from glean_client import GleanClient, GleanError  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("index")


def main() -> int:
    parser = argparse.ArgumentParser(description="Index documents into Glean.")
    parser.add_argument("--data", default="data/documents.json", help="Path to documents JSON.")
    parser.add_argument("--verify", action="store_true",
                        help="After indexing, poll search until docs appear.")
    args = parser.parse_args()

    cfg = Config.from_env()
    client = GleanClient(
        cfg.instance, cfg.indexing_token, cfg.client_token, act_as=cfg.act_as,
    )

    with open(args.data) as f:
        docs = json.load(f)
    log.info("Loaded %d documents from %s", len(docs), args.data)

    object_types = sorted({d.get("objectType", "Document") for d in docs})

    # 1. Create / update the datasource (idempotent on name).
    log.info("Ensuring datasource %r exists...", cfg.datasource)
    try:
        client.add_datasource(
            name=cfg.datasource,
            display_name=cfg.datasource_display,
            url_regex=cfg.url_regex,
            object_types=object_types,
            is_test=True,
        )
        log.info("Datasource ready.")
    except GleanError as e:
        # In the shared sandbox the datasource may already exist / be admin-owned;
        # that's fine, we can still index into it.
        log.warning("add_datasource returned %s (continuing): %s", e.status, e.body)

    # 2. Index each document.
    ok, failed = 0, 0
    for d in docs:
        try:
            client.index_document(cfg.datasource, d)
            log.info("Indexed %s (%s)", d["id"], d["title"])
            ok += 1
        except GleanError as e:
            log.error("FAILED to index %s: %s %s", d["id"], e.status, e.body)
            failed += 1

    log.info("Indexing complete: %d ok, %d failed.", ok, failed)

    # 3. Optionally verify discoverability (indexing is async; can take minutes).
    if args.verify:
        log.info("Verifying discoverability (indexing is asynchronous)...")
        probe = docs[0]["title"].split()[0]
        for attempt in range(1, 11):
            hits = client.search(probe, page_size=5, datasource=cfg.datasource)
            if hits:
                log.info("Verified: %d result(s) for probe %r on attempt %d.",
                         len(hits), probe, attempt)
                break
            log.info("Attempt %d: not searchable yet, waiting 30s...", attempt)
            time.sleep(30)
        else:
            log.warning("Documents not searchable after polling. They may still "
                        "be indexing, or the datasource needs to be enabled for "
                        "search in the Admin Console.")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
