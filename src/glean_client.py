"""
glean_client.py
---------------
Thin REST wrapper over Glean's three APIs: Indexing (push docs), Search (retrieve),
and Chat (generate). Uses `requests` so every request/response shape stays visible.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import requests

logger = logging.getLogger("glean")


class GleanError(RuntimeError):
    """Raised when a Glean API call fails. Carries status + body for debugging."""

    def __init__(self, message: str, status: Optional[int] = None, body: Optional[str] = None):
        super().__init__(message)
        self.status = status
        self.body = body


class GleanClient:
    def __init__(
        self,
        instance: str,
        indexing_token: str,
        client_token: str,
        timeout: int = 30,
        act_as: Optional[str] = None,
    ):
        # Two bases: Indexing uses /api/index/v1 + indexing token;
        # Search/Chat use /rest/api/v1 + client token.
        self.base = f"https://{instance}-be.glean.com"
        self.index_base = f"{self.base}/api/index/v1"
        self.client_base = f"{self.base}/rest/api/v1"
        self.indexing_token = indexing_token
        self.client_token = client_token
        self.timeout = timeout
        # Global Client API tokens must name a user; results are ACL-scoped to them.
        self.act_as = act_as
        self.session = requests.Session()

    def _act_as_headers(self) -> Optional[dict]:
        # Search/Chat only — Indexing does not need (or accept) X-Glean-ActAs.
        return {"X-Glean-ActAs": self.act_as} if self.act_as else None

    def _post(self, url: str, token: str, payload: dict,
              extra_headers: Optional[dict] = None) -> dict:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            **(extra_headers or {}),
        }
        logger.debug("POST %s payload=%s", url, payload)
        try:
            resp = self.session.post(url, headers=headers, json=payload, timeout=self.timeout)
        except requests.RequestException as e:
            raise GleanError(f"Network error calling {url}: {e}") from e

        if resp.status_code >= 400:
            # Preserve status/body so callers can distinguish auth vs payload vs 5xx.
            raise GleanError(
                f"Glean API {resp.status_code} at {url}",
                status=resp.status_code,
                body=resp.text[:2000],
            )
        if not resp.text:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text}

    # --- Indexing API (/api/index/v1, indexing token) ---

    def add_datasource(self, name: str, display_name: str, url_regex: str,
                       object_types: list[str], is_test: bool = True) -> dict:
        """Create/update a custom datasource. Idempotent on `name`."""
        return self._post(f"{self.index_base}/adddatasource", self.indexing_token, {
            "name": name,
            "displayName": display_name,
            "datasourceCategory": "PUBLISHED_CONTENT",
            "urlRegex": url_regex,
            "objectDefinitions": [
                {"name": ot, "docCategory": "PUBLISHED_CONTENT"} for ot in object_types
            ],
            # Test datasource: keeps ranking signals off in the shared sandbox.
            "isTestDatasource": is_test,
            "isUserReferencedByEmail": True,
        })

    def index_document(self, datasource: str, doc: dict) -> dict:
        """Push a single document (internal schema -> Glean document shape)."""
        glean_doc = {
            "datasource": datasource,
            "objectType": doc.get("objectType", "Document"),
            "id": doc["id"],
            "title": doc["title"],
            "viewURL": doc["url"],  # must match datasource urlRegex or indexing rejects it
            "body": {"mimeType": "text/plain", "textContent": doc["body"]},
            "permissions": {"allowAnonymousAccess": True},  # demo only; not production-safe
        }
        custom = [
            {"name": key, "value": str(doc[key])}
            for key in ("author", "department", "client", "owner",
                        "contractValue", "startDate", "endDate", "updatedAt")
            if doc.get(key)
        ]
        if custom:
            glean_doc["customProperties"] = custom

        return self._post(
            f"{self.index_base}/indexdocument",
            self.indexing_token,
            {"document": glean_doc},
        )

    def get_document_status(self, datasource: str, doc_id: str, object_type: str) -> dict:
        """Debugging helper: check upload/indexing status of a document."""
        return self._post(f"{self.index_base}/getdocumentstatus", self.indexing_token, {
            "datasource": datasource,
            "docId": doc_id,
            "objectType": object_type,
        })

    # --- Search API (/rest/api/v1, client token + ActAs) ---

    def search(self, query: str, page_size: int = 5,
               datasource: Optional[str] = None,
               id_prefix: Optional[str] = None) -> list[dict]:
        """
        Retrieve relevant docs for a query.

        The sandbox ignores server-side `datasourcesFilter`, so we also filter
        client-side on Glean's id namespace: CUSTOM_<DATASOURCE>_<objectType>_<id>.
        """
        request_options: dict[str, Any] = {"facetBucketSize": 10}
        if datasource:
            request_options["datasourcesFilter"] = [datasource]

        data = self._post(
            f"{self.client_base}/search",
            self.client_token,
            {"query": query, "pageSize": page_size, "requestOptions": request_options},
            extra_headers=self._act_as_headers(),
        )

        # Sandbox ignores datasourcesFilter; Glean ids look like CUSTOM_INTERVIEWDS_Contract_...
        # so we scope to our contracts by that prefix (objectType, not company name).
        prefix = id_prefix
        if prefix is None and datasource:
            prefix = f"CUSTOM_{datasource.upper()}_Contract_"

        results = []
        for r in data.get("results", []) or []:
            doc = r.get("document", {}) or {}
            meta = doc.get("metadata", {}) or {}
            doc_id = doc.get("id") or meta.get("documentId", "")
            if prefix and not str(doc_id).startswith(prefix):
                continue

            # Real Search responses put snippet text in "text"; fall back to "snippet".
            snippets = r.get("snippets", []) or []
            snippet_text = " ".join(
                (s.get("text") or s.get("snippet") or "") for s in snippets
            ).strip()
            results.append({
                "title": r.get("title", "(untitled)"),
                "url": r.get("url", ""),
                "snippet": snippet_text,
                "datasource": doc.get("datasource", meta.get("datasource", "")),
                "doc_id": doc_id,
            })
        return results

    # --- Chat API (/rest/api/v1, client token + ActAs) ---

    def chat(self, question: str, context_docs: Optional[list] = None,
             datasource: Optional[str] = None) -> dict:
        """
        Ask Chat for a grounded answer. When context_docs is provided, answer
        closed-book from those docs only. Returns {answer, citations}.
        """
        # Closed-book: pass our Search hits as the only allowed context so Chat
        # cannot invent answers from other knowledge or its own retrieval.
        if context_docs is not None:
            parts = [
                "You are answering a question using ONLY the context documents provided below. "
                "If the answer is not contained in the context, say you don't have that information. "
                "Do not use any other knowledge or sources.\n\n"
                "=== CONTEXT DOCUMENTS ===\n",
            ]
            for doc in context_docs:
                parts.append(
                    f"Title: {doc.get('title', '')}\n"
                    f"URL: {doc.get('url', '')}\n"
                    f"Content: {doc.get('snippet', '')}\n\n"
                )
            parts.append(f"=== QUESTION ===\n{question}")
            message_text = "".join(parts)
        else:
            message_text = question

        payload: dict[str, Any] = {
            "messages": [{"author": "USER", "fragments": [{"text": message_text}]}],
        }
        # Belt-and-suspenders: also ask Chat to scope its own retrieval to our datasource.
        if datasource:
            payload["inclusions"] = {
                "filters": [{"fieldName": "datasource", "values": [
                    {"value": datasource, "relationType": "EQUALS"},
                ]}],
            }

        data = self._post(
            f"{self.client_base}/chat",
            self.client_token,
            payload,
            extra_headers=self._act_as_headers(),
        )
        return self._parse_chat_response(data)

    @staticmethod
    def _parse_chat_response(data: dict) -> dict:
        """Concatenate GLEAN_AI text fragments and collect citations."""
        answer_parts: list[str] = []
        citations: list[dict] = []

        for msg in data.get("messages", []):
            if msg.get("author") not in (None, "GLEAN_AI"):
                continue
            for frag in msg.get("fragments", []):
                if frag.get("text"):
                    answer_parts.append(frag["text"])
                cit = frag.get("citation")
                if cit:
                    src = cit.get("sourceDocument", {}) or {}
                    citations.append({
                        "title": src.get("title", "(untitled)"),
                        "url": src.get("url", ""),
                        "snippet": src.get("snippet", ""),
                    })

        return {"answer": "".join(answer_parts).strip(), "citations": citations}
