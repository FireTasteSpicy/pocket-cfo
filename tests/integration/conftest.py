"""Skip the model-dependent integration tests when no credentials are configured.

The integration tests actually call Gemini, so they need either a
`GEMINI_API_KEY` (AI Studio) or Vertex credentials. On a clean checkout without
credentials, they SKIP rather than fail — so `make test` stays green and the
unit suite (which needs no key) is the deterministic reproducibility signal.
Provide a key and they run for real.
"""

from __future__ import annotations

import os

import pytest

# Load .env so a locally-configured GEMINI_API_KEY is visible to the integration
# tests (pytest does not read .env on its own). No-op if python-dotenv or .env is
# absent, so the clean-checkout skip behavior is preserved.
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


def _has_model_credentials() -> bool:
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return True
    return os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true"


def pytest_collection_modifyitems(config, items) -> None:
    # This hook sees the WHOLE session's items, so we must skip only the ones under
    # tests/integration/ — not the deterministic unit suite.
    if _has_model_credentials():
        return
    skip = pytest.mark.skip(
        reason="needs GEMINI_API_KEY or Vertex creds (model-dependent integration test)"
    )
    for item in items:
        if "integration" in item.nodeid.split("::", 1)[0].split("/"):
            item.add_marker(skip)
