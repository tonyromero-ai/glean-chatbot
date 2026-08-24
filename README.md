# Glean Chatbot

Indexes a small set of internal contracts into Glean, answers questions from those
docs via Search + Chat, and exposes the same flow as an MCP tool (`ask_glean`).

## Requirements

- Python 3.10+
- A Glean instance
- An Indexing API token
- A Client API token with Search and Chat scopes

## Setup

1. Clone and enter the repo:

```bash
git clone <your-repo-url>
cd glean-chatbot
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create a `.env` from the example and fill in your values:

```bash
# macOS / Linux
cp .env.example .env

# Windows (PowerShell)
copy .env.example .env
```

| Variable | Required | Purpose |
|----------|----------|---------|
| `GLEAN_INSTANCE` | yes | Instance name (`https://<instance>-be.glean.com`) |
| `GLEAN_INDEXING_TOKEN` | yes | Indexing API token |
| `GLEAN_CLIENT_TOKEN` | yes | Client API token (Search + Chat) |
| `GLEAN_ACT_AS` | yes* | User email for `X-Glean-ActAs` (*needed with a global client token) |
| `GLEAN_DATASOURCE` | no | Datasource name (default `interviewds`) |
| `GLEAN_DATASOURCE_DISPLAY` | no | Display name in the Glean UI |
| `GLEAN_URL_REGEX` | no | Regex every doc `viewURL` must match |

`.env` is auto-loaded by `config.py` (via `python-dotenv`). You do not need to `source` it.

## Run

### Index documents

```bash
python scripts/index_documents.py
# optional: wait until Search can find them
python scripts/index_documents.py --verify
```

### Ask from the CLI

```bash
python scripts/ask.py "Who owns the Enronry Tony contract?"
python scripts/ask.py "What must OKLightning Tony deliver before go-live?" --top-k 3
```

### MCP (Cursor)

Project config lives at `.cursor/mcp.json` (absolute path to `src/mcp_server.py` + env vars).
Restart Cursor / reload MCP after editing it. The tool is `ask_glean`.

Smoke-test the server alone:

```bash
python src/mcp_server.py
```

### Tests

```bash
python tests/test_pipeline.py
```

No network; mocks Search/Chat.

## How it works

`scripts/index_documents.py` pushes `data/documents.json` through the Indexing API.
At query time, `src/pipeline.py` calls Search, then (only if there are hits) Chat with
those hits as closed-book context, and returns an answer plus sources. CLI and MCP
both call that same pipeline. Results are scoped to our own documents; if Search
returns nothing, we suggest close document titles instead of inventing an answer.

## Notes / limitations

- Shared sandbox ignores `datasourcesFilter`; we filter client-side on the document
  id prefix (`CUSTOM_<DATASOURCE>_Contract_`).
- Indexing is asynchronous — docs may take a few minutes to become searchable.
- Demo docs use `allowAnonymousAccess: true`. Do not ship that in production.
- Doc `viewURL`s must match `GLEAN_URL_REGEX` or indexing will reject them.

See `DESIGN_NOTE.md` for API tradeoffs and production notes.
