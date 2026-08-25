# Design Note

Short write-up of how this chatbot works and what I'd change for production.

## 1. The three Glean APIs

**What we're indexing.** Five client contracts in `data/documents.json`. Each one
has terms, owners, and obligations. They go in as `Contract` objects.

**Indexing API** — push docs into Glean.

`scripts/index_documents.py` creates the datasource (if needed), then pushes each
doc with `/indexdocument`. I marked it as a test datasource so it doesn't mess with
ranking in the shared sandbox.

Each doc gets: id, title, viewURL, body, and metadata as `customProperties` (client,
owner, contractValue, startDate, endDate, contractId, department).

Why `/indexdocument` and not bulk? There are only five docs. I want to see each one
succeed or fail on its own. Bulk makes sense when you're replacing a whole corpus at
once or have thousands of docs — not here.

**Search API** — find relevant docs for a question.

Calls `/rest/api/v1/search` with a `datasourcesFilter` to scope to our datasource.
Also sends `X-Glean-ActAs` with a user email. Our Client token is global, so Glean
needs to know which user we're acting as. Results are trimmed to what that user can
see. Indexing calls don't use this header.

Results get normalized to `{title, url, snippet, datasource, doc_id}` so the rest of
the code doesn't depend on Glean's raw response shape.

**Scoping in the shared sandbox**

The sandbox ignores `datasourcesFilter`. Search was returning other people's docs.

Fix for the demo: after Search returns, I filter client-side on document IDs. Ours
look like `CUSTOM_INTERVIEWDS_Contract_...`. Anything that doesn't match gets dropped.

That's a workaround. In production you'd give each customer their own datasource and
let Glean enforce isolation — not filter in app code.

**Chat API** — generate the answer.

Calls `/rest/api/v1/chat`. Same `X-Glean-ActAs` header as Search, same reason.

Important: I don't let Chat do its own retrieval. I pass the Search results into the
prompt and tell the model to answer only from those docs. If the answer isn't in the
context, it should say so. That way the answer can't drift into general knowledge or
other indexed content.

## 2. End-to-end flow

```
data/documents.json
        │
        ▼  scripts/index_documents.py
   [1] INDEX  ── Indexing API ──► Glean datasource + documents
                                        │
   User question (CLI or MCP ask_glean)  │
        │                                │
        ▼                                │
   src/pipeline.py                       │
        │                                │
   [2] SEARCH ◄── Search API ────────────┘
        │         (retrieve hits)
        │
        ├─ no hits? ──► do NOT call Chat
        │               return "did you mean" / available titles
        │               (grounded=False)
        │
        └─ hits? ──► [3] CLOSED-BOOK CHAT
                          Chat API, with Search hits as the only context
                          │
                          ▼
                     [4] GROUNDED ANSWER + SOURCES
                          {answer, sources, retrieved, grounded=True}
```

CLI (`scripts/ask.py`) and MCP (`src/mcp_server.py`) are thin adapters over the
same `answer_question()` pipeline. Whatever the CLI prints is what the MCP tool
returns (minus formatting).

When Search returns nothing, `difflib` suggests close document titles or lists what's
available. When Search hits but Chat comes back empty, I fall back to a snippet from
the top result.

## 3. Tradeoffs (what I skipped on purpose)

- **REST, not the SDK.** Easier to see exactly what's going over the wire. Would use
  the official SDK in production for retries and typed models.
- **Client-side ID filtering.** Only needed because the sandbox is shared.
- **Anonymous access on indexed docs.** Fine for a demo. Not for real customers.
- **Single question, no memory.** One shot Q&A. Multi-turn is a small add later.
- **No caching, backoff, or metrics.** Logs errors by status code (401 vs 400 vs
  500). Would add tracing and dashboards before rollout.

## 4. What production would look like

**Permissions.** Index real ACLs per document. Run Search and Chat as the requesting
user (we already use ActAs as a step toward that). Glean trims answers to what that
person can see — that's the main reason to use Glean instead of a plain vector DB.

**Multiple teams.** One datasource per team or source system. Drop the client-side ID
hack once each tenant has their own datasource. Move from a script to scheduled sync
— incremental updates with `/indexdocument`, full refreshes with bulk when needed.

**How to expose it.** MCP for agents and IDEs (already done). REST wrapper for a
support bot that needs high throughput. Same pipeline behind both.

**Observability.** Track retrieval count, latency, grounded vs refused answers,
empty-result rate. Those tell you when indexing or coverage is broken.

**Rollout.** Test datasource → small pilot group → one team → wider. Use Admin
Console to enable search gradually. Watch refusal and error rates before expanding.

**Rough plan:** design (schema, permissions, success criteria) → build (sync jobs,
service endpoints) → test (ACL correctness, answer quality on a labeled set) →
rollout with a pilot team.

People involved: doc owners, IT/identity, security, support, and a pilot user group.
