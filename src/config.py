"""
config.py
---------
Centralized configuration, loaded from environment variables so no secrets
live in the code. See .env.example for the full list.
"""

try:
    from dotenv import load_dotenv
    from pathlib import Path
    # .env lives in the project root, one level up from src/
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass  # dotenv optional; env vars can still be set manually

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    instance: str
    indexing_token: str
    client_token: str
    datasource: str
    datasource_display: str
    url_regex: str
    act_as: Optional[str]

    @classmethod
    def from_env(cls) -> "Config":
        def req(key: str) -> str:
            val = os.getenv(key, "").strip()
            if not val:
                raise RuntimeError(
                    f"Missing required environment variable: {key}. "
                    f"Copy .env.example to .env and fill it in (the .env file is now auto-loaded)."
                )
            return val

        return cls(
            instance=req("GLEAN_INSTANCE"),
            indexing_token=req("GLEAN_INDEXING_TOKEN"),
            client_token=req("GLEAN_CLIENT_TOKEN"),
            datasource=os.getenv("GLEAN_DATASOURCE", "interviewds").strip(),
            datasource_display=os.getenv("GLEAN_DATASOURCE_DISPLAY", "Finance Evolution Corp").strip(),
            url_regex=os.getenv("GLEAN_URL_REGEX", "^https://financeevolution.internal/.*").strip(),
            act_as=(os.getenv("GLEAN_ACT_AS") or "").strip() or None,
        )
